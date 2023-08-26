import argparse
import re
import os
import hashlib
import pathlib


def get_dir_checksum(path: str, file_regex: str) -> str:
    assert os.path.isdir(path), f'"{path}" is not a directory'
    ifg_files: list[str] = []
    for p in pathlib.Path(path).glob("*"):
        basename = str(p).split("/")[-1]
        if all(
            [
                p.is_file(),
                basename != ".do-not-touch",
                basename != "upload-meta.json",
                re.match(file_regex, basename),
            ]
        ):
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
