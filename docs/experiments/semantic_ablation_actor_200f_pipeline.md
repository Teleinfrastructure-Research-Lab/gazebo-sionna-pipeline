# Actor-aware 200-frame semantic-ablation runbook

## 1. Experiment purpose

This workflow adds actor sampling and actor mesh export to the 200-frame rigid-scene chain before composition, RT, labels, features, and evaluation.

## 2. Execution modes

- Inspect recorded actor-aware outputs.
- Rebuild RT labels, feature tables, and semantic-ablation evaluation from staged recorded RT and composed artifacts.
- Run actor-aware upstream stages only when the archived pose inputs and the remaining scene inputs, actor manifest, and actor assets are available.

## 3. Required source inputs

| Source input | Location | Consuming script | Validation |
|---|---|---|---|
| Recorded actor run | `rt_out/experiments/semantic_ablation_200f/run_20260522_143156/semantic_ablation/semantic_ablation_actor_200f/` | recorded inspection and staged downstream inputs | `test -d` |
| Writable configuration | `<RUN_ROOT>/config/experiment_config.json` | feature builders | JSON parse |
| Staged composed manifests and RT CSV | `<RUN_ROOT>/frames/composed_manifests/`, `<RUN_ROOT>/rt_results/` | label and feature builders | file and CSV checks |
| Canonical rigid pose logs | `<REFERENCE_RUN_ROOT>/inputs/poses/` | sampler and rigid pose frames | file and SHA-256 checks |

`semantic_ablation.zip` includes the two canonical rigid pose logs under this run's `inputs/poses/` directory. The actor manifest/assets, scene manifests, and source geometry remain separate required inputs for upstream regeneration.

## 4. Generated artifact chain

`sampled frames -> rigid pose frames -> actor frame samples -> rigid and actor mesh export -> composition -> XML -> RT -> labels -> features -> evaluation`.

| Generated artifact | Producing command | Output path | Consumed by |
|---|---|---|---|
| Actor frame samples | `build_experiment_actor_frame_samples.py --config` | `frames/actor_frame_samples.json` | actor export |
| Dynamic/actor mesh indexes | `export_dynamic_meshes_batch.py --include-actors` | `frames/dynamic_meshes/`, `frames/actor_meshes/` | composition |
| Composed/XML indexes | composition/XML batch scripts | `frames/composed_manifests/`, `sionna_xml/` | RT |
| Labeled RT rows, feature tables, and evaluation CSV | label, feature, and evaluation scripts | `<RUN_ROOT>/rt_results/`, `<RUN_ROOT>/features/`, `<RUN_ROOT>/results/` | inspection |

## 5. Environment prerequisites

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"; cd "$REPO_ROOT"
python3 --version; test -d models
python3 rt_out/scripts/dynamic_actor/build_experiment_actor_frame_samples.py --help
python3 rt_out/scripts/dynamic/export_dynamic_meshes_batch.py --help
python3 rt_out/scripts/composition/compose_frame_manifests_batch.py --help
python3 rt_out/scripts/rt/build_sionna_xml_batch.py --help
python3 rt_out/scripts/rt/run_rt_multi_rx_batch.py --help
```

Blender is required for mesh export; Sionna RT/Mitsuba is required for RT. Check them before a heavy stage with `command -v blender` and `${SIONNA_PYTHON:-python3} -c 'import sionna.rt, mitsuba'`.

## 6. Run variables, 7. create the run root, and 8. configuration

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
REFERENCE_RUN_ROOT="$REPO_ROOT/rt_out/experiments/semantic_ablation_200f/run_20260522_143156/semantic_ablation/semantic_ablation_actor_200f"
RUN_ROOT="$REPO_ROOT/rt_out/experiments/semantic_ablation_actor_200f/run_example"
SOURCE_CONFIG="$REFERENCE_RUN_ROOT/configs/experiment_config.json"
CONFIG="$RUN_ROOT/config/experiment_config.json"
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
assert resolve_config_output_root(config, json.loads(config.read_text())["output_dir"]) == expected
PY
cp -a "$REFERENCE_RUN_ROOT/frames/composed_manifests" "$RUN_ROOT/frames/"
cp "$REFERENCE_RUN_ROOT/rt_results/rt_200frames_multi_rx.csv" "$RUN_ROOT/rt_results/"
```

`REFERENCE_RUN_ROOT` remains read-only. A copied configuration alone is insufficient for an upstream actor-aware run: copy the archived pose inputs as well, and supply the remaining manifests, source geometry, actor manifest, and actor assets.

## 9. Preflight

```bash
set -euo pipefail
test -f "$CONFIG"
test -f "$RUN_ROOT/frames/composed_manifests/composed_manifest_index.csv"
test -f "$RUN_ROOT/rt_results/rt_200frames_multi_rx.csv"
python3 -m json.tool "$CONFIG" >/dev/null
```

## 10. Smoke workflow

```bash
python3 rt_out/scripts/rt/build_rt_labels.py --config "$CONFIG"
```

This writes `rt_results/rt_200frames_multi_rx_labeled.csv` below the writable `RUN_ROOT` from the staged recorded RT CSV.

## 11. Complete workflow

The full actor-aware dependency order is:

`sampled frames -> rigid pose frames -> actor frame samples -> rigid mesh export -> actor mesh export -> composition -> XML -> RT -> labels -> features -> evaluation`.

The extracted archive supports the writable downstream chain: `recorded RT -> RT labels -> object features -> raw occupancy features -> semantic-ablation evaluation`. It now includes canonical rigid pose inputs, but upstream frame and geometry regeneration still requires the remaining dynamic/static manifests, source geometry, actor manifest, and actor assets. For a complete source set, use a defined and validated dynamic manifest:

```bash
DYNAMIC_MANIFEST="$RUN_ROOT/manifests/dynamic_manifest.json"
test -f "$DYNAMIC_MANIFEST"
python3 rt_out/scripts/dynamic_rigid/sample_experiment_frames.py --config "$CONFIG" --dynamic-manifest "$DYNAMIC_MANIFEST"
python3 rt_out/scripts/dynamic_rigid/build_dynamic_pose_frames.py --experiment-root "$RUN_ROOT"
python3 rt_out/scripts/dynamic_rigid/resolve_dynamic_visual_frames.py --experiment-root "$RUN_ROOT" --models-root "$REPO_ROOT/models"
python3 rt_out/scripts/dynamic_actor/build_experiment_actor_frame_samples.py --config "$CONFIG"
python3 rt_out/scripts/dynamic/export_dynamic_meshes_batch.py --config "$CONFIG" --include-actors --blender "${BLENDER:-blender}"
python3 rt_out/scripts/composition/compose_frame_manifests_batch.py --config "$CONFIG" --include-actors
python3 rt_out/scripts/rt/build_sionna_xml_batch.py --config "$CONFIG"
python3 rt_out/scripts/rt/run_rt_multi_rx_batch.py --config "$CONFIG" --sionna-python "${SIONNA_PYTHON:-python3}"
python3 rt_out/scripts/rt/build_rt_labels.py --config "$CONFIG"
python3 rt_out/scripts/features/build_object_features.py --config "$CONFIG"
python3 rt_out/scripts/features/build_raw_occupancy_features.py --config "$CONFIG"
```

Validate each generated index/CSV with `test -f` before starting the next command. With the available archive, stop before the sampler; do not treat the defined `DYNAMIC_MANIFEST` example as an available public input.

For the supported writable downstream path, run:

```bash
python3 rt_out/scripts/rt/build_rt_labels.py --config "$CONFIG"
python3 rt_out/scripts/features/build_object_features.py --config "$CONFIG"
python3 rt_out/scripts/features/build_raw_occupancy_features.py --config "$CONFIG"
python3 rt_out/scripts/experiments/run_semantic_ablation.py \
  --config "$CONFIG" --target y_path_change --feature-mode raw --models logistic
```

Each command resolves `output_dir: "."` from `"$RUN_ROOT/config/experiment_config.json"`, so its generated labels, features, and evaluation CSV stay below `RUN_ROOT`.

## 12. Restart and overwrite behavior

Batch mesh/XML/RT stages are heavy and may write run-local indexes. Use a fresh `RUN_ROOT` for regeneration. Normal 200-frame label generation writes the labeled CSV and summary CSV. `build_rt_labels.py --validate-only` is supported only for the canonical 2,446-frame one-second mode: `--horizon-frames 10 --one-second-split --validate-only`. Feature builders have no dry-run option.

## 13. Output inventory

The extracted run contains 200 XML files, actor mesh manifests/indexes, labeled RT rows, object/raw feature CSVs, timeline artifacts, and evaluation results.

## 14. Troubleshooting

- Actor export fails: validate `frames/actor_frame_samples.json` and actor configuration fields.
- Composition fails: validate dynamic and actor index paths below `RUN_ROOT`.
- Upstream frame stage fails: the required source pose logs are not in the archive.

## 15. Related documentation

- [Rigid 200-frame runbook](semantic_ablation_200f_pipeline.md)
- [Recorded comparison](actor_vs_rigid_ablation_comparison.md)
