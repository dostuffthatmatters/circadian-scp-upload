# Daily SCP Sync

**Resumable, interruptible, SCP upload client for any files or directories generated day by day.**

<br/>

## Use Case

You have a local directory that generates data every day on you local machine. The directory looks like this:

```
📁 data-directory-2
├── 📁 20190101
│   ├── 📄 file1.txt
│   ├── 📄 file2.txt
│   └── 📄 file3.txt
└── 📁 20190102
    ├── 📄 file1.txt
    ├── 📄 file2.txt
    └── 📄 file3.txt
```

... or like this:

```
📁 data-directory-1
├── 📄 20190101.txt
├── 📄 20190102-a.txt
├── 📄 20190102-b.txt
└── 📄 20190103.txt
```

This tool can sync the local data to a remote server via SCP for these two directory structures.

- It will only upload directories or files one hour after midnight of the day they were generated (files directories labeled with `20190101` will only be considered after `2019-01-02 01:00:00`)
- It is resumable, meaning if the upload is interrupted, it will continue where it left off
- It is interruptible without running it in a separate thread (`should_abort_upload` callback)
- After a file or a directory has been uploaded, this tool will compute the checksum of the respective file(s) and delete the local file(s) only if the checksums match and if specified by the user

<br/>

## Usage

```python
import circadian_scp_upload

# Use the callbacks to customize the upload process
# and integrate it into your own application. All callbacks
# are optional and the callback object does not need to be
# passed to the upload client. The lambda functions below
# are the default values.

upload_client_callbacks = circadian_scp_upload.UploadClientCallbacks(
    # which files to consider in the upload process
    # function from YYYYMMDD string to regex
    date_string_to_dir_file_regex=(
        lambda date_string: r"^[\.].*" + date_string + r".*$"
    ),

    # use your own logger
    log_info=lambda message: print(f"INFO - {message}"),
    log_error=lambda message: print(f"ERROR - {message}"),

    # for example, we use this to make the upload stop, every time the
    # parameters for uploading changed (upload active true/false, etc.)
    should_abort_upload=lambda: False,
)

# teardown happens automatically when leaving the "with"-block
with circadian_scp_upload.RemoteConnection(
    "1.2.3.4", "someusername", "somepassword"
) as remote_connection:

    # upload a directory full of directories "YYYYMMDD/"
    circadian_scp_upload.DailyDirectoryTransferClient(
        remote_connection=remote_connection,
        src_path="/path/to/data-directory-1",
        dst_path="/path/to/remote/data-directory-1",
        remove_files_after_upload=True,
        callbacks=upload_client_callbacks,
    ).run()

    # upload a directory full of files "YYYYMMDD.txt"
    circadian_scp_upload.DailyFileTransferClient(
        remote_connection=remote_connection,
        src_path="/path/to/data-directory-2",
        dst_path="/path/to/remote/data-directory-2",
        remove_files_after_upload=True,
        callbacks=upload_client_callbacks,
    ).run()
```
