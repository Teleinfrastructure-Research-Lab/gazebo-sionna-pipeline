#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
OUT="$ROOT/rt_out"
SCRIPTS="$SCRIPT_DIR"

mkdir -p "$OUT/poses/panda" "$OUT/poses/ur5"

echo "Starting pose loggers..."

gz topic --echo -t /model/Panda/pose > "$OUT/poses/panda/panda_pose.log" &
PANDA_LOG_PID=$!

gz topic --echo -t /model/ur5_rg2/pose > "$OUT/poses/ur5/ur5_pose.log" &
UR5_LOG_PID=$!

cleanup() {
    echo "Stopping loggers..."
    kill $PANDA_LOG_PID 2>/dev/null || true
    kill $UR5_LOG_PID 2>/dev/null || true
}
trap cleanup EXIT

sleep 2

echo "Starting Panda and UR5 scripts..."

bash "$SCRIPTS/run_panda.sh" &
PANDA_PID=$!

bash "$SCRIPTS/run_ur5.sh" &
UR5_PID=$!

wait $PANDA_PID
wait $UR5_PID

echo "Robot scripts finished."
sleep 1
