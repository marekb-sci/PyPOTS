"""
Dataset class for model BRITS.
"""

# Created by Wenjie Du <wenjay.du@gmail.com>
# License: BSD-3-Clause

from typing import Union, Iterable

import torch

from ...data.base import BaseDataset
from ...data.utils import _parse_delta_torch


class DatasetForBRITS(BaseDataset):
    """Dataset class for BRITS.

    Parameters
    ----------
    data : dict or str,
        The dataset for model input, should be a dictionary including keys as 'X' and 'y',
        or a path string locating a data file.
        If it is a dict, X should be array-like of shape [n_samples, sequence length (time steps), n_features],
        which is time-series data for input, can contain missing values, and y should be array-like of shape
        [n_samples], which is classification labels of X.
        If it is a path string, the path should point to a data file, e.g. a h5 file, which contains
        key-value pairs like a dict, and it has to include keys as 'X' and 'y'.

    return_labels : bool, default = True,
        Whether to return labels in function __getitem__() if they exist in the given data. If `True`, for example,
        during training of classification models, the Dataset class will return labels in __getitem__() for model input.
        Otherwise, labels won't be included in the data returned by __getitem__(). This parameter exists because we
        need the defined Dataset class for all training/validating/testing stages. For those big datasets stored in h5
        files, they already have both X and y saved. But we don't read labels from the file for validating and testing
        with function _fetch_data_from_file(), which works for all three stages. Therefore, we need this parameter for
        distinction.

    file_type : str, default = "h5py"
        The type of the given file if train_set and val_set are path strings.
    """

    def __init__(
        self,
        data: Union[dict, str],
        return_labels: bool = True,
        file_type: str = "h5py",
    ):
        super().__init__(data, return_labels, file_type)

        if not isinstance(self.data, str):
            # calculate all delta here.
            forward_missing_mask = (~torch.isnan(self.X)).type(torch.float32)
            forward_X = torch.nan_to_num(self.X)
            forward_delta = _parse_delta_torch(forward_missing_mask)
            backward_X = torch.flip(forward_X, dims=[1])
            backward_missing_mask = torch.flip(forward_missing_mask, dims=[1])
            backward_delta = _parse_delta_torch(backward_missing_mask)

            self.processed_data = {
                "forward": {
                    "X": forward_X.to(torch.float32),
                    "missing_mask": forward_missing_mask.to(torch.float32),
                    "delta": forward_delta.to(torch.float32),
                },
                "backward": {
                    "X": backward_X.to(torch.float32),
                    "missing_mask": backward_missing_mask.to(torch.float32),
                    "delta": backward_delta.to(torch.float32),
                },
            }

    def _fetch_data_from_array(self, idx: int) -> Iterable:
        """Fetch data from self.X if it is given.

        Parameters
        ----------
        idx : int,
            The index of the sample to be return.

        Returns
        -------
        sample : list,
            A list contains

            index : int tensor,
                The index of the sample.

            X : tensor,
                The feature vector for model input.

            missing_mask : tensor,
                The mask indicates all missing values in X.

            delta : tensor,
                The delta matrix contains time gaps of missing values.

            label (optional) : tensor,
                The target label of the time-series sample.
        """
        sample = [
            torch.tensor(idx),
            # for forward
            self.processed_data["forward"]["X"][idx],
            self.processed_data["forward"]["missing_mask"][idx],
            self.processed_data["forward"]["delta"][idx],
            # for backward
            self.processed_data["backward"]["X"][idx],
            self.processed_data["backward"]["missing_mask"][idx],
            self.processed_data["backward"]["delta"][idx],
        ]

        if self.y is not None and self.return_labels:
            sample.append(self.y[idx].to(torch.long))

        return sample

    def _fetch_data_from_file(self, idx: int) -> Iterable:
        """Fetch data with the lazy-loading strategy, i.e. only loading data from the file while requesting for samples.
        Here the opened file handle doesn't load the entire dataset into RAM but only load the currently accessed slice.

        Parameters
        ----------
        idx : int,
            The index of the sample to be return.

        Returns
        -------
        sample : list,
            The collated data sample, a list including all necessary sample info.
        """

        if self.file_handle is None:
            self.file_handle = self._open_file_handle()

        X = torch.from_numpy(self.file_handle["X"][idx]).to(torch.float32)
        missing_mask = (~torch.isnan(X)).to(torch.float32)
        X = torch.nan_to_num(X)

        forward = {
            "X": X,
            "missing_mask": missing_mask,
            "deltas": _parse_delta_torch(missing_mask),
        }

        backward = {
            "X": torch.flip(forward["X"], dims=[0]),
            "missing_mask": torch.flip(forward["missing_mask"], dims=[0]),
        }
        backward["deltas"] = _parse_delta_torch(backward["missing_mask"])

        sample = [
            torch.tensor(idx),
            # for forward
            forward["X"],
            forward["missing_mask"],
            forward["deltas"],
            # for backward
            backward["X"],
            backward["missing_mask"],
            backward["deltas"],
        ]

        # if the dataset has labels and is for training, then fetch it from the file
        if "y" in self.file_handle.keys() and self.return_labels:
            sample.append(torch.tensor(self.file_handle["y"][idx], dtype=torch.long))

        return sample
