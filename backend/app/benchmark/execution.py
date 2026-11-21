"""Call the reusable case evaluator with a wall-clock limit and resource measurement."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from app.engines.process_env import processor_environment

from .configuration import ASSET_TYPES


class CaseTimeout(RuntimeError):
    pass


def _disk_size(work: Path) -> int:
    size = 0
    for path in work.rglob("*"):
        try:
            if path.is_file() and not path.is_symlink():
                size += path.stat().st_size
        except FileNotFoundError:
            continue
    return size


def evaluate_isolated(work: Path, config: dict) -> dict:
    (work / "config.json").write_text(json.dumps(config, ensure_ascii=False))
    started = time.monotonic()
    deadline = started + config["timeout_seconds"]
    usage = 0
    env = processor_environment(work)
    env.update(OPENBLAS_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1")
    with subprocess.Popen(
        [sys.executable, "-m", "app.benchmark.case_worker", str(work)],
        cwd=Path(__file__).resolve().parents[2], env=env, start_new_session=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ) as process:
        try:
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    raise CaseTimeout("The benchmark case exceeded its wall-clock time limit.")
                usage = max(usage, _disk_size(work))
                time.sleep(.15)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
    if process.returncode:
        raise RuntimeError("The isolated evaluator exited before returning a result.")
    result = json.loads((work / "result.json").read_text())
    result.setdefault("metrics", {}).update({
        "case_seconds": round(time.monotonic() - started, 4),
        "temp_storage_peak_bytes": max(usage, _disk_size(work)),
    })
    return result


def asset_paths(result: dict, work: Path) -> dict[str, Path]:
    assets = {}
    reference = result.get("reference", {})
    pending = [(key, path) for key, path in result.get("artifacts", {}).items()]
    pending.extend((f"reference_{key}", path) for key, path in reference.get("artifacts", {}).items())
    root = work.resolve()
    for label, relative in pending:
        path = (work / relative).resolve()
        if (
            path.is_relative_to(root) and path.suffix in ASSET_TYPES and path.is_file()
            and path.stat().st_size <= 256 * 1024 * 1024 and len(label) < 72
        ):
            assets[label] = path
    return assets
