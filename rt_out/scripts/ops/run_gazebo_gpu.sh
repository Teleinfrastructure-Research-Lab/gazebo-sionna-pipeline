#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../../.." && pwd)"
SETUP_SCRIPT="$SCRIPT_DIR/setup_gazebo_env.sh"

if [[ -z "${PIPELINE_RUN_DIR:-}" ]]; then
  echo "PIPELINE_RUN_DIR must point to an experiment run before Gazebo can start." >&2
  exit 2
fi

if [[ $# -lt 1 ]]; then
  echo "Usage: bash rt_out/scripts/ops/run_gazebo_gpu.sh <world.sdf> [extra gz args...]" >&2
  exit 1
fi

python3 - "$PROJECT_ROOT" "$PIPELINE_RUN_DIR" <<'PY'
import sys
from pathlib import Path

project_root = Path(sys.argv[1])
sys.path.insert(0, str(project_root / "rt_out" / "scripts"))
from experiment_paths import resolve_experiment_root

resolve_experiment_root(sys.argv[2], create=False, require_existing=True)
PY

if ! command -v gz >/dev/null 2>&1; then
  echo "gz was not found in PATH. Install Gazebo Sim and try again." >&2
  exit 1
fi

GAZEBO_LOG_PATH="$(python3 "$PROJECT_ROOT/rt_out/scripts/experiment_paths.py" \
  --experiment-root "$PIPELINE_RUN_DIR" \
  --log-name "gazebo/gazebo_sim.log" \
  --timestamp)"
echo "experiment_root=$(cd -- "$PIPELINE_RUN_DIR" && pwd)"
echo "gazebo_log=$GAZEBO_LOG_PATH"

# shellcheck disable=SC1090
source "$SETUP_SCRIPT"

exec gz sim -v 4 -r "$@" >"$GAZEBO_LOG_PATH" 2>&1
