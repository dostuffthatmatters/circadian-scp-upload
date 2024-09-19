from typing import List
import datetime
import pytest

from circadian_scp_upload.utils import _file_or_dir_name_to_date


@pytest.mark.order(2)
def test_file_or_dir_name_to_date_parsing() -> None:
    expected_date = datetime.date(2021, 2, 3)
    assert _file_or_dir_name_to_date("2021-02-03", "^%Y%m%d$") == None
    assert _file_or_dir_name_to_date("2021020", "^%Y%m%d$") == None
    assert _file_or_dir_name_to_date("2021020a", "^%Y%m%d$") == None
    assert _file_or_dir_name_to_date("a2021020", "^%Y%m%d$") == None

    assert _file_or_dir_name_to_date("20210203", "^%Y%m%d$") == expected_date
    assert _file_or_dir_name_to_date(
        "asds20210203", "^.*%Y%m%d$"
    ) == expected_date
    assert _file_or_dir_name_to_date(
        "ads20210203.asd", "^.*%Y%m%d.*$"
    ) == expected_date
    assert _file_or_dir_name_to_date(
        "20210203.txt", "^.*%Y%m%d.*$"
    ) == expected_date

    assert _file_or_dir_name_to_date(
        "2021-02-03", "^%Y-%m-%d$"
    ) == expected_date
    assert _file_or_dir_name_to_date(
        "2021-03-02", "^%Y-%d-%m$"
    ) == expected_date
    assert _file_or_dir_name_to_date(
        "03-02-2021", "^%d-%m-%Y$"
    ) == expected_date
    assert _file_or_dir_name_to_date(
        "03-2021-02", "^%d-%Y-%m$"
    ) == expected_date
    assert _file_or_dir_name_to_date(
        "02-2021-03", "^%m-%Y-%d$"
    ) == expected_date
    assert _file_or_dir_name_to_date(
        "02-03-2021", "^%m-%d-%Y$"
    ) == expected_date


@pytest.mark.order(2)
def test_file_or_dir_name_to_date_ambiguity() -> None:
    def _test(
        dated_regex: str,
        good_strings: List[str],
        bad_strings: List[str],
    ) -> None:
        print(f"dated_regex = {dated_regex}")
        for good_string in good_strings:
            print(f"good_string = {good_string}")
            assert _file_or_dir_name_to_date(
                good_string, dated_regex
            ) is not None

        for bad_string in bad_strings:
            print(f"bad_string = {bad_string}")
            try:
                _file_or_dir_name_to_date(bad_string, dated_regex)
                assert False, f'Should have raised a ValueError'
            except ValueError:
                pass

    _test(
        dated_regex="^%Y.*%m.*%d$",
        good_strings=["2022-03-04"],
        bad_strings=["2022-03-04-05", "2022-2021-04-05"],
    )
    _test(
        dated_regex="^.*%Y%m%d.*$",
        good_strings=["20220204"],
        bad_strings=["202202041", "20220204-20220205"],
    )
    _test(
        dated_regex="^.*%Y-%m-%d.*$",
        good_strings=["2022-02-04"],
        bad_strings=["2020-11-2020-11-11", "2020-11-20.2020-12-20"],
    )


@pytest.mark.order(2)
def test_file_or_dir_name_to_date_timing() -> None:
    now = datetime.datetime.now()
    latest_date = ((now - datetime.timedelta(days=1)) if (now.hour > 0) else
                   (now - datetime.timedelta(days=2))).date()

    not_considered_dates = [(latest_date + datetime.timedelta(days=n))
                            for n in range(1, 11)]
    considered_dates = [(latest_date - datetime.timedelta(days=n))
                        for n in range(0, 10)]
    for date in not_considered_dates:
        assert _file_or_dir_name_to_date(
            date.strftime("%Y-%m-%d"), "^%Y-%m-%d$"
        ) == None
    for date in considered_dates:
        assert _file_or_dir_name_to_date(
            date.strftime("%Y-%m-%d"), "^%Y-%m-%d$"
        ) == date
