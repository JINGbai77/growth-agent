import os
from pathlib import Path


class ProcessLease:
    """OS-held lock released on crash; one scheduler may own a SQLite database."""

    def __init__(self, database_path: str):
        path = Path(database_path).resolve().with_suffix(".scheduler.lock")
        self.stream = path.open("a+b")
        self.stream.seek(0)
        self.stream.write(b"1")
        self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.stream.close()
            raise RuntimeError(
                "Database already owned by another scheduler; use one API process"
            ) from exc

    def close(self):
        if self.stream.closed:
            return
        if os.name == "nt":
            import msvcrt

            self.stream.seek(0)
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        self.stream.close()
