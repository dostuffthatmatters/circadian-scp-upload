import os
import re
from typing import Generator
import pytest

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README_FILE_PATH = os.path.join(PROJECT_DIR, "README.md")
PY_FILE_PATH = os.path.join(PROJECT_DIR, "main_template.py")


@pytest.fixture
def provide_main_template_file() -> Generator[None, None, None]:
    with open(README_FILE_PATH, "r") as f:
        content = f.read()
    m = re.findall(
        r"```python\n(import daily\_scp\_sync\n[^`]+)\n```",
        content,
        re.MULTILINE,
    )
    with open(PY_FILE_PATH, "w") as f:
        f.write(str(m[0]))

    yield

    os.remove(PY_FILE_PATH)


def test_static_types(provide_main_template_file: None) -> None:
    assert os.system("rm -rf .mypy_cache/3.11/daily_scp_sync") == 0
    assert os.system("mypy daily_scp_sync") == 0

    assert os.system("rm -rf .mypy_cache/3.11/main_template.*") == 0
    assert os.system(f"mypy {PY_FILE_PATH}") == 0
