from __future__ import annotations
from typing import Any, Callable, Literal
import time
import glob
import fabric.connection
import fabric.transfer
import os
import shutil
import filelock
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
        callbacks: circadian_scp_upload.UploadClientCallbacks = circadian_scp_upload.
        UploadClientCallbacks(),
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

    def __upload_directory(
        self, dir_name: str
    ) -> Literal["successful", "failed", "aborted", "no files found"]:
        """Perform the whole upload process for a given directory.

        1. If the respective remote directory doesn't exist, create it
        2. Determine which files have not been uploaded yet
        4. Upload every file that is found locally but has not been uploaded yet
        5. Test whether the checksums of "files on server" and "local ifgs"
           are equal, raise an exception (and end the function) if they differ
        7. Optionally remove the local directory"""

        log_info: Callable[[str], None] = lambda msg: self.callbacks.log_info(f"{dir_name}: {msg}")
        log_error: Callable[[str],
                            None] = lambda msg: self.callbacks.log_error(f"{dir_name}: {msg}")

        src_dir_path = os.path.join(self.src_path, dir_name)
        dst_dir_path = f"{self.dst_path}/{dir_name}"
        twin_lock = circadian_scp_upload.utils.TwinFileLock(
            src_dir_path, dst_dir_path, self.remote_connection.connection, log_info=log_info
        )
        log_info(
            f"starting to upload local directory '{src_dir_path}'" +
            f" to remote directory '{dst_dir_path}'"
        )

        log_info(f"screening local directory")
        local_directory = circadian_scp_upload.screen_directory(src_dir_path)

        log_info("possibly creating remote directory")
        self.remote_connection.connection.run(f"mkdir -p {dst_dir_path}")

        log_info(f"screening remote directory")
        remote_directory = circadian_scp_upload.screen_directory(
            dst_dir_path, self.remote_connection.connection
        )

        log_info(f"comparing local and remote directory")
        files_in_sync, files_not_in_sync = circadian_scp_upload.compare_directory_screens(
            local_directory, remote_directory
        )
        log_info(
            f"found {len(files_in_sync)} synced files and {len(files_not_in_sync)} unsynced files"
        )

        if len(files_not_in_sync) == 0:
            log_info("directories are in sync")
            if self.remove_files_after_upload:
                shutil.rmtree(src_dir_path)
                log_info("finished removing source")
            else:
                log_info("skipped removal of source")
            twin_lock.release()
            return "successful"

        # quit if no src files are found
        if len(files_in_sync.union(files_not_in_sync)) == 0:
            log_info("directory is empty")
            if self.remove_files_after_upload:
                shutil.rmtree(src_dir_path)
                log_info("finished removing source")
            else:
                log_info("skipped removal of source")
            return "no files found"

        # create all subdirectories on the remote server
        log_info("possibly creating all remote subdirectories")
        self.remote_connection.connection.run(
            f"mkdir -p " +
            (" ".join([f"{dst_dir_path}/{p}" for p in local_directory.get_subdirectories()]))
        )

        # logging progress
        def _log_progress() -> None:
            c, t = len(files_in_sync), len(local_directory.files)
            fraction, finished = c / t, c == t
            log_info(
                f"{int(fraction * 100):5.1f} % " + f"({c:{len(str(t))}d}/{t})" +
                f" uploaded {'(finished)' if finished else ''}"
            )

        twin_lock.aquire()

        # upload every file that is missing in the remote
        # meta but present in the local directory
        last_log_time = time.time()
        for f in sorted(list(files_not_in_sync)):
            self.remote_connection.transfer_process.put(
                os.path.join(src_dir_path, f.relative_path),
                f"{dst_dir_path}/{f.relative_path}"
            )
            files_not_in_sync.remove(f)
            files_in_sync.add(f)

            if ((time.time() - last_log_time)
                > 60) or (len(files_not_in_sync) == 0):
                _log_progress()
                last_log_time = time.time()

            if self.callbacks.should_abort_upload():
                return "aborted"

        # compute remote checksum again
        remote_directory = circadian_scp_upload.screen_directory(
            dst_dir_path, self.remote_connection.connection
        )
        updated_files_in_sync, updated_files_not_in_sync = circadian_scp_upload.compare_directory_screens(
            local_directory, remote_directory
        )
        assert len(files_not_in_sync) == 0, "This should not happen"
        assert files_in_sync == updated_files_in_sync, "This should not happen"
        if len(updated_files_not_in_sync) > 0:
            log_error(
                f"upload is not complete, some files are missing ({updated_files_not_in_sync})"
            )
            return "failed"

        # only remove src if configured and checksums match
        if self.remove_files_after_upload:
            shutil.rmtree(src_dir_path)
            log_info("finished removing source")
        else:
            log_info("skipped removal of source")

        twin_lock.release()

        return "successful"

    def __upload_files(
        self,
        considered_filenames: set[str],
    ) -> Literal["successful", "failed"]:

        self.callbacks.log_info(f"screening local directory")
        local_directory = circadian_scp_upload.screen_directory(
            self.src_path, max_depth=1
        )
        local_directory.filter_by_filenames(considered_filenames)

        self.callbacks.log_info(f"screening remote directory")
        remote_directory = circadian_scp_upload.screen_directory(
            self.dst_path, self.remote_connection.connection, max_depth=1
        )

        self.callbacks.log_info(f"comparing local and remote directory")
        files_in_sync, files_not_in_sync = circadian_scp_upload.compare_directory_screens(
            local_directory, remote_directory
        )
        self.callbacks.log_info(
            f"found {len(files_in_sync)} synced files and {len(files_not_in_sync)} unsynced files"
        )

        if self.remove_files_after_upload:
            self.callbacks.log_info("removing files that are in sync")
            for f in files_in_sync:
                os.remove(os.path.join(self.src_path, f.relative_path))

        twin_lock = circadian_scp_upload.utils.TwinFileLock(
            self.src_path,
            self.dst_path,
            self.remote_connection.connection,
            log_info=self.callbacks.log_info
        )
        twin_lock.aquire()

        # upload every file that is missing in the remote
        # meta but present in the local directory
        for f in sorted(list(files_not_in_sync)):
            self.callbacks.log_info(f"uploading {f.relative_path}")
            self.remote_connection.transfer_process.put(
                os.path.join(self.src_path, f.relative_path),
                f"{self.dst_path}/{f.relative_path}",
            )
            if self.remove_files_after_upload:
                self.callbacks.log_info(f"removing local {f.relative_path}")
                os.remove(os.path.join(self.src_path, f.relative_path))

        twin_lock.release()

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

        src_items = circadian_scp_upload.list_src_items(
            self.src_path, self.variant, self.callbacks.dated_regex
        )
        self.callbacks.log_info(
            f"Searching for dates in {self.src_path} using " +
            f"the regex {self.callbacks.dated_regex}"
        )
        self.callbacks.log_info(f"Found {len(src_items)} item(s) to be uploaded: {src_items}")

        if self.variant == "directories":
            for item in src_items:
                result = self.__upload_directory(item)
                self.callbacks.log_info(f"{item}: done ({result})")
                if result == "aborted":
                    break
        else:
            self.callbacks.log_info("starting")
            result = self.__upload_files(set(src_items))
            self.callbacks.log_info(f"done ({result})")
