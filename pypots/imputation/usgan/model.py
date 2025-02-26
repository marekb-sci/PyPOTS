"""
The implementation of USGAN for the partially-observed time-series imputation task.

Refer to the paper "Miao, X., Wu, Y., Wang, J., Gao, Y., Mao, X., & Yin, J. (2021).
Generative Semi-supervised Learning for Multivariate Time Series Imputation. AAAI 2021."

"""

# Created by Jun Wang <jwangfx@connect.ust.hk> and Wenjie Du <wenjay.du@gmail.com>
# License: BSD-3-Clause

from typing import Union, Optional

import h5py
import numpy as np
import torch
from torch.utils.data import DataLoader

from .data import DatasetForUSGAN
from .modules import _USGAN
from ..base import BaseNNImputer
from ...optim.adam import Adam
from ...optim.base import Optimizer
from ...utils.logging import logger


class USGAN(BaseNNImputer):
    """The PyTorch implementation of the USGAN model. Refer to :cite:`miao2021SSGAN`.

    Parameters
    ----------
    n_steps : int
        The number of time steps in the time-series data sample.

    n_features : int
        The number of features in the time-series data sample.

    rnn_hidden_size : int
        The hidden size of the RNN cell

    lambda_mse : float
        The weight of the reconstruction loss

    hint_rate : float
        The hint rate for the discriminator

    dropout_rate : float
        The dropout rate for the last layer in Discriminator

    G_steps : int
        The number of steps to train the generator in each iteration.

    D_steps : int
        The number of steps to train the discriminator in each iteration.

    batch_size : int
        The batch size for training and evaluating the model.

    epochs : int
        The number of epochs for training the model.

    patience : int
        The patience for the early-stopping mechanism. Given a positive integer, the training process will be
        stopped when the model does not perform better after that number of epochs.
        Leaving it default as None will disable the early-stopping.

    G_optimizer : :class:`pypots.optim.Optimizer`
        The optimizer for the generator training.
        If not given, will use a default Adam optimizer.

    D_optimizer : :class:`pypots.optim.Optimizer`
        The optimizer for the discriminator training.
        If not given, will use a default Adam optimizer.

    num_workers : int
        The number of subprocesses to use for data loading.
        `0` means data loading will be in the main process, i.e. there won't be subprocesses.

    device : Union[str, torch.device, list]
        The device for the model to run on. It can be a string, a :class:`torch.device` object, or a list of them.
        If not given, will try to use CUDA devices first (will use the default CUDA device if there are multiple),
        then CPUs, considering CUDA and CPU are so far the main devices for people to train ML models.
        If given a list of devices, e.g. ['cuda:0', 'cuda:1'], or [torch.device('cuda:0'), torch.device('cuda:1')] , the
        model will be parallely trained on the multiple devices (so far only support parallel training on CUDA devices).
        Other devices like Google TPU and Apple Silicon accelerator MPS may be added in the future.

    saving_path : str
        The path for automatically saving model checkpoints and tensorboard files (i.e. loss values recorded during
        training into a tensorboard file). Will not save if not given.

    model_saving_strategy : str
        The strategy to save model checkpoints. It has to be one of [None, "best", "better"].
        No model will be saved when it is set as None.
        The "best" strategy will only automatically save the best model after the training finished.
        The "better" strategy will automatically save the model during training whenever the model performs
        better than in previous epochs.

    References
    ----------
    .. [1] `Miao, Xiaoye, Yangyang Wu, Jun Wang, Yunjun Gao, Xudong Mao, and Jianwei Yin. 2021.
       "Generative Semi-Supervised Learning for Multivariate Time Series Imputation".
       Proceedings of the AAAI Conference on Artificial Intelligence 35 (10):8983-91.
       <https://doi.org/10.1609/aaai.v35i10.17086>`_

    """

    def __init__(
        self,
        n_steps: int,
        n_features: int,
        rnn_hidden_size: int,
        lambda_mse: float = 1,
        hint_rate: float = 0.7,
        dropout_rate: float = 0.0,
        G_steps: int = 1,
        D_steps: int = 1,
        batch_size: int = 32,
        epochs: int = 100,
        patience: Optional[int] = None,
        G_optimizer: Optional[Optimizer] = Adam(),
        D_optimizer: Optional[Optimizer] = Adam(),
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
        assert G_steps > 0 and D_steps > 0, "G_steps and D_steps should both >0"

        self.n_steps = n_steps
        self.n_features = n_features
        self.G_steps = G_steps
        self.D_steps = D_steps

        # set up the model
        self.model = _USGAN(
            n_steps,
            n_features,
            rnn_hidden_size,
            lambda_mse,
            hint_rate,
            dropout_rate,
            self.device,
        )
        self._send_model_to_given_device()
        self._print_model_size()

        # set up the optimizer
        self.G_optimizer = G_optimizer
        self.G_optimizer.init_optimizer(self.model.generator.parameters())
        self.D_optimizer = D_optimizer
        self.D_optimizer.init_optimizer(self.model.discriminator.parameters())

    def _assemble_input_for_training(self, data: list) -> dict:
        # fetch data
        (
            indices,
            X,
            missing_mask,
            deltas,
            back_X,
            back_missing_mask,
            back_deltas,
        ) = self._send_data_to_given_device(data)

        # assemble input data
        inputs = {
            "indices": indices,
            "forward": {
                "X": X,
                "missing_mask": missing_mask,
                "deltas": deltas,
            },
            "backward": {
                "X": back_X,
                "missing_mask": back_missing_mask,
                "deltas": back_deltas,
            },
        }

        return inputs

    def _assemble_input_for_validating(self, data: list) -> dict:
        return self._assemble_input_for_training(data)

    def _assemble_input_for_testing(self, data: list) -> dict:
        return self._assemble_input_for_validating(data)

    def _train_model(
        self,
        training_loader: DataLoader,
        val_loader: DataLoader = None,
    ) -> None:
        # each training starts from the very beginning, so reset the loss and model dict here
        self.best_loss = float("inf")
        self.best_model_dict = None

        try:
            training_step = 0
            epoch_train_loss_G_collector = []
            epoch_train_loss_D_collector = []
            for epoch in range(self.epochs):
                self.model.train()
                for idx, data in enumerate(training_loader):
                    training_step += 1
                    inputs = self._assemble_input_for_training(data)

                    step_train_loss_G_collector = []
                    step_train_loss_D_collector = []

                    if idx % self.G_steps == 0:
                        self.G_optimizer.zero_grad()
                        results = self.model.forward(
                            inputs, training_object="generator"
                        )
                        results["generation_loss"].backward()
                        self.G_optimizer.step()
                        step_train_loss_G_collector.append(
                            results["generation_loss"].item()
                        )

                    if idx % self.D_steps == 0:
                        self.D_optimizer.zero_grad()
                        results = self.model.forward(
                            inputs, training_object="discriminator"
                        )
                        results["discrimination_loss"].backward(retain_graph=True)
                        self.D_optimizer.step()
                        step_train_loss_D_collector.append(
                            results["discrimination_loss"].item()
                        )

                    mean_step_train_D_loss = np.mean(step_train_loss_D_collector)
                    mean_step_train_G_loss = np.mean(step_train_loss_G_collector)

                    epoch_train_loss_D_collector.append(mean_step_train_D_loss)
                    epoch_train_loss_G_collector.append(mean_step_train_G_loss)

                    # save training loss logs into the tensorboard file for every step if in need
                    # Note: the `training_step` is not the actual number of steps that Discriminator and Generator get
                    # trained, the actual number should be D_steps*training_step and G_steps*training_step accordingly
                    if self.summary_writer is not None:
                        loss_results = {
                            "generation_loss": mean_step_train_G_loss,
                            "discrimination_loss": mean_step_train_D_loss,
                        }
                        self._save_log_into_tb_file(
                            training_step, "training", loss_results
                        )
                mean_epoch_train_D_loss = np.mean(epoch_train_loss_D_collector)
                mean_epoch_train_G_loss = np.mean(epoch_train_loss_G_collector)
                logger.info(
                    f"epoch {epoch}: "
                    f"training loss_generator {mean_epoch_train_G_loss:.4f}, "
                    f"train loss_discriminator {mean_epoch_train_D_loss:.4f}"
                )
                mean_loss = mean_epoch_train_G_loss

                if mean_loss < self.best_loss:
                    self.best_loss = mean_loss
                    self.best_model_dict = self.model.state_dict()
                    self.patience = self.original_patience
                    # save the model if necessary
                    self._auto_save_model_if_necessary(
                        training_finished=False,
                        saving_name=f"{self.__class__.__name__}_epoch{epoch}_loss{mean_loss}",
                    )
                else:
                    self.patience -= 1
                    if self.patience == 0:
                        logger.info(
                            "Exceeded the training patience. Terminating the training procedure..."
                        )
                        break
        except Exception as e:
            logger.error(f"Exception: {e}")
            if self.best_model_dict is None:
                raise RuntimeError(
                    "Training got interrupted. Model was not trained. Please investigate the error printed above."
                )
            else:
                RuntimeWarning(
                    "Training got interrupted. Please investigate the error printed above.\n"
                    "Model got trained and will load the best checkpoint so far for testing.\n"
                    "If you don't want it, please try fit() again."
                )

        if np.equal(self.best_loss, float("inf")):
            raise ValueError("Something is wrong. best_loss is Nan after training.")

        logger.info("Finished training.")

    def fit(
        self,
        train_set: Union[dict, str],
        val_set: Optional[Union[dict, str]] = None,
        file_type: str = "h5py",
    ) -> None:
        # Step 1: wrap the input data with classes Dataset and DataLoader
        training_set = DatasetForUSGAN(
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
            if isinstance(val_set, str):
                with h5py.File(val_set, "r") as hf:
                    # Here we read the whole validation set from the file to mask a portion for validation.
                    # In PyPOTS, using a file usually because the data is too big. However, the validation set is
                    # generally shouldn't be too large. For example, we have 1 billion samples for model training.
                    # We won't take 20% of them as the validation set because we want as much as possible data for the
                    # training stage to enhance the model's generalization ability. Therefore, 100,000 representative
                    # samples will be enough to validate the model.
                    val_set = {
                        "X": hf["X"][:],
                        "X_intact": hf["X_intact"][:],
                        "indicating_mask": hf["indicating_mask"][:],
                    }
            val_set = DatasetForUSGAN(val_set, return_labels=False, file_type=file_type)
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
        file_type="h5py",
    ) -> dict:
        self.model.eval()  # set the model as eval status to freeze it.
        test_set = DatasetForUSGAN(test_set, return_labels=False, file_type=file_type)
        test_loader = DataLoader(
            test_set,
            batch_size=self.batch_size,
            shuffle=False,
            num_workers=self.num_workers,
        )
        imputation_collector = []

        with torch.no_grad():
            for idx, data in enumerate(test_loader):
                inputs = self._assemble_input_for_testing(data)
                results = self.model.forward(inputs, training=False)
                imputed_data = results["imputed_data"]
                imputation_collector.append(imputed_data)

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
