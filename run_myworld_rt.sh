#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"

if ! command -v gz >/dev/null 2>&1; then
  echo "gz was not found in PATH. Install Gazebo Sim and try again." >&2
  exit 1
fi

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

exec gz sim "$@" "$PROJECT_ROOT/myworld_rt.sdf"
