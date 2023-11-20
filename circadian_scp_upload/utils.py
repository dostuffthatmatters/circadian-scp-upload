from __future__ import annotations
from typing import Any, Callable, List, Literal, Optional
import json
import os
import re
import datetime
import pydantic
import filelock
import fabric.connection


def filename_is_ambiguous_for_dated_regex(regex: str, filename: str) -> bool:
    """Returns true if the filename matches the dated regex more than once.

    This happens when this filename could have been produced on more than one
    date with respect to the dated regex. For example, if the dated regex is
    `^.*%Y%m%d.*$`, the filename `log-2020111111.txt` is ambiguous because
    it could have been produced on 2020-11-11 or 2011-11-11."""

    substrings = ([filename[0 : i] for i in range(1, len(filename))] +
                  [filename[i :] for i in range(1, len(filename))] + [filename])
    trimmed_regex = regex[regex.index("("): regex.rindex(")") + 1]
    trimmed_regex = trimmed_regex.replace("(", "").replace(")", "")

    matches: list[str] = []

    for substring in substrings:
        new_matches = re.findall(trimmed_regex, substring)
        assert isinstance(new_matches, list)
        assert all(isinstance(m, str) for m in new_matches)
        matches += new_matches

    return len(set(matches)) > 1


def file_or_dir_name_to_date(
    file_or_dir_name: str,
    dated_regex: str,
) -> Optional[datetime.date]:
    """Converts a string to a date based on a dated regex.

    Sample input for `string`: "2021-01-01"
    Sample input for `dated_regex`: "%Y-%m-%d" """

    # only consider dates after at least 1
    # hour of the following day has passed
    now = datetime.datetime.now()
    latest_date = ((now - datetime.timedelta(days=1)) if (now.hour > 0) else
                   (now - datetime.timedelta(days=2))).date()

    keys = list(sorted(["%Y", "%m", "%d"], key=lambda x: dated_regex.index(x)))

    regex = dated_regex
    for old, new in {
        "%Y": r"(\d{4})",
        "%m": r"(\d{2})",
        "%d": r"(\d{2})",
    }.items():
        regex = regex.replace(old, new)

    if filename_is_ambiguous_for_dated_regex(regex, file_or_dir_name):
        raise ValueError()

    matches = re.findall(regex, file_or_dir_name)
    if len(matches) == 0:
        return None
    assert len(matches) == 1
    match = matches[0]
    assert isinstance(match, tuple)
    assert len(match) == 3
    try:
        date = datetime.datetime.strptime(
            f"{match[0]}-{match[1]}-{match[2]}", "-".join(keys)
        ).date()
        return date if (date <= latest_date) else None
    except ValueError:
        return None


def get_src_dates(
    src_path: str,
    variant: Literal["directories", "files"],
    dated_regex: str,
) -> dict[datetime.date, list[str]]:
    """For a given src path and dated regex,returns"""

    dates: dict[datetime.date, list[str]] = {}

    if not os.path.isdir(src_path):
        raise Exception(f'path "{src_path}" is not a directory')

    ambiguous_paths: list[str] = []

    for file_or_dir_name in os.listdir(src_path):
        file_or_dir_path = os.path.join(src_path, file_or_dir_name)

        try:
            if variant == "directories":
                consider_path = os.path.isdir(file_or_dir_path)
            else:
                consider_path = os.path.isfile(file_or_dir_path)
            if consider_path:
                date = file_or_dir_name_to_date(file_or_dir_name, dated_regex)
                if date is not None:
                    if date not in dates:
                        dates[date] = []
                    dates[date].append(file_or_dir_path)
        except ValueError:
            ambiguous_paths.append(file_or_dir_path)

    if len(ambiguous_paths) > 0:
        raise ValueError(
            f"The following {variant} match the regex `{repr(dated_regex)}` but cannot be "
            +
            f"parsed with parsed into a valid date because the result is ambiguous (can "
            + "be produced on more than one date): [\n" +
            ",\n".join(ambiguous_paths) + "\n]"
        )

    return dates


class UploadMeta(pydantic.BaseModel):
    src_dir_path: str
    uploaded_files: List[str]

    def dump(self) -> None:
        """dumps the meta object to a JSON file"""
        with open(
            os.path.join(self.src_dir_path, "upload-meta.json"), "w"
        ) as f:
            json.dump(self.model_dump(exclude={"src_dir_path"}), f, indent=4)

    @staticmethod
    def init(src_dir_path: str) -> UploadMeta:
        src_dir_path = src_dir_path.rstrip("/")

        if os.path.isfile(src_dir_path):
            try:
                with open(
                    os.path.join(src_dir_path, "upload-meta.json"), "r"
                ) as f:
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

    model_config = pydantic.ConfigDict(extra="forbid")

    dated_regex: str = pydantic.Field(
        default=r"^.*" + "%Y%m%d" + r".*$",
        description=
        "Which files/directories to consider in the upload process. The patterns `%Y`/`%m`/`%d` represent the date at which the file was generated. Any string containing some pattern except for these four will raise an exception. `%Y` = 4-digit year, `%m` = 2-digit month, `%d` = 2-digit day (all fixed width, i.e. zero-padded).",
    )

    @pydantic.field_validator("dated_regex", mode="before")
    @classmethod
    def _validate_dated_regex(cls, v: str) -> str:
        checks: list[tuple[bool, str]] = [
            ("%Y" in v, "string must contain `%Y`"),
            ("%m" in v, "string must contain `%m`"),
            ("%d" in v, "string must contain `%d`"),
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
        description=
        "Function to be called when logging a message or type ERROR.",
    )
    should_abort_upload: Callable[[], bool] = pydantic.Field(
        default=(lambda: False),
        description=
        "Can be used to interrupt the upload process. This function will be run between each file or directory and (when uploading large directories), after every 25 files. If it returns true, then the upload process will be aborted.",
    )


class TwinFileLock:
    def __init__(
        self,
        local_dir_path: str,
        remote_dir_path: str,
        remote_connection: fabric.connection.Connection,
        log_info: Optional[Callable[[str], None]] = None,
    ):
        self.src_filepath = os.path.join(local_dir_path, ".do-not-touch")
        self.dst_filepath = f"{remote_dir_path}/.do-not-touch"

        self.src_filelock = filelock.FileLock(self.src_filepath)
        self.remote_connection = remote_connection
        self.log_info = log_info

    def __enter__(self) -> None:
        if self.log_info is not None:
            self.log_info(
                f'acquiring lock on local machine at "{self.src_filepath}"'
            )
        self.src_filelock.acquire(timeout=0)
        if self.log_info is not None:
            self.log_info(
                f'acquiring lock on remote server at "{self.dst_filepath}"'
            )
        self.remote_connection.run(f"touch {self.dst_filepath}")

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        if self.log_info is not None:
            self.log_info(
                f'releasing lock on remote server at "{self.dst_filepath}"'
            )
        self.remote_connection.run(f"rm -rf {self.dst_filepath}")

        if self.log_info is not None:
            self.log_info(
                f'releasing lock on local machine at "{self.src_filepath}"'
            )
        self.src_filelock.release()
        if os.path.isfile(self.src_filepath):
            os.remove(self.src_filepath)
