#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${SCRIPT_DIR}/capture_synchronized_stable_instance_rgb_pcl_topics.cpp"
OUT="${SCRIPT_DIR}/capture_synchronized_stable_instance_rgb_pcl_topics"

PKG_FLAGS="$(pkg-config --cflags --libs gz-transport gz-msgs)"
CXXFLAGS=(-O2 -std=c++17 -Wall -Wextra -pedantic)
DEFINES=()
EXTRA_FLAGS=()

if command -v g++ >/dev/null 2>&1; then
  COMPILER=(g++)
elif command -v clang++ >/dev/null 2>&1; then
  COMPILER=(clang++)
elif command -v gcc >/dev/null 2>&1; then
  if ! printf 'int main(){return 0;}\n' | gcc -x c++ -E - >/dev/null 2>&1; then
    echo "gcc is present, but the C++ frontend (cc1plus) is missing. Install g++ or clang++." >&2
    exit 1
  fi
  COMPILER=(gcc -x c++)
  EXTRA_FLAGS+=(-lstdc++)
else
  echo "No suitable C++ compiler found (g++, clang++, or gcc)." >&2
  exit 1
fi

if pkg-config --exists opencv4; then
  DEFINES+=(-DHAVE_OPENCV4)
  # shellcheck disable=SC2206
  EXTRA_FLAGS+=($(pkg-config --cflags --libs opencv4))
fi

"${COMPILER[@]}" "${CXXFLAGS[@]}" "${DEFINES[@]}" "${SRC}" -o "${OUT}" ${PKG_FLAGS} "${EXTRA_FLAGS[@]}"
echo "${OUT}"
