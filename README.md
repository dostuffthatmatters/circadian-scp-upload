# 📮 Circadian SCP Upload

**Resumable, interruptible, well-tested SCP upload client for any files or directories generated day by day.**

[![GitHub Workflow Status (with event)](https://img.shields.io/github/actions/workflow/status/dostuffthatmatters/circadian-scp-upload/test.yaml?label=CI%20tests&cacheSeconds=60)](https://github.com/dostuffthatmatters/circadian-scp-upload/actions/workflows/test.yaml)
[![GitHub](https://img.shields.io/github/license/dostuffthatmatters/circadian-scp-upload?color=4c1&cacheSeconds=60)](https://github.com/dostuffthatmatters/circadian-scp-upload/blob/main/LICENSE.md)
[![PyPI - Version](https://img.shields.io/github/v/tag/dostuffthatmatters/circadian-scp-upload?label=latest%20version&color=f5f5f5&cacheSeconds=60)](https://pypi.org/project/circadian-scp-upload)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/circadian_scp_upload?label=supported%20Python%20versions&color=f5f5f5&cacheSeconds=60)](https://pypi.org/project/circadian-scp-upload)

## Use Case

You have a local directory that generates daily data on your local machine. The directory looks like this:

```
📁 data-directory-1
├── 📁 20190101
│   ├── 📄 file1.txt
│   ├── 📄 file2.txt
│   └── 📄 file3.txt
└── 📁 20190102
    ├── 📄 file1.txt
    ├── 📄 file2.txt
    └── 📄 file3.txt
```

Or like this:

```
📁 data-directory-2
├── 📄 20190101.txt
├── 📄 20190102-a.txt
├── 📄 20190102-b.txt
└── 📄 20190103.txt
```

With this tool you can:

- Upload that data to a server, right **after** the day of creation
- Mark directories as "in progress" on the remote server so that subsequent processing steps will not touch unfinished days of data while uploading.
- Optionally remove the local files after the upload is complete and verified with checksums

This tool uses [SCP](https://en.wikipedia.org/wiki/Secure_copy_protocol) via the Python library [paramiko](https://github.com/paramiko/paramiko) to do that. It will write files named `.do-not-touch` in the local and remote directories during the upload process and delete them afterward.

Below is a code snippet that defines a specific directory/file naming scheme (for example, `%Y%m%d-(\.txt|\.csv)`). The client uses this information to tell _when_ a specific file or directory was generated. It will only upload files when at least one hour of the following day has passed.

**Can't I use `rsync` or a similar CLI tool for that?**

Yes, of course. However, the actual copying logic of individual files or directories is just ~ 100 lines of code of this repository. The rest of this library is dedicated to being a plug-and-play solution for any Python codebase: logging, regex filters, being interruptable, in-progress markers, removing the local files after the checksums of local and remote directories are identical, etc.

One should be able to `pip install`/`pdm add`/... and call a well-documented and typed upload client class instead of manually connecting each codebase to rsync and doing all the pattern and scheduling logic repeatedly.

**How do you make sure that the upload works correctly?**

First, the whole codebase has type hints and is strictly checked with [Mypy](https://github.com/python/mypy) - even the snippet in the usage section below is tye checked with Mypy.

Secondly, the date patterning is tested extensively, and the upload process of the files and directories is tested with an actual remote server by generating a bunch of sample files and directories and uploading them to that server. One can check out the output of the test runs in the [GitHub Actions](https://github.com/dostuffthatmatters/circadian-scp-upload/actions/workflows/test.yaml) of this repository - in the "Run pytests" step.

Thirdly, after the upload, the checksum of the local and the remote directories/files is compared to ensure the upload was successful. Only if those checksums match will the client delete the local files. The file removal has to be actively enabled or disabled.

<br/>

## Usage

Install into any Python `^3.10` project:

```bash
pip install circadian_scp_upload
# or
pdm add circadian_scp_upload
```

Configure and use the upload client:

```python
import circadian_scp_upload

# Use the callbacks to customize the upload process
# and integrate it into your own codebase. All callbacks
# are optional and the callback object does not need to be
# passed to the upload client. The lambda functions below
# are the default values.

upload_client_callbacks = circadian_scp_upload.UploadClientCallbacks(
    # which directories/files to consider in the upload process; only
    # supports %Y/%y/%m/%d - does not support parentheses in the string
    dated_regex=r"^" + "%Y%m%d" + r"$",

    # use your own logger instead of print statements
    log_info=lambda message: print(f"INFO - {message}"),
    log_error=lambda message: print(f"ERROR - {message}"),

    # callback that is called periodically during the upload
    # process to check if the upload should be aborted
    should_abort_upload=lambda: False,
)

# teardown happens automatically when leaving the "with"-block
with circadian_scp_upload.RemoteConnection(
    "1.2.3.4", "someusername", "somepassword"
) as remote_connection:

    # upload a directory full of directories "YYYYMMDD/"
    circadian_scp_upload.DailyTransferClient(
        remote_connection=remote_connection,
        src_path="/path/to/local/data-directory-1",
        dst_path="/path/to/remote/data-directory-1",
        remove_files_after_upload=True,
        variant="directories",
        callbacks=upload_client_callbacks,
    ).run()

    # upload a directory full of files "YYYYMMDD.txt"
    circadian_scp_upload.DailyTransferClient(
        remote_connection=remote_connection,
        src_path="/path/to/local/data-directory-2",
        dst_path="/path/to/remote/data-directory-2",
        remove_files_after_upload=True,
        variant="files",
        callbacks=upload_client_callbacks,
    ).run()
```

The client will produce an informational output wherever one directs the log output:

```log
INFO - 2024-09-17: starting to upload local directory '/tmp/circadian_scp_upload_test/2024-09-17' to remote directory '/tmp/circadian_scp_upload_test/2024-09-17'
INFO - 2024-09-17: screening local directory
INFO - 2024-09-17: possibly creating remote directory
INFO - 2024-09-17: screening remote directory
INFO - 2024-09-17: comparing local and remote directory
INFO - 2024-09-17: found 0 synced files and 4 unsynced files
INFO - 2024-09-17: possibly creating all remote subdirectories
INFO - 2024-09-17: acquiring lock on local machine at "/tmp/circadian_scp_upload_test/2024-09-17/.do-not-touch"
INFO - 2024-09-17: acquiring lock on remote server at "/tmp/circadian_scp_upload_test/2024-09-17/.do-not-touch"
INFO - 2024-09-17: 100.0 % (4/4) uploaded (finished)
INFO - 2024-09-17: finished removing source
INFO - 2024-09-17: releasing lock on remote server at "/tmp/circadian_scp_upload_test/2024-09-17/.do-not-touch"
INFO - 2024-09-17: releasing lock on local machine at "/tmp/circadian_scp_upload_test/2024-09-17/.do-not-touch"
INFO - 2024-09-17: done (successful)
INFO - 2024-09-18: starting to upload local directory '/tmp/circadian_scp_upload_test/2024-09-18' to remote directory '/tmp/circadian_scp_upload_test/2024-09-18'
INFO - 2024-09-18: screening local directory
INFO - 2024-09-18: possibly creating remote directory
INFO - 2024-09-18: screening remote directory
INFO - 2024-09-18: comparing local and remote directory
INFO - 2024-09-18: found 0 synced files and 5 unsynced files
INFO - 2024-09-18: possibly creating all remote subdirectories
INFO - 2024-09-18: acquiring lock on local machine at "/tmp/circadian_scp_upload_test/2024-09-18/.do-not-touch"
INFO - 2024-09-18: acquiring lock on remote server at "/tmp/circadian_scp_upload_test/2024-09-18/.do-not-touch"
INFO - 2024-09-18: 100.0 % (5/5) uploaded (finished)
INFO - 2024-09-18: finished removing source
INFO - 2024-09-18: releasing lock on remote server at "/tmp/circadian_scp_upload_test/2024-09-18/.do-not-touch"
INFO - 2024-09-18: releasing lock on local machine at "/tmp/circadian_scp_upload_test/2024-09-18/.do-not-touch"
INFO - 2024-09-18: done (successful)
```

If the upload takes longer than 1 minute, it logs its progress (e.g. ` 40.0 % (3/5) uploaded`) every minute.
