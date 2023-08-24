import datetime
import os
import random
import time
from typing import Callable, Literal
import dotenv


def load_credentials() -> tuple[str, str, str]:
    dotenv.load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    TEST_SERVER_HOST = os.getenv("TEST_SERVER_HOST")
    assert isinstance(TEST_SERVER_HOST, str)

    TEST_SERVER_USERNAME = os.getenv("TEST_SERVER_USERNAME")
    assert isinstance(TEST_SERVER_USERNAME, str)

    TEST_SERVER_PASSWORD = os.getenv("TEST_SERVER_PASSWORD")
    assert isinstance(TEST_SERVER_PASSWORD, str)

    return TEST_SERVER_HOST, TEST_SERVER_USERNAME, TEST_SERVER_PASSWORD


def generate_tmp_directory_path() -> str:
    """Generate a path to a temporary directory that does not exist yet."""
    current_timestamp = int(time.time())
    current_filepath: Callable[
        [], str
    ] = lambda: f"/tmp/circadian_scp_upload_test_{current_timestamp}"
    while os.path.exists(current_filepath()):
        current_timestamp += 1
    return current_filepath()


def generate_random_string(n: int = 20) -> str:
    """Generate a random string consisting of lowercase letters."""
    letters = [chr(i) for i in range(ord("a"), ord("z") + 1)]
    return "".join([random.choice(letters) for i in range(n)])


def generate_dummy_date_strings() -> list[str]:
    """Generate a list of dummy date strings (YYYYMMDD)."""
    current_time = datetime.datetime.now()

    # the 7 days centered around today
    dates: list[datetime.date] = [
        (current_time + datetime.timedelta(days=delta)).date() for delta in range(-3, 4)
    ]

    # 4 random dates from the past 50 years, 4 from the future 50 years
    for i in range(8):
        dates.append(
            current_time
            + datetime.timedelta(
                days=(random.choice(range(4, 365 * 50)) * (-1 if i < 4 else 1))
            )
        )

    return [d.strftime("%Y%m%d") for d in dates]


def generate_dummy_files(date_string: str, n: int = 5) -> dict[str, str]:
    """For a given date string, generate a bunch of dummy files.

    For example, the call `generate_dummy_files(20190102)` might return:

    ```python
    {
        "ma20190102.txt": "some content",
        "mb20190102-0001.txt": "some other content",
        ...
    }
    ```"""
    output: dict[str, str] = {}
    for _ in range(n):
        prefix = random.choice(["", "ma", "mb", "file-"])
        suffix = random.choice(["", ".txt", "0001", "-0001.txt", "-0002", "0002.txt"])
        output[f"{prefix}{date_string}{suffix}"] = generate_random_string()
    return output


def provide_test_directory(
    variant: Literal["directories", "files"]
) -> tuple[str, dict[str, dict[str, str]]]:
    tmp_dir_path = generate_tmp_directory_path()
    dummy_files: dict[str, dict[str, str]] = {
        ds: generate_dummy_files(ds) for ds in generate_dummy_date_strings()
    }
    for date_string, files in dummy_files.items():
        date_dir_path = tmp_dir_path
        if variant == "directories":
            date_dir_path = os.path.join(tmp_dir_path, date_string)
        os.makedirs(date_dir_path, exist_ok=True)

        for filename, content in files.items():
            with open(os.path.join(date_dir_path, filename), "w") as f:
                f.write(content)

    return tmp_dir_path, dummy_files
