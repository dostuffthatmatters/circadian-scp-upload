import datetime
from circadian_scp_upload.utils import file_or_dir_name_to_date


def test_file_or_dir_name_to_date_parsing() -> None:
    expected_date = datetime.date(2021, 2, 3)
    assert file_or_dir_name_to_date("2021-02-03", "^%Y%m%d$") == None
    assert file_or_dir_name_to_date("2021020", "^%Y%m%d$") == None
    assert file_or_dir_name_to_date("2021020a", "^%Y%m%d$") == None
    assert file_or_dir_name_to_date("a2021020", "^%Y%m%d$") == None

    assert file_or_dir_name_to_date("20210203", "^%Y%m%d$") == expected_date
    assert file_or_dir_name_to_date("asds20210203", "^.*%Y%m%d$") == expected_date
    assert file_or_dir_name_to_date("ads20210203.asd", "^.*%Y%m%d.*$") == expected_date
    assert file_or_dir_name_to_date("20210203.txt", "^.*%Y%m%d.*$") == expected_date

    assert file_or_dir_name_to_date("2021-02-03", "^%Y-%m-%d$") == expected_date
    assert file_or_dir_name_to_date("2021-03-02", "^%Y-%d-%m$") == expected_date
    assert file_or_dir_name_to_date("03-02-2021", "^%d-%m-%Y$") == expected_date
    assert file_or_dir_name_to_date("03-2021-02", "^%d-%Y-%m$") == expected_date
    assert file_or_dir_name_to_date("02-2021-03", "^%m-%Y-%d$") == expected_date
    assert file_or_dir_name_to_date("02-03-2021", "^%m-%d-%Y$") == expected_date


def test_file_or_dir_name_to_date_ambiguity() -> None:
    dated_regex = "^%Y.*%m.*%d$"
    good_string = "2022-03-04"
    bad_string = "2022-03-04-05"

    assert file_or_dir_name_to_date(good_string, dated_regex) == datetime.date(
        2022, 3, 4
    )

    try:
        file_or_dir_name_to_date(bad_string, dated_regex)
        assert False, "Should have raised a ValueError"
    except ValueError:
        pass


def test_file_or_dir_name_to_date_timing() -> None:
    now = datetime.datetime.now()
    latest_datetime = (
        (now - datetime.timedelta(days=1))
        if (now.hour > 1)
        else (now - datetime.timedelta(days=2))
    )

    not_considered_dates = [
        (latest_datetime + datetime.timedelta(days=n)).date() for n in range(1, 11)
    ]
    considered_dates = [
        (latest_datetime - datetime.timedelta(days=n)).date() for n in range(0, 10)
    ]
    for date in not_considered_dates:
        assert file_or_dir_name_to_date(date.strftime("%Y-%m-%d"), "^%Y-%m-%d$") == None
    for date in considered_dates:
        assert file_or_dir_name_to_date(date.strftime("%Y-%m-%d"), "^%Y-%m-%d$") == date
