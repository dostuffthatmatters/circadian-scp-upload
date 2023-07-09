import re
import os
import hashlib
import pathlib


def get_dir_checksum(path: str, file_regex: str) -> str:
    assert os.path.isdir(path), f'"{path}" is not a directory'
    ifg_files: list[str] = []
    for p in pathlib.Path(path).glob("*"):
        if p.is_file() and re.match(file_regex, str(p).split("/")[-1]):
            ifg_files.append(str(p))

    # calculate checksum over all files (sorted)
    hasher = hashlib.md5()
    for filename in sorted(ifg_files):
        filepath = os.path.join(path, filename)
        with open(filepath, "rb") as f:
            hasher.update(f.read())

    return hasher.hexdigest()


def get_file_checksum(path: str) -> str:
    assert os.path.isfile(path), f'"{path}" is not a file'
    hasher = hashlib.md5()
    with open(path, "rb") as f:
        hasher.update(f.read())
    return hasher.hexdigest()
