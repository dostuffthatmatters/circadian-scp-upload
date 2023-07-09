from __future__ import annotations
from typing import Any
import fabric.connection
import fabric.transfer


class RemoteClient:
    def __init__(self, host: str, username: str, password: str) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.connection = fabric.connection.Connection(
            f"{self.username}@{self.host}",
            connect_kwargs={"password": self.password},
            connect_timeout=5,
        )
        self.transfer_process = fabric.transfer.Transfer(self.connection)

    def __enter__(self) -> RemoteClient:
        self.connection.open()
        assert self.connection.is_connected, "could not open the ssh connection"
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any):
        # TODO: raise the exception correctly
        self.connection.close()
