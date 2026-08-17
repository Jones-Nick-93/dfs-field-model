#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"

command_name=${1:-doctor}
if [ "$#" -gt 0 ]; then
  shift
fi

if [ "$command_name" = "setup" ]; then
  command -v uv >/dev/null 2>&1 || {
    echo "uv is required. Install it, reopen the shell, then rerun 'sh scripts/dev.sh setup'." >&2
    exit 1
  }
  exec uv sync --extra dev --python 3.12
fi

python_path="$repo_root/.venv/bin/python"
if [ ! -x "$python_path" ]; then
  echo "Missing .venv. Run 'sh scripts/dev.sh setup' first." >&2
  exit 1
fi

exec "$python_path" "$repo_root/scripts/dev.py" "$command_name" "$@"
