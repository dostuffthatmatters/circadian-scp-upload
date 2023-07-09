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
