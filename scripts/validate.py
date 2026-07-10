"""Run the repository's complete offline validation surface."""

from __future__ import annotations

import subprocess
import sys

COMMANDS = (
    [sys.executable, "-m", "pip", "check"],
    [sys.executable, "-m", "ruff", "format", "--check", "core/resumes", "tests", "scripts"],
    [sys.executable, "-m", "ruff", "check", "--select", "E9,F401,F63,F7,F82", "."],
    [sys.executable, "-m", "ruff", "check", "core/resumes", "tests", "scripts"],
    [sys.executable, "-m", "mypy"],
    [sys.executable, "-m", "pytest"],
    [sys.executable, "-m", "scripts.run_evals"],
    [sys.executable, "-m", "compileall", "-q", "app_tkinter.py", "core", "run.py"],
)


def main() -> int:
    for command in COMMANDS:
        print("+", " ".join(command), flush=True)
        completed = subprocess.run(command, check=False)
        if completed.returncode:
            return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
