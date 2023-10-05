import datetime
import json
import os
import sys
from typing import Generator
import pytest
import circadian_scp_upload
from . import utils


@pytest.fixture
def _provide_test_directory(
) -> (Generator[tuple[str, dict[str, dict[str, str]]], None, None]):
    tmp_dir_path, dummy_files = utils.provide_test_directory("files")
    yield tmp_dir_path, dummy_files
    os.system(
        f"rm -rf /tmp/circadian_scp_upload_test_*_{sys.version.split(' ')[0]}/"
    )


def _check_directory_state(
    path: str,
    dummy_files: dict[str, dict[str, str]],
    past_dates_should_exist: bool,
    future_dates_should_exist: bool,
) -> None:
    assert os.path.isdir(path)

    latest_datetime_to_consider = datetime.datetime.now() - datetime.timedelta(
        days=1
    )
    if latest_datetime_to_consider.hour == 0:
        latest_datetime_to_consider -= datetime.timedelta(days=1)
    latest_date_string_to_consider = latest_datetime_to_consider.date(
    ).strftime("%Y%m%d")

    wrongly_existing_files: list[str] = []
    wrongly_missing_files: list[str] = []

    if os.path.isfile(os.path.join(path, ".do-not-touch")):
        wrongly_existing_files.append(os.path.join(path, ".do-not-touch"))

    for date_string in sorted(dummy_files.keys()):
        files_should_exist = (
            past_dates_should_exist if
            (date_string
             <= latest_date_string_to_consider) else future_dates_should_exist
        )

        if files_should_exist:
            for file_name, file_contents in dummy_files[date_string].items():
                if not os.path.isfile(os.path.join(path, file_name)):
                    wrongly_missing_files.append(os.path.join(path, file_name))
                else:
                    with open(os.path.join(path, file_name), "r") as f:
                        assert f.read() == file_contents
        else:
            for file_name, file_contents in dummy_files[date_string].items():
                if os.path.isfile(os.path.join(path, file_name)):
                    wrongly_existing_files.append(os.path.join(path, file_name))

    for check_list, check_message in [
        (wrongly_existing_files, "The following files should not exist"),
        (wrongly_missing_files, "The following files should exist"),
    ]:
        assert len(check_list) == 0, (
            check_message + ": [\n" + ",\n".join(check_list) + "\n]"
        )


@pytest.mark.order(4)
def test_file_upload(
    _provide_test_directory: tuple[str, dict[str, dict[str, str]]]
) -> None:
    current_time = datetime.datetime.now()
    if current_time.hour == 0 and current_time.minute > 58:
        raise RuntimeError(
            "Test cannot be started between 00:58 and 01:00, because it might "
            +
            "interfere with which directories are considered during the upload"
        )

    tmp_dir_path, dummy_files = _provide_test_directory

    print("tmp_dir_path =", tmp_dir_path)
    print("dummy_files =", json.dumps(dummy_files, indent=4))

    # check integrity of local directory
    _check_directory_state(
        tmp_dir_path,
        dummy_files,
        past_dates_should_exist=True,
        future_dates_should_exist=True,
    )

    with circadian_scp_upload.RemoteConnection(
        *utils.load_credentials()
    ) as remote_connection:
        assert not remote_connection.transfer_process.is_remote_dir(
            tmp_dir_path
        )
        remote_connection.connection.run(f"mkdir -p {tmp_dir_path}")
        assert remote_connection.transfer_process.is_remote_dir(tmp_dir_path)

        # perform upload
        circadian_scp_upload.DailyTransferClient(
            remote_connection=remote_connection,
            src_path=tmp_dir_path,
            dst_path=tmp_dir_path,
            remove_files_after_upload=True,
            variant="files",
        ).run()

        # check integrity of local directory
        _check_directory_state(
            tmp_dir_path,
            dummy_files,
            past_dates_should_exist=False,
            future_dates_should_exist=True,
        )

        # move old local directory and download remote directory
        os.rename(tmp_dir_path, tmp_dir_path + "-old-local")
        tmp_dir_name = tmp_dir_path.split("/")[-1]
        remote_connection.connection.run(
            f"cd /tmp && tar -cf {tmp_dir_name}.tar {tmp_dir_name}"
        )
        remote_connection.transfer_process.get(
            tmp_dir_path + ".tar", tmp_dir_path + ".tar"
        )
        remote_connection.connection.run(
            f"rm -rf /tmp/circadian_scp_upload_test_*_{sys.version.split(' ')[0]}/"
        )
        os.system(f"cd /tmp && tar -xf {tmp_dir_name}.tar")

        # check integrity of remote directory (downloaded to local)
        _check_directory_state(
            tmp_dir_path,
            dummy_files,
            past_dates_should_exist=True,
            future_dates_should_exist=False,
        )
