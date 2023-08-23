from __future__ import annotations
import json
import os
import re
from typing import Any, Callable, Literal
import datetime
import pydantic
import glob
import filelock
import fabric.connection


def _is_valid_date_string(date_string: str) -> bool:
    try:
        day_ending = datetime.datetime.strptime(
            f"{date_string} 23:59:59", "%Y%m%d %H:%M:%S"
        )
        seconds_since_day_ending = (
            datetime.datetime.now() - day_ending
        ).total_seconds()
        assert seconds_since_day_ending >= 3600
        return True
    except (ValueError, AssertionError):
        return False


def get_src_date_strings(
    src_path: str, variant: Literal["directories", "files"]
) -> list[str]:
    if not os.path.isdir(src_path):
        raise Exception(f'path "{src_path}" is not a directory')

    for do_not_touch_filepath in glob.glob(
        os.path.join(src_path, "**", ".do-not-touch"), recursive=True
    ):
        if filelock.FileLock(do_not_touch_filepath).is_locked:
            raise Exception(
                f"path is used by another upload process: "
                + f"filelock at {do_not_touch_filepath} is locked"
            )

    output: list[str] = []
    for filename in os.listdir(src_path):
        filepath = os.path.join(src_path, filename)
        try:
            if variant == "directories":
                assert os.path.isdir(filepath)
                assert _is_valid_date_string(filename)
                output.append(filename)
            else:
                date_string_matches = re.findall(r"^.*(2\d{7}).*$", filename)
                assert len(date_string_matches) == 1
                assert isinstance(date_string_matches[0], str)
                assert _is_valid_date_string(date_string_matches[0])
                output.append(date_string_matches[0])
        except AssertionError:
            pass

    return list(set(output))


class UploadMeta(pydantic.BaseModel):
    src_dir_path: str
    uploaded_files: list[str]

    def dump(self) -> None:
        """dumps the meta object to a JSON file"""
        with open(os.path.join(self.src_dir_path, "upload-meta.json"), "w") as f:
            json.dump(self.model_dump(exclude={"src_dir_path"}), f, indent=4)

    @staticmethod
    def init(src_dir_path: str) -> UploadMeta:
        src_dir_path = src_dir_path.rstrip("/")

        if os.path.isfile(src_dir_path):
            try:
                with open(os.path.join(src_dir_path, "upload-meta.json"), "r") as f:
                    meta = UploadMeta(src_dir_path=src_dir_path, **json.load(f))
            except (
                FileNotFoundError,
                TypeError,
                json.JSONDecodeError,
                pydantic.ValidationError,
            ):
                raise Exception("could not load local upload-meta.json")
        else:
            meta = UploadMeta(src_dir_path=src_dir_path, uploaded_files=[])

        return meta


class UploadClientCallbacks(pydantic.BaseModel):
    """A collection of callbacks passed to the upload client."""

    date_string_to_file_regex: Callable[[str], str] = pydantic.Field(
        default=(lambda date_string: r"^[^\.].*" + date_string + r".*$"),
        description=(
            "A function that takes a `date string` and returns a regex "
            + "string. For every `date_string`, the upload client finds, "
            + "only consider the files that match this regex string. "
            + "The default regex string will match any file that does "
            + "not start with a dot and contains the `date_string`."
        ),
    )
    log_info: Callable[[str], None] = pydantic.Field(
        default=(lambda msg: print(f"INFO - {msg}")),
        description="Function to be called when logging a message or type INFO.",
    )
    log_error: Callable[[str], None] = pydantic.Field(
        default=(lambda msg: print(f"ERROR - {msg}")),
        description="Function to be called when logging a message or type ERROR.",
    )
    should_abort_upload: Callable[[], bool] = pydantic.Field(
        default=(lambda: False),
        description="Can be used to interrupt the upload process. This "
        + "function will be run between each file or directory and (when "
        + "uploading large directories), after every 25 files. If it "
        + "returns true, then the upload process will be aborted.",
    )


class TwinFileLock:
    def __init__(
        self,
        local_dir_path: str,
        remote_dir_path: str,
        remote_connection: fabric.connection.Connection,
    ):
        self.src_filepath = os.path.join(local_dir_path, ".do-not-touch")
        self.dst_filepath = f"{remote_dir_path}/.do-not-touch"

        self.src_filelock = filelock.FileLock(self.src_filepath)
        self.remote_connection = remote_connection

    def __enter__(self) -> None:
        self.src_filelock.acquire(timeout=0)
        self.remote_connection.run(f"touch {self.dst_filepath}")

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.remote_connection.run(f"rm -r {self.dst_filepath}")
        self.src_filelock.release()
