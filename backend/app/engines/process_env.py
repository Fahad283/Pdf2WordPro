"""Minimal environment for third-party PDF, OCR, and Word processors."""

import os
from pathlib import Path

FORWARDED = (
    "PATH",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TESSDATA_PREFIX",
    "FONTCONFIG_PATH",
    "FONTCONFIG_FILE",
    "TMPDIR",
    "HOME",
    "XDG_CACHE_HOME",
    "DYLD_LIBRARY_PATH",
    "LD_LIBRARY_PATH",
    "SYSTEMROOT",
    "WINDIR",
)


def processor_environment(workspace: Path | None = None) -> dict[str, str]:
    environment = {name: os.environ[name] for name in FORWARDED if name in os.environ}
    if workspace is not None:
        environment.update(HOME=str(workspace), TMPDIR=str(workspace), XDG_CACHE_HOME=str(workspace / "cache"))
    environment["OMP_THREAD_LIMIT"] = "1"
    return environment
