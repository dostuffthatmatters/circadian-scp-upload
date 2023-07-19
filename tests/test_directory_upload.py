import os
import shutil
from typing import Generator
import pytest
import circadian_scp_upload
from . import utils


@pytest.fixture
def provide_test_directory() -> (
    Generator[tuple[str, dict[str, dict[str, str]]], None, None]
):
    tmp_dir_path, dummy_files = utils.provide_test_directory("directories")
    yield tmp_dir_path, dummy_files
    if os.path.exists(tmp_dir_path):
        shutil.rmtree(tmp_dir_path)


def test_directory_upload(
    provide_test_directory: tuple[str, dict[str, dict[str, str]]]
) -> None:
    tmp_dir_path, dummy_files = provide_test_directory

    # TODO: get server credentials from env file
    with circadian_scp_upload.RemoteConnection(
        "1.2.3.4", "someusername", "somepassword"
    ) as remote_connection:
        # TODO: assert that remote dir does not exist

        circadian_scp_upload.DailyTransferClient(
            remote_connection=remote_connection,
            src_path=tmp_dir_path,
            dst_path=tmp_dir_path,
            remove_files_after_upload=True,
            variant="directories",
        ).run()

    # TODO: download remote directory

    # TODO: check equality locally

    # TODO: assert that local lock file does not exists
    # TODO: assert that remote lock file does not exist
