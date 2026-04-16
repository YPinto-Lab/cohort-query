from datetime import datetime
from pathlib import Path
from typing import Optional


class Logger:
    def __init__(self, log_file_path: Path, echo_default: bool = False):
        self.log_file_path = log_file_path
        self.echo_default = echo_default

    def log(self, message: str, echo: Optional[bool] = None) -> None:
        should_echo = self.echo_default if echo is None else echo
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {message}"
        if should_echo:
            print(line)
        with self.log_file_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")