from typing import Callable, Dict, List, Literal, Tuple
import datetime
import os
import random
import sys
import time
import dotenv


def generate_random_string(min_length: int = 0, max_length: int = 5) -> str:
    """Generate a random string of length between `min_length` and `max_length`
    with random letters, and symbols (dash, underscore, dot). The strings will
    always start and end with a letter."""

    allowed_characters = [chr(o) for o in range(ord("a"), ord("z") + 1)]
    allowed_characters += [chr(o) for o in range(ord("A"), ord("Z") + 1)]
    allowed_symbols = ["-", "_", "."] * 3
    random_length = random.randint(min_length, max_length)
    string = ""
    if random_length > 0:
        string += random.choice(allowed_characters)
    if random_length > 2:
        for _ in range(random_length - 2):
            string += random.choice(allowed_characters + allowed_symbols)
    if random_length > 1:
        string += random.choice(allowed_characters)
    return string


def generate_random_dated_regexes() -> List[str]:
    dr: List[str] = []
    for _ in range(3):
        a = generate_random_string()
        b = generate_random_string()
        c = generate_random_string()
        specifiers = ["%Y", "%m", "%d"]
        random.shuffle(specifiers)
        dr.append(f"{a}{specifiers[0]}{b}{specifiers[1]}{c}{specifiers[2]}.*")

    return list(set(dr))


def load_credentials() -> Tuple[str, str, str]:
    dotenv.load_dotenv(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    )
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
    python_version = sys.version.split(" ")[0]
    current_filepath: Callable[
        [], str
    ] = lambda: f"/tmp/circadian_scp_upload_test_{current_timestamp}_{python_version}"
    while os.path.exists(current_filepath()):
        current_timestamp += 1
    return current_filepath()


def generate_dummy_dates() -> List[datetime.date]:
    """Generate a list of random dates"""

    today = datetime.date.today()
    timedeltas: List[datetime.timedelta] = []

    # the 7 days centered around today
    for delta in range(-3, 4):
        timedeltas.append(datetime.timedelta(days=delta))

    # 3 random dates from the past 50 years, 4 from the future 50 years
    for i in range(3):
        timedeltas.append(
            datetime.timedelta(days=(random.choice(range(4, 365 * 50))))
        )
        timedeltas.append(
            datetime.timedelta(days=(random.choice(range(4, 365 * 50)) * (-1)))
        )

    return [today + delta for delta in timedeltas]


def generate_dummy_files(dated_regex: str,
                         date: datetime.date,
                         n: int = 5) -> Dict[str, str]:
    """For a given date string, generate a bunch of dummy files.

    For example, the call `generate_dummy_files(20190102)` might return:

    ```python
    {
        "ma20190102.txt": "some content",
        "mb20190102-0001.txt": "some other content",
        ...
    }
    ```"""
    output: Dict[str, str] = {}
    for _ in range(n):
        suffix = generate_random_string(min_length=0, max_length=10)
        content = generate_random_string(min_length=10, max_length=40)
        output[f"{date.strftime(dated_regex)[:-2]}{suffix}"] = content
    return output


def provide_test_directory(
    variant: Literal["directories", "files"]
) -> Tuple[str, Dict[str, Dict[datetime.date, Dict[str, str]]]]:
    tmp_dir_path = generate_tmp_directory_path()
    os.mkdir(tmp_dir_path)

    dates = generate_dummy_dates()
    dated_regexes = generate_random_dated_regexes()
    files: Dict[str, Dict[datetime.date, Dict[str, str]]] = {}

    print("tmp_dir_path = ", tmp_dir_path)
    print("dates = ", dates)
    print("dated_regexes = ", dated_regexes)

    for dated_regex in dated_regexes:
        files[dated_regex] = {}
        for date in dates:
            files[dated_regex][date] = generate_dummy_files(dated_regex, date)

    for dated_regex in dated_regexes:
        root_dir_for_this_regex = os.path.join(tmp_dir_path, dated_regex[:-2])
        for date in dates:
            if variant == "directories":
                date_dir_path = os.path.join(
                    root_dir_for_this_regex, date.strftime(dated_regex[:-2])
                )
            else:
                date_dir_path = root_dir_for_this_regex
            os.makedirs(date_dir_path, exist_ok=True)

            for filename, content in files[dated_regex][date].items():
                with open(os.path.join(date_dir_path, filename), "w") as f:
                    f.write(content)

    return tmp_dir_path, files
