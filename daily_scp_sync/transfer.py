import os
import shutil
import invoke
import re
import daily_scp_sync


class DailyDirectoryTransferClient:
    def __init__(
        self,
        src_path: str,
        dst_path: str,
        remove_files_after_upload: bool,
        remote_client: daily_scp_sync.remote_client.RemoteClient,
        callbacks: daily_scp_sync.utils.UploadClientCallbacks,
    ) -> None:
        self.src_path = src_path.rstrip("/")
        self.dst_path = dst_path.rstrip("/")
        self.remove_files_after_upload = remove_files_after_upload
        self.remote_client = remote_client
        assert self.remote_client.transfer_process.is_remote_dir(
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
        local_checksum = daily_scp_sync.checksum.get_dir_checksum(
            os.path.join(self.src_path, date_string), file_regex
        )
        local_script_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "checksum.py"
        )
        remote_dir_path = f"{self.dst_path}/{date_string}"
        remote_script_path = f"{remote_dir_path}/checksum.py"
        self.remote_client.transfer_process.put(local_script_path, remote_script_path)

        try:
            self.remote_client.connection.run(
                "python3.10 --version", hide=True, in_stream=False
            )
        except invoke.exceptions.UnexpectedExit:
            raise Exception("python3.10 is not installed on the server")

        try:
            remote_command = (
                f'python3.10 {remote_script_path} "{remote_dir_path}" "{file_regex}"'
            )
            a: invoke.runners.Result = self.remote_client.connection.run(
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

    def run(self) -> None:
        src_date_strings = daily_scp_sync.utils.get_src_date_strings(self.src_path)
        self.callbacks.log_info(
            f"Found {len(src_date_strings)} directorie(s) to upload: {src_date_strings}"
        )
        for date_string in src_date_strings:
            self.__upload_date(date_string)
            if self.callbacks.should_abort_upload():
                self.callbacks.log_info("Aborting upload")
                break


# TODO: class DailyFileTransferClient
