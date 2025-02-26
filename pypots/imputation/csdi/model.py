"""
The implementation of CSDI for the partially-observed time-series imputation task.

Refer to the paper Tashiro, Y., Song, J., Song, Y., & Ermon, S. (2021).
CSDI: Conditional Score-based Diffusion Models for Probabilistic Time Series Imputation. NeurIPS 2021.

Notes
-----
Partial implementation uses code from the official implementation https://github.com/ermongroup/CSDI.

"""

# Created by Wenjie Du <wenjay.du@gmail.com>
# License: BSD-3-Clause

from typing import Union, Optional

import numpy as np
import torch
from torch.utils.data import DataLoader

from .data import DatasetForCSDI
from .modules import _CSDI
from ..base import BaseNNImputer
from ...optim.adam import Adam
from ...optim.base import Optimizer
from ...utils.logging import logger


class CSDI(BaseNNImputer):
    """The PyTorch implementation of the CSDI model :cite:`tashiro2021csdi`.

    Parameters
    ----------
    n_features :
        The number of features in the time-series data sample.

    n_layers :
        The number of layers in the 1st and 2nd DMSA blocks in the SAITS model.

    n_heads :
        The number of heads in the multi-head attention mechanism.

    n_channels :
        The number of residual channels.

    d_time_embedding :
        The dimension number of the time (temporal) embedding.

    d_feature_embedding :
        The dimension number of the feature embedding.

    d_diffusion_embedding :
        The dimension number of the diffusion embedding.

    is_unconditional :
        Whether the model is unconditional or conditional.

    target_strategy :
        The strategy for selecting the target for the diffusion process. It has to be one of ["mix", "random"].

    n_diffusion_steps :
        The number of the diffusion step T in the original paper.

    schedule:
        The schedule for other noise levels. It has to be one of ["quad", "linear"].

    beta_start:
        The minimum noise level.

    beta_end:
        The maximum noise level.

    batch_size :
        The batch size for training and evaluating the model.

    epochs :
        The number of epochs for training the model.

    patience :
        The patience for the early-stopping mechanism. Given a positive integer, the training process will be
        stopped when the model does not perform better after that number of epochs.
        Leaving it default as None will disable the early-stopping.

    optimizer :
        The optimizer for model training.
        If not given, will use a default Adam optimizer.

    num_workers :
        The number of subprocesses to use for data loading.
        `0` means data loading will be in the main process, i.e. there won't be subprocesses.

    device :
        The device for the model to run on. It can be a string, a :class:`torch.device` object, or a list of them.
        If not given, will try to use CUDA devices first (will use the default CUDA device if there are multiple),
        then CPUs, considering CUDA and CPU are so far the main devices for people to train ML models.
        If given a list of devices, e.g. ['cuda:0', 'cuda:1'], or [torch.device('cuda:0'), torch.device('cuda:1')] , the
        model will be parallely trained on the multiple devices (so far only support parallel training on CUDA devices).
        Other devices like Google TPU and Apple Silicon accelerator MPS may be added in the future.

    saving_path :
        The path for automatically saving model checkpoints and tensorboard files (i.e. loss values recorded during
        training into a tensorboard file). Will not save if not given.

    model_saving_strategy :
        The strategy to save model checkpoints. It has to be one of [None, "best", "better"].
        No model will be saved when it is set as None.
        The "best" strategy will only automatically save the best model after the training finished.
        The "better" strategy will automatically save the model during training whenever the model performs
        better than in previous epochs.

    References
    ----------
    .. [1] `Yusuke Tashiro, Jiaming Song, Yang Song, Stefano Ermon.
        "CSDI: Conditional Score-based Diffusion Models for Probabilistic Time Series Imputation".
        NeurIPS 2021.
        <https://proceedings.neurips.cc/paper/2021/hash/cfe8504bda37b575c70ee1a8276f3486-Abstract.html>`_

    """

    def __init__(
        self,
        n_features: int,
        n_layers: int,
        n_heads: int,
        n_channels: int,
        d_time_embedding: int,
        d_feature_embedding: int,
        d_diffusion_embedding: int,
        is_unconditional: bool = False,
        target_strategy: str = "random",
        n_diffusion_steps: int = 50,
        schedule: str = "quad",
        beta_start: float = 0.0001,
        beta_end: float = 0.5,
        batch_size: int = 32,
        epochs: int = 100,
        patience: Optional[int] = None,
        optimizer: Optional[Optimizer] = Adam(),
        num_workers: int = 0,
        device: Optional[Union[str, torch.device, list]] = None,
        saving_path: Optional[str] = None,
        model_saving_strategy: Optional[str] = "best",
    ):
        super().__init__(
            batch_size,
            epochs,
            patience,
            num_workers,
            device,
            saving_path,
            model_saving_strategy,
        )
        assert target_strategy in ["mix", "random"]
        assert schedule in ["quad", "linear"]

        # set up the model
        self.model = _CSDI(
            n_layers,
            n_heads,
            n_channels,
            n_features,
            d_time_embedding,
            d_feature_embedding,
            d_diffusion_embedding,
            is_unconditional,
            target_strategy,
            n_diffusion_steps,
            schedule,
            beta_start,
            beta_end,
        )
        self._print_model_size()
        self._send_model_to_given_device()

        # set up the optimizer
        self.optimizer = optimizer
        self.optimizer.init_optimizer(self.model.parameters())

    def _assemble_input_for_training(self, data: list) -> dict:
        (
            indices,
            observed_data,
            observed_mask,
            observed_tp,
            gt_mask,
            for_pattern_mask,
            cut_length,
        ) = self._send_data_to_given_device(data)

        inputs = {
            "observed_data": observed_data.permute(0, 2, 1),
            "observed_mask": observed_mask.permute(0, 2, 1),
            "observed_tp": observed_tp,
            "gt_mask": gt_mask.permute(0, 2, 1),
            "for_pattern_mask": for_pattern_mask,
            "cut_length": cut_length,
        }
        return inputs

    def _assemble_input_for_validating(self, data) -> dict:
        return self._assemble_input_for_training(data)

    def _assemble_input_for_testing(self, data) -> dict:
        return self._assemble_input_for_validating(data)

    def fit(
        self,
        train_set: Union[dict, str],
        val_set: Optional[Union[dict, str]] = None,
        file_type: str = "h5py",
        n_sampling_times: int = 1,
    ) -> None:
        # Step 1: wrap the input data with classes Dataset and DataLoader
        training_set = DatasetForCSDI(
            train_set, return_labels=False, file_type=file_type
        )
        training_loader = DataLoader(
            training_set,
            batch_size=self.batch_size,
            shuffle=True,
            num_workers=self.num_workers,
        )
        val_loader = None
        if val_set is not None:
            val_set = DatasetForCSDI(val_set, return_labels=False, file_type=file_type)
            val_loader = DataLoader(
                val_set,
                batch_size=self.batch_size,
                shuffle=False,
                num_workers=self.num_workers,
            )

        # Step 2: train the model and freeze it
        self._train_model(training_loader, val_loader)
        self.model.load_state_dict(self.best_model_dict)
        self.model.eval()  # set the model as eval status to freeze it.

        # Step 3: save the model if necessary
        self._auto_save_model_if_necessary(training_finished=True)

    def predict(
        self,
        test_set: Union[dict, str],
        file_type: str = "h5py",
        n_sampling_times: int = 1,
    ) -> dict:
        """

        Parameters
        ----------
        test_set : dict or str
            The dataset for model validating, should be a dictionary including keys as 'X' and 'y',
            or a path string locating a data file.
            If it is a dict, X should be array-like of shape [n_samples, sequence length (time steps), n_features],
            which is time-series data for validating, can contain missing values, and y should be array-like of shape
            [n_samples], which is classification labels of X.
            If it is a path string, the path should point to a data file, e.g. a h5 file, which contains
            key-value pairs like a dict, and it has to include keys as 'X' and 'y'.

        file_type : str
            The type of the given file if test_set is a path string.

        n_sampling_times:
            The number of sampling times for the model to sample from the diffusion process.

        Returns
        -------
        result_dict: dict
            Prediction results in a Python Dictionary for the given samples.
            It should be a dictionary including a key named 'imputation'.

        """
        # Step 1: wrap the input data with classes Dataset and DataLoader
        self.model.eval()  # set the model as eval status to freeze it.
        test_set = DatasetForCSDI(test_set, return_labels=False, file_type=file_type)
        test_loader = DataLoader(
            test_set,
            batch_size=self.batch_size,
            shuffle=False,
            num_workers=self.num_workers,
        )
        imputation_collector = []

        # Step 2: process the data with the model
        with torch.no_grad():
            for idx, data in enumerate(test_loader):
                inputs = self._assemble_input_for_testing(data)
                results = self.model(
                    inputs,
                    training=False,
                    n_sampling_times=n_sampling_times,
                )
                imputed_data = results["imputed_data"]
                imputation_collector.append(imputed_data)

        # Step 3: output collection and return
        imputation = torch.cat(imputation_collector).cpu().detach().numpy()
        result_dict = {
            "imputation": imputation,
        }
        return result_dict

    def impute(
        self,
        X: Union[dict, str],
        file_type="h5py",
    ) -> np.ndarray:
        logger.warning(
            "🚨DeprecationWarning: The method impute is deprecated. Please use `predict` instead."
        )
        results_dict = self.predict(X, file_type=file_type)
        return results_dict["imputation"]
