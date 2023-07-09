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
        """Perform the whole upload process for a given directory.

        1. If the respective remote directory doesn't exist, create it
        2. Download the current upload-meta.json file from the server
           or use a new one
        3. Determine which files have not been uploaded yet
        4. Upload every file that is found locally but not in the remote
           meta. Update the remote meta every 25 uploaded files (reduces
           load and traffic).
        5. Test whether the checksums of "files on server" and "local ifgs"
           are equal, raise an exception (and end the function) if the differ
        6. Indicate that the upload process is complete in remote meta
        7. Optionally remove local ifgs"""

        meta = daily_scp_sync.utils.UploadMeta.init(
            src_dir_path=f"{self.src_path}/{date_string}",
            dst_dir_path=f"{self.dst_path}/{date_string}",
            connection=self.remote_client.connection,
            transfer_process=self.remote_client.transfer_process,
        )

        # determine files present in src and dst directory
        # files should be named like "<anything>YYYYMMDD<anything>"
        file_regex = self.callbacks.date_string_to_dir_file_regex(date_string)
        raw_src_files = os.listdir(os.path.join(self.src_path, date_string))
        src_file_set = set([f for f in raw_src_files if re.match(file_regex, f)])
        dst_file_set = set(meta.fileList)

        # determine file differences between src and dst
        files_missing_in_dst = src_file_set.difference(dst_file_set)
        files_missing_in_src = dst_file_set.difference(src_file_set)

        # this can happen, when the process fails during the src removal
        if len(files_missing_in_src) > 0:
            self.callbacks.log_error(
                f"{date_string}: files present in dst are missing in src: {files_missing_in_src}"
            )
            return

        # if there are files that have not been uploaded, assert that the
        # remote meta also indicates an incomplete upload state
        if (len(files_missing_in_dst) != 0) and meta.complete:
            self.callbacks.log_error(
                f"{date_string}: missing files on dst but remote meta contains complete=True"
            )
            return

        # upload every file that is missing in the remote
        # meta but present in the local directory
        for i, f in enumerate(sorted(files_missing_in_dst)):
            self.remote_client.transfer_process.put(
                os.path.join(self.src_path, date_string, f),
                f"{self.dst_path}/{date_string}/{f}",
            )
            meta.fileList.append(f)

            # update the local meta in every loop, but only
            # sync the remote meta every 25 iterations
            if ((i + 1) % 25 == 0) or (i == len(files_missing_in_dst) - 1):
                meta.dump(transfer_process=self.remote_client.transfer_process)
            else:
                meta.dump()

        # raise an exception if the checksums do not match
        if not self.__directory_checksums_match(date_string):
            self.callbacks.log_error(f"{date_string}: checksums do not match")
            return

        # only set meta.complete to True, when the checksums match
        meta.complete = True
        meta.dump(transfer_process=self.remote_client.transfer_process)
        self.callbacks.log_info(f"{date_string}: Successfully uploaded")

        # only remove src if configured and checksums match
        if self.remove_files_after_upload:
            shutil.rmtree(os.path.join(self.src_path, date_string))
            self.callbacks.log_info(f"{date_string}: Successfully removed source")
        else:
            self.callbacks.log_info(f"{date_string}: Skipping removal of source")

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
