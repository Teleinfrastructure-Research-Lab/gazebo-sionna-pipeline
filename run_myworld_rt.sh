#!/usr/bin/env bash

# Launch the RT-facing world variant used by the Gazebo-to-Sionna pipeline.
# This world is the one the manifest extraction scripts expect, so researchers
# should use this launcher when generating data for the validated RT flow.

set -euo pipefail

# Resolve the repository root so the script works when launched from anywhere.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"

# Gazebo Sim is the only external runtime dependency this launcher assumes.
if ! command -v gz >/dev/null 2>&1; then
  echo "gz was not found in PATH. Install Gazebo Sim and try again." >&2
  exit 1
fi

# Expose every model subtree the RT world may reference through model:// URIs.
RESOURCE_PATHS=(
  "$PROJECT_ROOT/models"
  "$PROJECT_ROOT/models/furniture"
  "$PROJECT_ROOT/models/humans"
  "$PROJECT_ROOT/models/parts"
  "$PROJECT_ROOT/models/robots"
  "$PROJECT_ROOT/models/UAVs"
)

RESOURCE_PATH="$(IFS=:; printf '%s' "${RESOURCE_PATHS[*]}")"
export GZ_SIM_RESOURCE_PATH="${RESOURCE_PATH}${GZ_SIM_RESOURCE_PATH:+:$GZ_SIM_RESOURCE_PATH}"

# Forward any extra Gazebo CLI flags, then point Gazebo at the RT world file.
exec gz sim "$@" "$PROJECT_ROOT/myworld_rt.sdf"
