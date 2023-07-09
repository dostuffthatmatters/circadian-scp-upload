import os
import datetime


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
