from __future__ import annotations
from typing import Any, Callable, Literal
import datetime
import glob
import math
import fabric.connection
import fabric.transfer
import os
import shutil
import filelock
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
        self.connection.close()


class DailyTransferClient:
    def __init__(
        self,
        remote_connection: RemoteConnection,
        src_path: str,
        dst_path: str,
        remove_files_after_upload: bool,
        variant: Literal["directories", "files"],
        callbacks: circadian_scp_upload.
        UploadClientCallbacks = circadian_scp_upload.UploadClientCallbacks(),
    ) -> None:
        self.src_path = src_path.rstrip("/")
        self.dst_path = dst_path.rstrip("/")
        self.remove_files_after_upload = remove_files_after_upload
        self.remote_connection = remote_connection
        assert self.remote_connection.transfer_process.is_remote_dir(
            self.dst_path
        ), f'remote "{self.dst_path}" is not a directory'
        self.variant = variant
        self.callbacks = callbacks

    def __directory_checksums_match(self, dir_name: str) -> bool:
        """Use `hashlib` to generate a checksum for the local and the
        remote directory. The remote checksum will be calculated by
        copying a script to the remote server and executing it there.

        This script requires the server to have Python 3.10 installed
        and will raise an exception if its not present."""

        file_regex = "^.*$"
        local_checksum = circadian_scp_upload.checksum.get_dir_checksum(
            os.path.join(self.src_path, dir_name), file_regex
        )
        local_script_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "checksum.py"
        )
        remote_dir_path = f"{self.dst_path}/{dir_name}"
        remote_script_path = f"{self.dst_path}/checksum.py"
        self.callbacks.log_info(
            f'Copying checksum script to remote server at path "{remote_script_path}"'
        )
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
            remote_command = f'python3.10 {remote_script_path} --file_regex "{file_regex}" "{remote_dir_path}"'
            a: invoke.runners.Result = self.remote_connection.connection.run(
                remote_command, hide=True, in_stream=False
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
        self, date: datetime.date, dir_name: str
    ) -> Literal["successful", "failed", "aborted", "no files found"]:
        """Perform the whole upload process for a given directory.

        1. If the respective remote directory doesn't exist, create it
        2. Determine which files have not been uploaded yet
        4. Upload every file that is found locally but has not been uploaded yet
        5. Test whether the checksums of "files on server" and "local ifgs"
           are equal, raise an exception (and end the function) if they differ
        6. Remove the remote meta file
        7. Optionally remove local ifgs"""

        log_info: Callable[
            [str],
            None] = lambda msg: self.callbacks.log_info(f"{date}: {msg}")
        log_error: Callable[
            [str],
            None] = lambda msg: self.callbacks.log_error(f"{date}: {msg}")

        src_dir_path = os.path.join(self.src_path, dir_name)
        dst_dir_path = f"{self.dst_path}/{dir_name}"
        log_info(
            f"starting to upload directory local directory '{src_dir_path}'" +
            f" to remote directory '{dst_dir_path}'"
        )

        meta = circadian_scp_upload.utils.UploadMeta.init(
            src_dir_path=src_dir_path
        )

        # determine files present in src and dst directory
        # files should be named like "<anything>YYYYMMDD<anything>"
        src_files = set([
            f for f in os.listdir(src_dir_path)
            if f not in ["upload-meta.json", ".do-not-touch"]
        ])
        log_info(f"found {len(src_files)} files in src directory")

        # quit if no src files are found
        if len(src_files) == 0:
            log_info("directory is empty")
            if self.remove_files_after_upload:
                shutil.rmtree(src_dir_path)
                log_info("finished removing source")
            else:
                log_info("skipped removal of source")
            return "no files found"

        # determine file differences between src and dst
        files_missing_in_dst = src_files.difference(set(meta.uploaded_files))
        log_info(f"{len(files_missing_in_dst)} files missing in dst")

        # possibly create remote directory
        if not self.remote_connection.transfer_process.is_remote_dir(
            dst_dir_path
        ):
            self.remote_connection.connection.run(f"mkdir -p {dst_dir_path}")
            assert self.remote_connection.transfer_process.is_remote_dir(
                dst_dir_path
            )
            log_info(f"created remote directory")

        # logging progress every 10%
        max_file_count_characters = len(str(len(src_files)))
        log_progress: Callable[[float], None] = lambda fraction: log_info(
            f"{int(fraction * 100):3d} % " +
            f"({len(meta.uploaded_files):{max_file_count_characters}d}/{len(src_files)})"
            + f" uploaded {'(finished)' if fraction == 1 else ''}"
        )

        # locking the directory both locally and remote
        with circadian_scp_upload.utils.TwinFileLock(
            src_dir_path,
            dst_dir_path,
            self.remote_connection.connection,
            log_info=self.callbacks.log_info
        ):
            progress: float = len(meta.uploaded_files) / len(src_files)

            # upload every file that is missing in the remote
            # meta but present in the local directory
            for f in sorted(files_missing_in_dst):
                self.remote_connection.transfer_process.put(
                    os.path.join(src_dir_path, f), f"{dst_dir_path}/{f}"
                )
                meta.uploaded_files.append(f)
                meta.dump()
                new_progress = len(meta.uploaded_files) / len(src_files)
                if math.floor(new_progress * 10) != math.floor(progress * 10):
                    log_progress(progress)
                    if self.callbacks.should_abort_upload():
                        return "aborted"
                progress = new_progress

            log_progress(1)

            # raise an exception if the checksums do not match
            if not self.__directory_checksums_match(dir_name):
                log_error("checksums do not match")
                return "failed"
            else:
                log_info("checksums match")

        # only remove src if configured and checksums match
        if self.remove_files_after_upload:
            shutil.rmtree(src_dir_path)
            log_info("finished removing source")
        else:
            log_info("skipped removal of source")

        return "successful"

    def __upload_date_files(
        self, date: datetime.date
    ) -> Literal["successful", "failed"]:
        meta = circadian_scp_upload.utils.UploadMeta.init(
            src_dir_path=self.src_path
        )

        # determine file differences between src and dst
        file_regex = date.strftime(self.callbacks.dated_regex)
        src_files = set([
            f for f in os.listdir(self.src_path) if re.match(file_regex, f)
        ])
        files_missing_in_dst = src_files.difference(set(meta.uploaded_files))
        self.callbacks.log_info(
            f"{date}: {len(files_missing_in_dst)} files missing in dst"
        )

        # locking the directory both locally and remote
        with circadian_scp_upload.utils.TwinFileLock(
            self.src_path,
            self.dst_path,
            self.remote_connection.connection,
            log_info=self.callbacks.log_info
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

    def block_if_process_is_already_running(self) -> None:
        """Checks whether any filelock is locked in the source directory.
        Raises an exception if this is the case because this would mean
        that another upload process is currently running on that source
        directory."""

        for do_not_touch_filepath in glob.glob(
            os.path.join(self.src_path, "**", ".do-not-touch"), recursive=True
        ) + glob.glob(os.path.join(self.src_path, ".do-not-touch")):
            if filelock.FileLock(do_not_touch_filepath).is_locked:
                raise Exception(
                    f"path is used by another upload process: " +
                    f"filelock at {do_not_touch_filepath} is locked"
                )

    def run(self) -> None:
        self.block_if_process_is_already_running()
        src_dates = circadian_scp_upload.utils.get_src_dates(
            self.src_path, self.variant, self.callbacks.dated_regex
        )
        self.callbacks.log_info(
            f"Searching for dates in {self.src_path} using " +
            f"the regex {self.callbacks.dated_regex}"
        )
        self.callbacks.log_info(
            f"Found {len(src_dates)} date(s) to be uploaded: {src_dates}"
        )

        for date, paths in src_dates.items():
            if self.variant == "directories":
                self.callbacks.log_info(
                    f"{date}: found {len(paths)} paths for this date: {paths}"
                )
                for path in paths:
                    result = self.__upload_date_directory(
                        date, os.path.basename(path)
                    )
                    self.callbacks.log_info(f"{date}: done ({result})")
                    if result == "aborted":
                        break

            elif self.variant == "files":
                result = self.__upload_date_files(date)
                self.callbacks.log_info(f"{date}: done ({result})")

            if self.callbacks.should_abort_upload():
                self.callbacks.log_info("Aborting upload")
                break
