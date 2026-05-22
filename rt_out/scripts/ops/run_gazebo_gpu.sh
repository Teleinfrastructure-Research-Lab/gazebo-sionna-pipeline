#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../../.." && pwd)"
SETUP_SCRIPT="$SCRIPT_DIR/setup_gazebo_env.sh"

if ! command -v gz >/dev/null 2>&1; then
  echo "gz was not found in PATH. Install Gazebo Sim and try again." >&2
  exit 1
fi

if [[ $# -lt 1 ]]; then
  echo "Usage: bash rt_out/scripts/ops/run_gazebo_gpu.sh <world.sdf> [extra gz args...]" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$SETUP_SCRIPT"

exec gz sim -v 4 -r "$@"
