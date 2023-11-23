from typing import List
import argparse
import re
import os
import hashlib
import pathlib


def get_dir_checksum(path: str, file_regex: str) -> str:
    assert os.path.isdir(path), f'"{path}" is not a directory'
    matching_filenames: List[str] = []
    for filename in os.listdir(path):
        full_path = os.path.join(path, filename)
        if (
            os.path.isfile(full_path) and
            (filename not in [".do-not-touch", "upload-meta.json"]) and
            re.match(file_regex, filename)
        ):
            matching_filenames.append(filename)

    # calculate checksum over all files (sorted)
    hasher = hashlib.md5()
    for filename in sorted(matching_filenames):
        filepath = os.path.join(path, filename)
        with open(filepath, "rb") as f:
            try:
                file_content = f.read()
            except Exception as e:
                raise Exception(f'Could not read file "{filepath}"') from e
            hasher.update(file_content)

    return hasher.hexdigest()


def get_file_checksum(path: str) -> str:
    assert os.path.isfile(path), f'"{path}" is not a file'
    hasher = hashlib.md5()
    with open(path, "rb") as f:
        try:
            file_content = f.read()
        except Exception as e:
            raise Exception(f'Could not read file "{path}"') from e
        hasher.update(file_content)
    return hasher.hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="checksum",
        description="Compute MD5 checksums of files or directories.",
    )
    parser.add_argument(
        "path",
        type=str,
        help="path to directory or file",
    )
    parser.add_argument(
        "--file_regex",
        type=str,
        help="regex to match files",
        required=False,
        default=r"^.*$",
    )

    args = parser.parse_args()
    assert isinstance(args.path, str)
    assert isinstance(args.file_regex, str)

    if os.path.isdir(args.path):
        print(get_dir_checksum(args.path, args.file_regex))
    elif os.path.isfile(args.path):
        print(get_file_checksum(args.path))
    else:
        raise Exception(f'The path "{args.path}"does not exist')
