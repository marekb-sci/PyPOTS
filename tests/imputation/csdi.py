"""
Test cases for CSDI imputation model.
"""

# Created by Wenjie Du <wenjay.du@gmail.com>
# License: BSD-3-Clause


import os.path
import unittest

import numpy as np
import pytest

from pypots.imputation import CSDI
from pypots.optim import Adam
from pypots.utils.logging import logger
from pypots.utils.metrics import cal_mae
from tests.global_test_config import (
    DATA,
    DEVICE,
    check_tb_and_model_checkpoints_existence,
)
from tests.imputation.config import (
    TRAIN_SET,
    VAL_SET,
    TEST_SET,
    RESULT_SAVING_DIR_FOR_IMPUTATION,
    EPOCHS,
)


class TestCSDI(unittest.TestCase):
    logger.info("Running tests for an imputation model CSDI...")

    # set the log and model saving path
    saving_path = os.path.join(RESULT_SAVING_DIR_FOR_IMPUTATION, "CSDI")
    model_save_name = "saved_csdi_model.pypots"

    # initialize an Adam optimizer
    optimizer = Adam(lr=0.001, weight_decay=1e-5)

    # initialize a CSDI model
    csdi = CSDI(
        n_features=DATA["n_features"],
        n_layers=1,
        n_channels=8,
        d_time_embedding=32,
        d_feature_embedding=3,
        d_diffusion_embedding=32,
        n_heads=1,
        epochs=EPOCHS,
        saving_path=saving_path,
        optimizer=optimizer,
        device=DEVICE,
    )

    @pytest.mark.xdist_group(name="imputation-csdi")
    def test_0_fit(self):
        self.csdi.fit(TRAIN_SET, VAL_SET)

    @pytest.mark.xdist_group(name="imputation-csdi")
    def test_1_impute(self):
        imputed_X = self.csdi.predict(TEST_SET)["imputation"]
        assert not np.isnan(
            imputed_X
        ).any(), "Output still has missing values after running impute()."
        test_MAE = cal_mae(
            imputed_X, DATA["test_X_intact"], DATA["test_X_indicating_mask"]
        )
        logger.info(f"CSDI test_MAE: {test_MAE}")

    @pytest.mark.xdist_group(name="imputation-csdi")
    def test_2_parameters(self):
        assert hasattr(self.csdi, "model") and self.csdi.model is not None

        assert hasattr(self.csdi, "optimizer") and self.csdi.optimizer is not None

        assert hasattr(self.csdi, "best_loss")
        self.assertNotEqual(self.csdi.best_loss, float("inf"))

        assert (
            hasattr(self.csdi, "best_model_dict")
            and self.csdi.best_model_dict is not None
        )

    @pytest.mark.xdist_group(name="imputation-csdi")
    def test_3_saving_path(self):
        # whether the root saving dir exists, which should be created by save_log_into_tb_file
        assert os.path.exists(
            self.saving_path
        ), f"file {self.saving_path} does not exist"

        # check if the tensorboard file and model checkpoints exist
        check_tb_and_model_checkpoints_existence(self.csdi)

        # save the trained model into file, and check if the path exists
        self.csdi.save_model(
            saving_dir=self.saving_path, file_name=self.model_save_name
        )

        # test loading the saved model, not necessary, but need to test
        saved_model_path = os.path.join(self.saving_path, self.model_save_name)
        self.csdi.load_model(saved_model_path)


if __name__ == "__main__":
    unittest.main()
