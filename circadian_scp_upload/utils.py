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

    output: list[str] = []
    invalid_filenames: list[str] = []
    for filename in os.listdir(src_path):
        filepath = os.path.join(src_path, filename)
        try:
            if variant == "directories":
                assert os.path.isdir(filepath)
                assert _is_valid_date_string(filename)
                output.append(filename)
            else:
                invalid_filenames = re.findall(r"(\d{9})", filename)
                if len(invalid_filenames) > 0:
                    invalid_filenames.append(filename)

                date_string_matches = re.findall(r"(\d{8})", filename)
                assert isinstance(date_string_matches, list)
                if len(date_string_matches) > 1:
                    invalid_filenames.append(filename)
                for m in date_string_matches:
                    assert isinstance(m, str)
                    if _is_valid_date_string(m):
                        output.append(m)
        except AssertionError:
            pass

    if len(invalid_filenames) > 0:
        raise Exception(
            "The following filenames are invalid due to having 9 or more "
            + "succeeding digits or two or more blocks of 8 succeeding "
            + "digits in their name- due to this it, their date of "
            + f"generation cannot be determined: {invalid_filenames}"
        )
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

    dated_directory_regex: str = pydantic.Field(
        default=r"^[\.].*" + "%Y%m%d" + r".*$",
        description=(
            "Which directories to consider in the upload process. The "
            + "patterns `%Y`/`%y`/`%m`/`%d` represent the date at which "
            + "the file was generated. Any string containing some pattern "
            + "except for these four will raise an exception. "
            + "`%Y` = 4-digit year, `%y` = 2-digit year, `%m` = 2-digit "
            + "month, `%d` = 2-digit day (all fixed width, i.e. zero-padded)."
        ),
    )
    dated_file_regex: str = pydantic.Field(
        default=r"^[\.].*" + "%Y%m%d" + r".*$",
        description=(
            "Which files to consider in the upload process. The patterns "
            + "`%Y`/`%y`/`%m`/`%d` represent the date at which the file "
            + "was generated. Any string containing some pattern except "
            + "for these four will raise an exception."
            + "`%Y` = 4-digit year, `%y` = 2-digit year, `%m` = 2-digit "
            + "month, `%d` = 2-digit day (all fixed width, i.e. zero-padded)."
        ),
    )

    @pydantic.field_validator(
        "dated_directory_regex",
        "dated_file_regex",
        mode="before",
    )
    @classmethod
    def _validate_dated_regex(cls, v: str) -> str:
        checks: list[tuple[bool, str]] = [
            (("%Y" in v) or ("%y" in v), "string must contain `%Y` or `%y`"),
            (("%m" in v) and ("%d" in v), "string must contain `%m` and `%d`"),
            (v.count("%") == 3, "string must contain exactly 3 `%` characters"),
            ("(" not in v, "string must not contain `(`"),
            (")" not in v, "string must not contain `)`"),
            (v.startswith("^"), "string must start with `^`"),
            (v.endswith("$"), "string must end with `$`"),
        ]
        error_message = "; ".join([m for (c, m) in checks if not c])
        if len(error_message) > 0:
            raise ValueError(f"value `{repr(v)}` is invalid: {error_message}")
        return v

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
        os.remove(self.src_filepath)
