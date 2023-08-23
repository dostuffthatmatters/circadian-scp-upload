import os
import shutil
from typing import Generator, Literal
import pytest
import circadian_scp_upload
from . import utils


"""
NEXT STEPS:

* future dates will still be present locally
* future dates will not be present remotely
* check whether all lock files have been removed

"""


@pytest.fixture
def provide_test_directory() -> (
    Generator[tuple[str, dict[str, dict[str, str]]], None, None]
):
    tmp_dir_path, dummy_files = utils.provide_test_directory("directories")
    yield tmp_dir_path, dummy_files
    if os.path.exists(tmp_dir_path):
        # shutil.rmtree(tmp_dir_path)
        pass


def _check_directory_state(
    path: str,
    dummy_files: dict[str, dict[str, str]],
    state: Literal["empty", "complete"],
) -> None:
    assert os.path.isdir(path)
    for date_string in dummy_files.keys():
        if state == "empty":
            assert not os.path.exists(os.path.join(path, date_string))
        else:
            assert os.path.isdir(os.path.join(path, date_string))
            for file_name, file_contents in dummy_files[date_string].items():
                assert os.path.isfile(os.path.join(path, date_string, file_name))
                with open(os.path.join(path, date_string, file_name), "r") as f:
                    assert f.read() == file_contents


def test_directory_upload(
    provide_test_directory: tuple[str, dict[str, dict[str, str]]]
) -> None:
    tmp_dir_path, dummy_files = provide_test_directory

    print("tmp_dir_path =", tmp_dir_path)
    print("dummy_files =", dummy_files)

    _check_directory_state(tmp_dir_path, dummy_files, "complete")

    with circadian_scp_upload.RemoteConnection(
        *utils.load_credentials()
    ) as remote_connection:
        assert not remote_connection.transfer_process.is_remote_dir(tmp_dir_path)
        remote_connection.connection.run(f"mkdir -p {tmp_dir_path}")
        assert remote_connection.transfer_process.is_remote_dir(tmp_dir_path)

        circadian_scp_upload.DailyTransferClient(
            remote_connection=remote_connection,
            src_path=tmp_dir_path,
            dst_path=tmp_dir_path,
            remove_files_after_upload=True,
            variant="directories",
        ).run()

        _check_directory_state(tmp_dir_path, dummy_files, "empty")

        os.rmdir(tmp_dir_path)

        # download remote directory and check completeness
        remote_connection.transfer_process.get(tmp_dir_path, tmp_dir_path)
        _check_directory_state(tmp_dir_path, dummy_files, "complete")

        # TODO: assert that remote lock file does not exist

        remote_connection.connection.run(f"rm -rf {tmp_dir_path}")
