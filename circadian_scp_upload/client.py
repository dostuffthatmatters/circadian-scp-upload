from __future__ import annotations
from typing import Any
import fabric.connection
import fabric.transfer
import os
import shutil
import invoke
import re
import circadian_scp_upload


class RemoteConnection:
    def __init__(self, host: str, username: str, password: str) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.connection = fabric.connection.Connection(
            f"{self.username}@{self.host}",
            connect_kwargs={"password": self.password},
            connect_timeout=5,
        )
        self.transfer_process = fabric.transfer.Transfer(self.connection)

    def __enter__(self) -> RemoteConnection:
        self.connection.open()
        assert self.connection.is_connected, "could not open the ssh connection"
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        # TODO: raise the exception correctly
        self.connection.close()


class DailyDirectoryTransferClient:
    def __init__(
        self,
        remote_connection: RemoteConnection,
        src_path: str,
        dst_path: str,
        remove_files_after_upload: bool,
        callbacks: circadian_scp_upload.UploadClientCallbacks,
    ) -> None:
        self.src_path = src_path.rstrip("/")
        self.dst_path = dst_path.rstrip("/")
        self.remove_files_after_upload = remove_files_after_upload
        self.remote_connection = remote_connection
        assert self.remote_connection.transfer_process.is_remote_dir(
            self.dst_path
        ), f"remote {self.dst_path} is not a directory"
        self.callbacks = callbacks

    def __directory_checksums_match(self, date_string: str) -> bool:
        """Use `hashlib` to generate a checksum for the local and the
        remote directory. The remote checksum will be calculated by
        copying a script to the remote server and executing it there.

        This script requires the server to have Python 3.10 installed
        and will raise an exception if its not present."""

        file_regex = self.callbacks.date_string_to_dir_file_regex(date_string)
        local_checksum = circadian_scp_upload.checksum.get_dir_checksum(
            os.path.join(self.src_path, date_string), file_regex
        )
        local_script_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "checksum.py"
        )
        remote_dir_path = f"{self.dst_path}/{date_string}"
        remote_script_path = f"{remote_dir_path}/checksum.py"
        self.remote_connection.transfer_process.put(
            local_script_path, remote_script_path
        )

        try:
            self.remote_connection.connection.run(
                "python3.10 --version", hide=True, in_stream=False
            )
        except invoke.exceptions.UnexpectedExit:
            raise Exception("python3.10 is not installed on the server")

        try:
            remote_command = (
                f'python3.10 {remote_script_path} "{remote_dir_path}" "{file_regex}"'
            )
            a: invoke.runners.Result = self.remote_connection.connection.run(
                f'python3.10 {remote_script_path} "{remote_dir_path}" "{file_regex}"',
                hide=True,
                in_stream=False,
            )
            assert a.exited == 0
            remote_checksum = a.stdout.strip()
            assert isinstance(remote_checksum, str)
        except (invoke.exceptions.UnexpectedExit, AssertionError) as e:
            raise Exception(
                f"could not execute remote command on server ({remote_command}): {e}"
            )

        return local_checksum == remote_checksum

    def __upload_date(self, date_string: str) -> None:
        pass
        """Perform the whole upload process for a given directory.

        1. If the respective remote directory doesn't exist, create it
        2. Determine which files have not been uploaded yet
        4. Upload every file that is found locally but has not been uploaded yet
        5. Test whether the checksums of "files on server" and "local ifgs"
           are equal, raise an exception (and end the function) if they differ
        6. Remove the remote meta file
        7. Optionally remove local ifgs"""

        meta = circadian_scp_upload.utils.UploadMeta.init(
            src_dir_path=f"{self.src_path}/{date_string}"
        )
        src_dir_path = os.path.join(self.src_path, date_string)
        src_do_not_touch_path = os.path.join(src_dir_path, ".do-not-touch")
        dst_dir_path = f"{self.dst_path}/{date_string}"
        dst_do_not_touch_path = f"{dst_dir_path}/.do-not-touch"

        # determine files present in src and dst directory
        # files should be named like "<anything>YYYYMMDD<anything>"
        file_regex = self.callbacks.date_string_to_dir_file_regex(date_string)
        raw_src_files = os.listdir(os.path.join(self.src_path, date_string))
        files_found_in_src = set([f for f in raw_src_files if re.match(file_regex, f)])

        # determine file differences between src and dst
        files_missing_in_dst = files_found_in_src.difference(set(meta.uploaded_files))

        if len(files_missing_in_dst) > 0:
            self.callbacks.log_info(
                f"{date_string}: {len(files_missing_in_dst)} files missing in dst"
            )
            self.remote_connection.connection.run(f"mkdir -p {dst_dir_path}")
            self.remote_connection.connection.run(dst_do_not_touch_path)
            os.system(f"touch {src_do_not_touch_path}")

            if not self.remote_connection.transfer_process.is_remote_dir(dst_dir_path):
                raise NotADirectoryError(
                    f"{date_string}: remote directory {dst_dir_path} does not exist"
                )

            # upload every file that is missing in the remote
            # meta but present in the local directory
            for i, f in enumerate(sorted(files_missing_in_dst)):
                r = self.remote_connection.transfer_process.put(
                    os.path.join(src_dir_path, f),
                    f"{self.dst_path}/{date_string}/{f}",
                )
                meta.uploaded_files.append(f)
                meta.dump()

        # raise an exception if the checksums do not match
        if not self.__directory_checksums_match(date_string):
            self.callbacks.log_error(f"{date_string}: checksums do not match")
            return

        # only remove '.do-not-touch' file when the checksums match
        os.system(f"rm -f {src_do_not_touch_path}")
        self.remote_connection.connection.run(f"rm -f {dst_do_not_touch_path}")
        self.callbacks.log_info(f"{date_string}: Successfully uploaded")

        # only remove src if configured and checksums match
        if self.remove_files_after_upload:
            shutil.rmtree(src_dir_path)
            self.callbacks.log_info(f"{date_string}: Successfully removed source")
        else:
            self.callbacks.log_info(f"{date_string}: Skipping removal of source")

    def run(self) -> None:
        src_date_strings = circadian_scp_upload.utils.get_src_date_strings(
            self.src_path
        )
        self.callbacks.log_info(
            f"Found {len(src_date_strings)} directorie(s) to upload: {src_date_strings}"
        )
        for date_string in src_date_strings:
            self.__upload_date(date_string)
            if self.callbacks.should_abort_upload():
                self.callbacks.log_info("Aborting upload")
                break


class DailyFileTransferClient:
    def __init__(
        self,
        remote_connection: RemoteConnection,
        src_path: str,
        dst_path: str,
        remove_files_after_upload: bool,
        callbacks: circadian_scp_upload.UploadClientCallbacks,
    ) -> None:
        pass

    def run(self) -> None:
        pass
