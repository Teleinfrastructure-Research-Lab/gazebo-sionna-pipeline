# Rigid 200-frame semantic-ablation runbook

## 1. Experiment purpose

This experiment evaluates semantic/material features and raw occupancy features against labeled multi-RX RT rows for 200 rigid-scene frames.

## 2. Execution modes

- Inspect the extracted result tree.
- Rebuild RT labels, object features, raw-occupancy features, and an explicit semantic-ablation evaluation from staged recorded RT and composed artifacts.
- Regenerate upstream rigid frames only when the archived pose inputs and the remaining dynamic/static manifests, source geometry, and other required scene inputs are available.

## 3. Required source inputs

| Source input | Location | Consuming script | Validation |
|---|---|---|---|
| Recorded reference run | `rt_out/experiments/semantic_ablation_200f/run_20260522_143156/semantic_ablation/semantic_ablation_rigid_200f/` | recorded inspection and staged downstream inputs | `test -d` |
| Writable configuration | `<RUN_ROOT>/config/experiment_config.json` | feature builders | `python3 -m json.tool` |
| Staged composed-manifest index and manifests | `<RUN_ROOT>/frames/composed_manifests/` | feature builders | CSV header and `test -f` |
| Staged RT CSV | `<RUN_ROOT>/rt_results/rt_200frames_multi_rx.csv` | label builder | CSV header |
| Canonical Panda/UR5 pose logs | `<REFERENCE_RUN_ROOT>/inputs/poses/` | rigid sampler and pose-frame extraction | file and SHA-256 checks |

`semantic_ablation.zip` includes the two canonical rigid pose logs under this run's `inputs/poses/` directory. They do not by themselves provide the manifests, source geometry, or other scene inputs needed for a complete upstream regeneration.

## 4. Generated artifact chain

| Generated artifact | Producing command | Output path | Consumed by |
|---|---|---|---|
| Labeled RT rows | `build_rt_labels.py --config` | `<RUN_ROOT>/rt_results/rt_200frames_multi_rx_labeled.csv` | feature builders |
| Object features | `build_object_features.py --config` | `<RUN_ROOT>/features/object_features_rt_labels.csv` | raw features |
| Raw occupancy features | `build_raw_occupancy_features.py --config` | `<RUN_ROOT>/features/raw_occupancy_features_rt_labels.csv` | inspection |
| Ablation result CSV | `run_semantic_ablation.py` | `<RUN_ROOT>/results/` | inspection |

## 5. Environment prerequisites

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"; cd "$REPO_ROOT"
python3 --version
python3 rt_out/scripts/rt/build_rt_labels.py --help
python3 rt_out/scripts/features/build_object_features.py --help
python3 rt_out/scripts/features/build_raw_occupancy_features.py --help
python3 rt_out/scripts/experiments/run_semantic_ablation.py --help
df -h "$REPO_ROOT"
```

## 6. Run variables, 7. create the run root, and 8. configuration

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
REFERENCE_RUN_ROOT="$REPO_ROOT/rt_out/experiments/semantic_ablation_200f/run_20260522_143156/semantic_ablation/semantic_ablation_rigid_200f"
RUN_ROOT="$REPO_ROOT/rt_out/experiments/semantic_ablation_rigid_200f/run_example"
SOURCE_CONFIG="$REFERENCE_RUN_ROOT/configs/experiment_config.json"
CONFIG="$RUN_ROOT/config/experiment_config.json"
test -d "$REFERENCE_RUN_ROOT"
test -f "$SOURCE_CONFIG"
mkdir -p "$RUN_ROOT/config" "$RUN_ROOT/frames" "$RUN_ROOT/rt_results"
cp "$SOURCE_CONFIG" "$CONFIG"
python3 - "$CONFIG" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
payload["output_dir"] = "."
path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
python3 -m json.tool "$CONFIG" >/dev/null
python3 - "$CONFIG" "$RUN_ROOT" <<'PY'
import json
import sys
from pathlib import Path
from rt_out.scripts.experiment_paths import resolve_config_output_root

config = Path(sys.argv[1])
expected = Path(sys.argv[2]).resolve()
actual = resolve_config_output_root(config, json.loads(config.read_text())["output_dir"])
assert actual == expected, (actual, expected)
print(actual)
PY
```

`REFERENCE_RUN_ROOT` is read-only. Stage only the recorded downstream inputs needed by the label and feature builders:

```bash
cp -a "$REFERENCE_RUN_ROOT/frames/composed_manifests" "$RUN_ROOT/frames/"
cp "$REFERENCE_RUN_ROOT/rt_results/rt_200frames_multi_rx.csv" "$RUN_ROOT/rt_results/"
```

## 9. Preflight

```bash
set -euo pipefail
test -f "$CONFIG"
test -f "$RUN_ROOT/rt_results/rt_200frames_multi_rx.csv"
test -f "$RUN_ROOT/frames/composed_manifests/composed_manifest_index.csv"
python3 -m json.tool "$CONFIG" >/dev/null
python3 - <<'PY' "$RUN_ROOT/frames/composed_manifests/composed_manifest_index.csv"
import csv, sys
rows=list(csv.DictReader(open(sys.argv[1], newline='')))
assert len(rows)==200 and 'composed_manifest_path' in rows[0]
PY
```

## 10. Smoke workflow

The safe smoke path rebuilds labels from the staged recorded RT CSV:

```bash
python3 rt_out/scripts/rt/build_rt_labels.py --config "$CONFIG"
```

## 11. Complete workflow

1. **Recorded inspection.** Input: `REFERENCE_RUN_ROOT`. Command: `test -f "$REFERENCE_RUN_ROOT/rt_results/rt_200frames_multi_rx.csv"`. It does not write the reference tree.
2. **RT labels.** Input: staged RT CSV. Command: `python3 rt_out/scripts/rt/build_rt_labels.py --config "$CONFIG"`. Output: `"$RUN_ROOT/rt_results/rt_200frames_multi_rx_labeled.csv"` and `rt_label_summary.csv`. Validation: `test -f "$RUN_ROOT/rt_results/rt_200frames_multi_rx_labeled.csv"`.
3. **Object features.** Input: generated labeled CSV and staged composed manifests. Command: `python3 rt_out/scripts/features/build_object_features.py --config "$CONFIG"`. Output: `"$RUN_ROOT/features/object_features_rt_labels.csv"`. Validation: `test -f "$RUN_ROOT/features/object_features_rt_labels.csv"`.
4. **Raw occupancy features.** Input: object features and staged composed mesh paths. Command: `python3 rt_out/scripts/features/build_raw_occupancy_features.py --config "$CONFIG"`. Output: `"$RUN_ROOT/features/raw_occupancy_features_rt_labels.csv"`. Validation: `test -f "$RUN_ROOT/features/raw_occupancy_features_rt_labels.csv"`.
5. **Evaluation.** Input: generated raw-occupancy features. Command:

```bash
python3 rt_out/scripts/experiments/run_semantic_ablation.py \
  --config "$CONFIG" --target y_path_change --feature-mode raw --models logistic
```

Output: a result CSV below `"$RUN_ROOT/results"`. Stop on missing label, feature, or staged composed-manifest input.

## 12. Restart and overwrite behavior

Feature builders expose no overwrite option. Use a fresh `RUN_ROOT`; do not write `REFERENCE_RUN_ROOT`. Label and evaluation outputs are written below the config-owned run root.

## 13. Output inventory

The extracted tree contains 200 Sionna XML files, `rt_200frames_multi_rx.csv`, labeled RT rows, object/raw feature CSVs, and result CSVs.

## 14. Related documentation

- [Actor-aware 200-frame runbook](semantic_ablation_actor_200f_pipeline.md)
- [Recorded comparison](actor_vs_rigid_ablation_comparison.md)
