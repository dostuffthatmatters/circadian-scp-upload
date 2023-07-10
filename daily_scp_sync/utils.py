from __future__ import annotations
import json
import os
from typing import Callable
import datetime
import pydantic


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


def get_src_date_strings(src_path: str) -> list[str]:
    if not os.path.isdir(src_path):
        return []

    return [
        date_string
        for date_string in os.listdir(src_path)
        if (
            os.path.isdir(os.path.join(src_path, date_string))
            and _is_valid_date_string(date_string)
        )
    ]


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

    date_string_to_dir_file_regex: Callable[[str], str] = pydantic.Field(
        default=(lambda date_string: r"^[\.].*" + date_string + r".*$"),
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
