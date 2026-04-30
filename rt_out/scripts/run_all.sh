#!/usr/bin/env bash

# Record Panda and UR5 pose logs while both scripted robot motion programs run.
# This is the operational data-capture helper that produces the pose logs later
# consumed by the prototype-frame and sampled-frame dynamic pipelines.

set -e

# Resolve common project directories once so every output path is explicit.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
OUT="$ROOT/rt_out"
SCRIPTS="$SCRIPT_DIR"

# Create the pose-log output folders before starting any background logging.
mkdir -p "$OUT/poses/panda" "$OUT/poses/ur5"

echo "Starting pose loggers..."

# Each logger subscribes to a full model pose topic and writes the raw stream to
# disk. Later scripts treat the pose-log sample index as the stable frame ID.
gz topic --echo -t /model/Panda/pose > "$OUT/poses/panda/panda_pose.log" &
PANDA_LOG_PID=$!

gz topic --echo -t /model/ur5_rg2/pose > "$OUT/poses/ur5/ur5_pose.log" &
UR5_LOG_PID=$!

cleanup() {
    # Always stop the background loggers, even if one motion script fails.
    echo "Stopping loggers..."
    kill $PANDA_LOG_PID 2>/dev/null || true
    kill $UR5_LOG_PID 2>/dev/null || true
}
trap cleanup EXIT

# Give the subscribers a moment to attach before the robots start moving.
sleep 2

echo "Starting Panda and UR5 scripts..."

# Run both robot motion scripts concurrently so the logs capture the same time
# window and can later be compared on a common source-sample axis.
bash "$SCRIPTS/run_panda.sh" &
PANDA_PID=$!

bash "$SCRIPTS/run_ur5.sh" &
UR5_PID=$!

wait $PANDA_PID
wait $UR5_PID

echo "Robot scripts finished."
# Leave a short tail so the final commanded poses are likely flushed to disk.
sleep 1
