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

    def get_subdirectories(self) -> list[str]:
        subdirs: set[str] = []
        for file in self.files:
            subdir = file.subdirectory()
            if subdir is not None:
                tmp_sd = subdir
                subdirs.add(tmp_sd)
                while "/" in tmp_sd:
                    tmp_sd = "/".join(tmp_sd.split("/")[:-1])
                    subdirs.add(tmp_sd)

        # sorting alphabetically will also put the parent directories first
        return sorted(list(subdirs))


class File(pydantic.BaseModel):
    filesize: int = pydantic.Field(..., description="Size of the file in bytes")
    md5sum: str = pydantic.Field(..., description="MD5 checksum of the file")
    relative_path: str = pydantic.Field(
        ...,
        description="Path of the file relative to the root directory",
        pattern=r"\./.*"
    )

    def __eq__(self, other: File) -> bool:
        return ((self.filesize == other.filesize) and
                (self.md5sum == other.md5sum) and
                (self.relative_path == other.relative_path))

    def __str__(self) -> str:
        return f"{self.relative_path} S{self.filesize} #{self.md5sum}"

    def subdirectory(self) -> Optional[str]:
        file_depth = self.relative_path.count("/")
        # depth of 1 means that the file is in the root directory
        if file_depth == 1:
            return None
        else:
            return "/".join((self.relative_path[2 :].split("/")[:-1]))


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
                               ] = remote_connection.run(command)
        assert remote_result is not None, "Failed to list files"
        assert remote_result.ok, f"Failed to list files: {remote_result.stderr}"
        stdout = remote_result.stdout.strip(" \t\n")

    lines = [l for l in stdout.split("\n") if ".do-not-touch" not in l]
    assert lines[-1] == "--- done ---", "Command did not finish"
    files: set[File] = set()
    for line in lines[:-1]:
        splitted = line.split("  ")
        assert len(splitted) == 3, f"Unexpected line: {line}"
        filesize = int(splitted[0])
        md5sum = splitted[1]
        relative_path = splitted[2]
        files.add(
            File(filesize=filesize, md5sum=md5sum, relative_path=relative_path)
        )

    return Directory(files=sorted(list(files)))
