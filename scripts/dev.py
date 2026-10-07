"""Cross-platform development command runner with verification receipts."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = REPO_ROOT / ".artifacts" / "verification" / "latest.json"


def capture(*command: str) -> str:
    if command[0] == "git":
        command = ("git", "-c", f"safe.directory={REPO_ROOT.as_posix()}", *command[1:])
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def git_metadata() -> dict[str, Any]:
    if not (REPO_ROOT / ".git").exists():
        return {
            "repository": "dfs-field-model",
            "branch": None,
            "commit": None,
            "dirty": None,
            "changed_file_count": None,
        }
    status = capture("git", "status", "--porcelain", "--untracked-files=all")
    return {
        "repository": "dfs-field-model",
        "branch": capture("git", "branch", "--show-current"),
        "commit": capture("git", "rev-parse", "HEAD"),
        "dirty": bool(status and status != "unknown"),
        "changed_file_count": len(status.splitlines()) if status != "unknown" else None,
    }


def commands() -> dict[str, list[str]]:
    return {
        "diff": (
            ["git", "-c", f"safe.directory={REPO_ROOT.as_posix()}", "diff", "--check"]
            if (REPO_ROOT / ".git").exists()
            else [sys.executable, "-c", "print('Release ZIP: Git diff check skipped')"]
        ),
        "lint": [sys.executable, "-m", "ruff", "check", "."],
        "test": [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--basetemp",
            str(REPO_ROOT / ".tmp" / "pytest"),
        ],
        "demo": [sys.executable, "demo_field.py"],
        "app": [sys.executable, "-m", "streamlit", "run", "app.py"],
    }


def run_step(name: str, command: list[str]) -> dict[str, Any]:
    print(f"\n== {name} ==", flush=True)
    started = time.perf_counter()
    result = subprocess.run(command, cwd=REPO_ROOT, check=False)
    return {
        "name": name,
        "status": "passed" if result.returncode == 0 else "failed",
        "exit_code": result.returncode,
        "duration_seconds": round(time.perf_counter() - started, 3),
    }


def write_receipt(steps: list[dict[str, Any]], passed: bool) -> None:
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        **git_metadata(),
        "platform": platform.system(),
        "python": platform.python_version(),
        "status": "passed" if passed else "failed",
        "steps": steps,
    }
    ARTIFACT.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


def doctor(as_json: bool) -> int:
    report = {
        **git_metadata(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "git": capture("git", "--version"),
        "verification_receipt_exists": ARTIFACT.is_file(),
    }
    if as_json:
        print(json.dumps(report, indent=2))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0


def check() -> int:
    (REPO_ROOT / ".tmp").mkdir(exist_ok=True)
    results: list[dict[str, Any]] = []
    for name in ("diff", "lint", "test", "demo"):
        result = run_step(name, commands()[name])
        results.append(result)
        if result["exit_code"] != 0:
            write_receipt(results, passed=False)
            print(f"\nCHECK FAILED: {name}", file=sys.stderr)
            return int(result["exit_code"])
    write_receipt(results, passed=True)
    print(f"\nCHECK PASSED; receipt: {ARTIFACT.relative_to(REPO_ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("doctor", "lint", "test", "demo", "check", "app")
    )
    parser.add_argument("--json", action="store_true", help="JSON output for doctor")
    args = parser.parse_args()

    if args.command == "doctor":
        return doctor(args.json)
    if args.command == "check":
        return check()
    if args.command == "test":
        (REPO_ROOT / ".tmp").mkdir(exist_ok=True)
    return int(run_step(args.command, commands()[args.command])["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
