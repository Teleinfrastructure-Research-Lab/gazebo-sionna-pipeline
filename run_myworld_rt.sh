#!/usr/bin/env bash

# Launch the RT-facing world variant used by the Gazebo-to-Sionna pipeline.
# This world is the one the manifest extraction scripts expect, so researchers
# should use this launcher when generating data for the validated RT flow.

set -euo pipefail

# Resolve the repository root so the script works when launched from anywhere.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
SETUP_SCRIPT="$PROJECT_ROOT/rt_out/scripts/ops/setup_gazebo_env.sh"

# Gazebo Sim is the only external runtime dependency this launcher assumes.
if ! command -v gz >/dev/null 2>&1; then
  echo "gz was not found in PATH. Install Gazebo Sim and try again." >&2
  exit 1
fi

if [[ ! -f "$SETUP_SCRIPT" ]]; then
  echo "Gazebo environment setup script not found: $SETUP_SCRIPT" >&2
  exit 1
fi

# Share the same model resource and GPU rendering setup used by other Gazebo launch helpers.
# shellcheck disable=SC1090
source "$SETUP_SCRIPT"

# Forward any extra Gazebo CLI flags, then point Gazebo at the main world file.
exec gz sim "$@" "$PROJECT_ROOT/myworld_rt.sdf"
