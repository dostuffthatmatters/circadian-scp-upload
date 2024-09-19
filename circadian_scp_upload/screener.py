from __future__ import annotations
from typing import Optional
import subprocess
import fabric.connection
import invoke
import pydantic


class Directory(pydantic.BaseModel):
    files: list[File] = pydantic.Field(
        ..., description="Files in the directory"
    )

    def get_subdirectories(self) -> set[str]:
        subdirs: set[str] = set()
        for file in self.files:
            subdir = file.subdirectory()
            if subdir is not None:
                subdirs.add(subdir)

        # sorting alphabetically will also put the parent directories first
        return subdirs

    def filter_by_filenames(self, relevant_filenames: set[str]) -> None:
        self.files = [
            file
            for file in self.files if file.relative_path in relevant_filenames
        ]


class File(pydantic.BaseModel):
    filesize: int = pydantic.Field(..., description="Size of the file in bytes")
    md5sum: str = pydantic.Field(..., description="MD5 checksum of the file")
    relative_path: str = pydantic.Field(
        ..., description="Path of the file relative to the root directory"
    )

    @pydantic.model_validator(mode="after")
    def _validate(self) -> File:
        if self.relative_path.startswith("./"):
            raise ValueError("relative_path should not start with './'")
        if self.relative_path.startswith("/"):
            raise ValueError("relative_path should not start with '/'")
        return self

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, File):
            return False
        return ((self.filesize == other.filesize) and
                (self.md5sum == other.md5sum) and
                (self.relative_path == other.relative_path))

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, File):
            return False
        return self.relative_path < other.relative_path

    def __str__(self) -> str:
        return f"{self.relative_path} S{self.filesize} #{self.md5sum}"

    def __hash__(self) -> int:
        return hash((self.relative_path, self.filesize, self.md5sum))

    def subdirectory(self) -> Optional[str]:
        file_depth = self.relative_path.count("/")
        # depth of 1 means that the file is in the root directory
        if file_depth == 1:
            return None
        else:
            return "/".join((self.relative_path.split("/")[:-1]))


def screen_directory(
    root_directory: str,
    remote_connection: Optional[fabric.connection.Connection] = None,
    max_depth: Optional[int] = None,
) -> Directory:
    command = (
        f"cd {root_directory} && find . -maxdepth " +
        f"{100 if (max_depth is None) else max_depth} -type f -exec sh -c " +
        "'echo \"$(stat -c %s {})  $(md5sum {})\"' \\; && echo '--- done ---'"
    )
    stdout: str
    if remote_connection is None:
        local_result = subprocess.run(["bash", "-c", command],
                                      capture_output=True)
        assert local_result.returncode == 0, f"Failed to list files: {local_result.stderr.decode()}"
        stdout = local_result.stdout.decode().strip(" \t\n")
    else:
        remote_result: Optional[invoke.runners.Result
                               ] = remote_connection.run(command, hide="both")
        assert remote_result is not None, "Failed to list files"
        assert remote_result.ok, f"Failed to list files: {remote_result.stderr}"
        stdout = remote_result.stdout.strip(" \t\n")

    lines = stdout.split("\n")
    assert lines[-1] == "--- done ---", "Command did not finish"
    files: set[File] = set()
    for line in lines[:-1]:
        splitted = line.split("  ")
        assert len(splitted) == 3, f"Unexpected line: {line}"
        filesize = int(splitted[0])
        md5sum = splitted[1]
        relative_path = splitted[2][2 :]
        if relative_path not in [".do-not-touch", "upload-meta.json"]:
            files.add(
                File(
                    filesize=filesize,
                    md5sum=md5sum,
                    relative_path=relative_path
                )
            )

    return Directory(files=sorted(list(files)))


def compare_directory_screens(
    src_dir: Directory, dst_dir: Directory
) -> tuple[set[File], set[File]]:
    """Compare two directory screens and return the differences.
    
    Returns:
        A tuple of two sets (1. files that are in sync, 2. files that are not in sync)
    """

    src_files = set(src_dir.files)
    dst_files = set(dst_dir.files)

    in_sync = src_files.intersection(dst_files)
    not_in_sync = src_files - dst_files

    return in_sync, not_in_sync
