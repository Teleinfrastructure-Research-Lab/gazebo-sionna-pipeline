#!/usr/bin/env bash

# Record Panda and UR5 pose logs while both scripted robot motion programs run.
# This is the operational data-capture helper that produces the pose logs later
# consumed by the prototype-frame and sampled-frame dynamic pipelines.

set -e

# Resolve common project directories once so every output path is explicit.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
RUN_DIR="${PIPELINE_RUN_DIR:-}"
if [ -z "$RUN_DIR" ]; then
  echo "ERROR: set PIPELINE_RUN_DIR to an experiment run directory before recording pose logs." >&2
  exit 2
fi
OUT="$RUN_DIR"
SCRIPTS="$SCRIPT_DIR"

# Allocate non-overwriting run-local log paths through the shared Python path
# utility. The utility creates <run>/logs only because this script needs it.
PANDA_LOG_PATH="$(python3 "$ROOT/rt_out/scripts/experiment_paths.py" \
  --experiment-root "$OUT" --log-name "ops/panda_pose.log" --timestamp)"
UR5_LOG_PATH="$(python3 "$ROOT/rt_out/scripts/experiment_paths.py" \
  --experiment-root "$OUT" --log-name "ops/ur5_pose.log" --timestamp)"

echo "experiment_root=$(cd "$OUT" && pwd)"
echo "panda_log=$PANDA_LOG_PATH"
echo "ur5_log=$UR5_LOG_PATH"
echo "Starting pose loggers..."

# Each logger subscribes to a full model pose topic and writes the raw stream to
# disk. Later scripts treat the pose-log sample index as the stable frame ID.
gz topic --echo -t /model/Panda/pose > "$PANDA_LOG_PATH" &
PANDA_LOG_PID=$!

gz topic --echo -t /model/ur5_rg2/pose > "$UR5_LOG_PATH" &
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
