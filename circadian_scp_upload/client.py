from __future__ import annotations
from typing import Any, Literal
import fabric.connection
import fabric.transfer
import os
import shutil
import invoke
import re
import circadian_scp_upload

# TODO: make directory upload interruptable at 10 % steps


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
        self.connection.close()


class DailyTransferClient:
    def __init__(
        self,
        remote_connection: RemoteConnection,
        src_path: str,
        dst_path: str,
        remove_files_after_upload: bool,
        variant: Literal["directories", "files"],
        callbacks: circadian_scp_upload.UploadClientCallbacks = circadian_scp_upload.UploadClientCallbacks(),
    ) -> None:
        self.src_path = src_path.rstrip("/")
        self.dst_path = dst_path.rstrip("/")
        self.remove_files_after_upload = remove_files_after_upload
        self.remote_connection = remote_connection
        assert self.remote_connection.transfer_process.is_remote_dir(
            self.dst_path
        ), f"remote {self.dst_path} is not a directory"
        self.variant = variant
        self.callbacks = callbacks

    def __directory_checksums_match(self, date_string: str) -> bool:
        """Use `hashlib` to generate a checksum for the local and the
        remote directory. The remote checksum will be calculated by
        copying a script to the remote server and executing it there.

        This script requires the server to have Python 3.10 installed
        and will raise an exception if its not present."""

        file_regex = self.callbacks.date_string_to_file_regex(date_string)
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

    def __upload_date_directory(
        self, date_string: str
    ) -> Literal["successful", "failed", "aborted"]:
        """Perform the whole upload process for a given directory.

        1. If the respective remote directory doesn't exist, create it
        2. Determine which files have not been uploaded yet
        4. Upload every file that is found locally but has not been uploaded yet
        5. Test whether the checksums of "files on server" and "local ifgs"
           are equal, raise an exception (and end the function) if they differ
        6. Remove the remote meta file
        7. Optionally remove local ifgs"""

        src_dir_path = os.path.join(self.src_path, date_string)
        dst_dir_path = f"{self.dst_path}/{date_string}"
        meta = circadian_scp_upload.utils.UploadMeta.init(src_dir_path=src_dir_path)

        # determine files present in src and dst directory
        # files should be named like "<anything>YYYYMMDD<anything>"
        file_regex = self.callbacks.date_string_to_file_regex(date_string)
        raw_src_files = os.listdir(os.path.join(self.src_path, date_string))
        files_found_in_src = set([f for f in raw_src_files if re.match(file_regex, f)])

        # determine file differences between src and dst
        files_missing_in_dst = files_found_in_src.difference(set(meta.uploaded_files))
        self.callbacks.log_info(
            f"{date_string}: {len(files_missing_in_dst)} files missing in dst"
        )

        if len(files_missing_in_dst) > 0:
            self.remote_connection.connection.run(f"mkdir -p {dst_dir_path}")

        with circadian_scp_upload.utils.TwinFileLock(
            src_dir_path, dst_dir_path, self.remote_connection.connection
        ):
            if not self.remote_connection.transfer_process.is_remote_dir(dst_dir_path):
                raise NotADirectoryError(
                    f"{date_string}: remote directory {dst_dir_path} does not exist"
                )

            progress: float = len(meta.uploaded_files) / len(files_found_in_src)

            # upload every file that is missing in the remote
            # meta but present in the local directory
            for f in sorted(files_missing_in_dst):
                self.remote_connection.transfer_process.put(
                    os.path.join(src_dir_path, f),
                    f"{self.dst_path}/{date_string}/{f}",
                )
                meta.uploaded_files.append(f)
                meta.dump()
                new_progress = len(meta.uploaded_files) / len(files_found_in_src)
                if int(new_progress * 10) != int(progress * 10):
                    self.callbacks.log_info(
                        f"{date_string}: {progress * 100:.2f}% "
                        + f"({len(meta.uploaded_files)}/{len(files_found_in_src)})"
                        + f" uploaded"
                    )
                progress = new_progress

            # raise an exception if the checksums do not match
            if not self.__directory_checksums_match(date_string):
                self.callbacks.log_error(f"{date_string}: checksums do not match")
                return "failed"

            self.callbacks.log_info(f"{date_string}: finished uploading")

        # only remove src if configured and checksums match
        if self.remove_files_after_upload:
            shutil.rmtree(src_dir_path)
            self.callbacks.log_info(f"{date_string}: finished removing source")
        else:
            self.callbacks.log_info(f"{date_string}: skipped removal of source")

        return "successful"

    def __upload_date_files(self, date_string: str) -> Literal["successful", "failed"]:
        meta = circadian_scp_upload.utils.UploadMeta.init(src_dir_path=self.src_path)

        # determine file differences between src and dst
        file_regex = self.callbacks.date_string_to_file_regex(date_string)
        files_missing_in_dst = set(
            [f for f in os.listdir(self.src_path) if re.match(file_regex, f)]
        ).difference(set(meta.uploaded_files))
        self.callbacks.log_info(
            f"{date_string}: {len(files_missing_in_dst)} files missing in dst"
        )

        with circadian_scp_upload.utils.TwinFileLock(
            self.src_path, self.dst_path, self.remote_connection.connection
        ):
            # upload every file that is missing in the remote
            # meta but present in the local directory
            for f in sorted(files_missing_in_dst):
                self.remote_connection.transfer_process.put(
                    os.path.join(self.src_path, f),
                    f"{self.dst_path}/{f}",
                )
                if self.remove_files_after_upload:
                    os.remove(os.path.join(self.src_path, f))
                meta.uploaded_files.append(f)
                meta.dump()

        return "successful"

    def run(self) -> None:
        src_date_strings = circadian_scp_upload.utils.get_src_date_strings(
            self.src_path, variant=self.variant
        )
        self.callbacks.log_info(
            f"Found {len(src_date_strings)} date(s) to be uploaded: {src_date_strings}"
        )
        for date_string in src_date_strings:
            self.callbacks.log_info(f"{date_string}: starting")

            if self.variant == "directories":
                self.callbacks.log_info(
                    f"{date_string}: {self.__upload_date_directory(date_string)}"
                )
            elif self.variant == "files":
                self.callbacks.log_info(
                    f"{date_string}: {self.__upload_date_files(date_string)}"
                )

            if self.callbacks.should_abort_upload():
                self.callbacks.log_info("Aborting upload")
                break
