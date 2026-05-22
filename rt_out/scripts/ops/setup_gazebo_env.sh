#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../../.." && pwd)"

RESOURCE_PATHS=(
  "$PROJECT_ROOT/models"
  "$PROJECT_ROOT/models/furniture"
  "$PROJECT_ROOT/models/humans"
  "$PROJECT_ROOT/models/parts"
  "$PROJECT_ROOT/models/robots"
  "$PROJECT_ROOT/models/UAVs"
)

join_unique_paths() {
  local existing="${1:-}"
  shift || true
  local -a candidates=("$@")
  local -a pieces=()
  local -A seen=()
  local path=""

  for path in "${candidates[@]}"; do
    if [[ -d "$path" && -z "${seen[$path]+x}" ]]; then
      pieces+=("$path")
      seen["$path"]=1
    fi
  done

  if [[ -n "$existing" ]]; then
    local old_ifs="$IFS"
    IFS=':'
    read -r -a existing_parts <<< "$existing"
    IFS="$old_ifs"
    for path in "${existing_parts[@]}"; do
      if [[ -n "$path" && -z "${seen[$path]+x}" ]]; then
        pieces+=("$path")
        seen["$path"]=1
      fi
    done
  fi

  local joined=""
  for path in "${pieces[@]}"; do
    if [[ -z "$joined" ]]; then
      joined="$path"
    else
      joined="$joined:$path"
    fi
  done
  printf '%s\n' "$joined"
}

export GZ_SIM_RESOURCE_PATH="$(join_unique_paths "${GZ_SIM_RESOURCE_PATH-}" "${RESOURCE_PATHS[@]}")"
export IGN_GAZEBO_RESOURCE_PATH="$(join_unique_paths "${IGN_GAZEBO_RESOURCE_PATH-}" "${RESOURCE_PATHS[@]}")"

export __NV_PRIME_RENDER_OFFLOAD=1
export __GLX_VENDOR_LIBRARY_NAME=nvidia
export __VK_LAYER_NV_optimus=NVIDIA_only

unset LIBGL_ALWAYS_SOFTWARE || true
unset MESA_LOADER_DRIVER_OVERRIDE || true
