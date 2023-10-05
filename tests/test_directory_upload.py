import datetime
import json
import os
from typing import Generator
import pytest
import sys
import circadian_scp_upload
from . import utils


@pytest.fixture
def _provide_test_directory() -> (
    Generator[tuple[str, dict[str, dict[datetime.date, dict[str, str]]]], None,
              None]
):
    tmp_dir_path, dummy_files = utils.provide_test_directory("directories")
    yield tmp_dir_path, dummy_files
    # os.system(
    #     f"rm -rf /tmp/circadian_scp_upload_test_*_{sys.version.split(' ')[0]}/"
    # )


def _check_directory_state(
    path: str,
    dummy_files: dict[datetime.date, dict[str, str]],
    past_dates_should_exist: bool,
    future_dates_should_exist: bool,
) -> None:
    assert os.path.isdir(path)
    dated_regex = path.split("/")[-1]

    latest_date_to_consider = datetime.date.today() - datetime.timedelta(days=1)
    if datetime.datetime.now().hour == 0:
        latest_date_to_consider -= datetime.timedelta(days=1)

    wrongly_existing_directories: list[str] = []
    wrongly_existing_files: list[str] = []
    wrongly_missing_directories: list[str] = []
    wrongly_missing_files: list[str] = []

    for date in sorted(dummy_files.keys()):
        if date <= latest_date_to_consider:
            directory_should_exist = past_dates_should_exist
        else:
            directory_should_exist = future_dates_should_exist

        date_dir_path = os.path.join(path, date.strftime(dated_regex))
        if directory_should_exist:
            if not os.path.isdir(date_dir_path):
                wrongly_missing_directories.append(date_dir_path)

            if os.path.isfile(os.path.join(date_dir_path, ".do-not-touch")):
                wrongly_existing_files.append(
                    os.path.join(date_dir_path, ".do-not-touch")
                )
            for file_name, file_contents in dummy_files[date].items():
                if not os.path.isfile(os.path.join(date_dir_path, file_name)):
                    wrongly_missing_files.append(
                        os.path.join(date_dir_path, file_name)
                    )
                else:
                    with open(os.path.join(date_dir_path, file_name), "r") as f:
                        assert f.read() == file_contents
        else:
            if os.path.isdir(date_dir_path):
                wrongly_existing_directories.append(date_dir_path)

    for check_list, check_message in [
        (
            wrongly_existing_directories,
            "The following directories should not exist"
        ),
        (wrongly_existing_files, "The following files should not exist"),
        (wrongly_missing_directories, "The following directories should exist"),
        (wrongly_missing_files, "The following files should exist"),
    ]:
        assert len(check_list) == 0, (
            check_message + ": [\n" + ",\n".join(check_list) + "\n]"
        )


@pytest.mark.order(3)
def test_directory_upload(
    _provide_test_directory: tuple[str, dict[str, dict[datetime.date,
                                                       dict[str, str]]]]
) -> None:
    current_time = datetime.datetime.now()
    if current_time.hour == 0 and current_time.minute > 58:
        raise RuntimeError(
            "Test cannot be started between 00:58 and 01:00, because it might "
            +
            "interfere with which directories are considered during the upload"
        )

    tmp_dir_path, dummy_files = _provide_test_directory

    for dated_regex in dummy_files.keys():
        root_dir_for_this_regex = os.path.join(tmp_dir_path, dated_regex[:-2])
        dummy_files_for_this_regex = dummy_files[dated_regex]
        print("root_dir_for_this_regex =", root_dir_for_this_regex)
        print(
            "dummy_files_for_this_regex =",
            json.dumps({
                str(k): v
                for k, v in dummy_files_for_this_regex.items()
            },
                       indent=4)
        )

        # check integrity of local directory
        _check_directory_state(
            root_dir_for_this_regex,
            dummy_files_for_this_regex,
            past_dates_should_exist=True,
            future_dates_should_exist=True,
        )

        with circadian_scp_upload.RemoteConnection(
            *utils.load_credentials()
        ) as remote_connection:
            assert not remote_connection.transfer_process.is_remote_dir(
                root_dir_for_this_regex
            )
            remote_connection.connection.run(
                f"mkdir -p {root_dir_for_this_regex}"
            )
            assert remote_connection.transfer_process.is_remote_dir(
                root_dir_for_this_regex
            )

            # perform upload
            circadian_scp_upload.DailyTransferClient(
                remote_connection=remote_connection,
                src_path=root_dir_for_this_regex,
                dst_path=root_dir_for_this_regex,
                remove_files_after_upload=True,
                variant="directories",
                callbacks=circadian_scp_upload.UploadClientCallbacks(
                    dated_regex=f"^{dated_regex}.*$"
                )
            ).run()

            # check integrity of local directory
            _check_directory_state(
                root_dir_for_this_regex,
                dummy_files_for_this_regex,
                past_dates_should_exist=False,
                future_dates_should_exist=True,
            )

            # move old local directory and download remote directory
            os.rename(
                root_dir_for_this_regex, root_dir_for_this_regex + "-old-local"
            )
            tmp_dir_name = root_dir_for_this_regex.split("/")[-1]
            remote_connection.connection.run(
                f'cd "{tmp_dir_path}" && tar -cf "{tmp_dir_name}.tar" "{tmp_dir_name}"'
            )
            remote_connection.transfer_process.get(
                root_dir_for_this_regex + ".tar",
                root_dir_for_this_regex + ".tar"
            )
            remote_connection.connection.run(
                f'rm -rf "/tmp/circadian_scp_upload_test_*_{sys.version.split()[0]}/"'
            )
            os.system(f'cd "{tmp_dir_path}" && tar -xf "{tmp_dir_name}.tar"')

            # check integrity of remote directory (downloaded to local)
            _check_directory_state(
                root_dir_for_this_regex,
                dummy_files_for_this_regex,
                past_dates_should_exist=True,
                future_dates_should_exist=False,
            )
