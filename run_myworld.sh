#!/usr/bin/env bash

# Launch the main simulation world, not the RT-specific extraction world.
# This is the normal Gazebo entry point when you want to interact with the
# scenario itself rather than run the RT-facing export pipeline.

set -euo pipefail

# Resolve the repository root so the script works when launched from anywhere.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"

# Gazebo Sim is the only external runtime dependency this launcher assumes.
if ! command -v gz >/dev/null 2>&1; then
  echo "gz was not found in PATH. Install Gazebo Sim and try again." >&2
  exit 1
fi

# Expose every model subtree the world may reference through model:// URIs.
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

# Forward any extra Gazebo CLI flags, then point Gazebo at the main world file.
exec gz sim "$@" "$PROJECT_ROOT/myworld.sdf"
