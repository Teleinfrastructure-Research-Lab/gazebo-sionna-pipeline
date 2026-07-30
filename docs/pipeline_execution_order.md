# Complete pipeline execution sequence

This guide lists the commands in the order in which they are executed. It
starts from an existing Gazebo scene and ends with generated point clouds and
Sionna RT results. Run every command from the repository root.

The current repository version has two important limitations: the static
registry builders retain an old default run path, and the 2,446-frame GT
point-cloud producer is represented by a smoke script rather than a generic
full-run CLI. The affected stages describe these limits; no replacement
commands are invented here.

## Stage 0 — environment and prerequisites

**Purpose**

Select the tools without launching a scientific workload and allocate a unique
run directory.

**Required before starting**

Python 3 with `numpy`; Blender; Gazebo Sim/`gz`; Sionna RT with Mitsuba; and,
for perception capture, a C++17 compiler, `pkg-config`, `gz-transport`, and
`gz-msgs`. Optional feature/training stages require their own Python packages.
The repository has no pinned lockfile or complete environment manifest.

**Command**

```bash
REPO_ROOT="$(pwd)"
EXPERIMENT_NAME="<experiment_name>"
RUN_ID="run_$(date +%Y%m%d_%H%M%S)"
RUN_ROOT="$REPO_ROOT/rt_out/experiments/$EXPERIMENT_NAME/$RUN_ID"
SIONNA_PYTHON="<path-to-sionna-python>"
BLENDER="<path-to-blender>"

export PIPELINE_RUN_DIR="$RUN_ROOT"
export SIONNA_PYTHON BLENDER
source rt_out/scripts/ops/setup_gazebo_env.sh
mkdir -p "$RUN_ROOT"/{config,manifests,frames,geometry,sionna_xml,rt_results,gt_scene_pointclouds,features,reports,logs}

python3 --version
python3 -c 'import numpy; print("numpy", numpy.__version__)'
"$SIONNA_PYTHON" -c 'import sionna.rt, mitsuba as mi; print("mitsuba", mi.variant())'
"$BLENDER" --version | head -n 1
gz sim --help >/dev/null
```

**Main options**

`PIPELINE_RUN_DIR` is required by the Gazebo/pose helpers. `SIONNA_PYTHON` is
the preferred RT interpreter; `COLLABPAPER_PYTHON` remains a legacy fallback.
`BLENDER` can be replaced by per-command `--blender` where supported.

**Input**

Installed tools and this repository.

**Output**

An empty unique run directory and no scientific outputs.

**Check**

The imports and `--help` checks must succeed. A missing optional package blocks
only the branch that needs it.

**Continuing after interruption**

Run allocation never reuses an existing run ID. Do not point a new experiment
at a completed run.

**Common problem**

Importing Sionna with the system Python, missing Gazebo resources, or setting
`PIPELINE_RUN_DIR` to `rt_out`/`current_experiment`.

## Stage 1 — Gazebo scene preparation checklist

**Purpose**

Confirm that the completed scene contains the inputs expected by extraction and
motion capture.

**Required before starting**

The scene has already been authored in Gazebo.

**Command**

```bash
test -f myworld_rt.sdf
test -d models
python3 -m json.tool rt_out/materials/material_map.json >/dev/null
```

**Main options**

The RT world is `myworld_rt.sdf`; the general world is `myworld.sdf`. The
intended scene must contain static objects, Panda and `ur5_rg2` articulated
models, and actor declarations when the actor branch is selected. Model mesh
URIs must resolve under `models/`.

**Input**

World/SDF, model/config/mesh assets, static material naming, actor assets if
used, and the resolved TX/RX experiment configuration. TX/RX are not inferred
from the SDF by the RT runner.

**Output**

No generated files.

**Check**

Check model names, actor name `actor_walking` when applicable, semantic/material
mapping rules, and TX/RX IDs before extraction.

**Continuing after interruption**

This is a preflight checklist. A changed scene requires a new run or a
deliberately invalidated downstream run.

**Common problem**

`model://` assets cannot be resolved, an expected robot/actor is absent, or a
material name has no RT mapping.

## Stage 2 — run creation and configuration used by the run

**Purpose**

Put all generated output and the input files used by the run under one run root.

**Required before starting**

Stage 0 and user-provided experiment config templates.

**Command**

```bash
mkdir -p "$RUN_ROOT/config"
cp <source-experiment-config.json> "$RUN_ROOT/config/experiment_config.json"
cp <source-dynamic-prototype-config.json> "$RUN_ROOT/config/dynamic_prototype_config.json"
cp <source-rt-material-config.json> "$RUN_ROOT/config/rt_material_mapping.json"
cp <source-actor-config.json> "$RUN_ROOT/config/actor_dynamic_config.json"
python3 -m json.tool "$RUN_ROOT/config/experiment_config.json" >/dev/null
```

The batch scripts resolve the config's `output_dir` relative to the repository.
It must therefore be the repository-relative run path, for example
`rt_out/experiments/<experiment_name>/<run_id>`, not `.`. The current validated
2,446-frame config uses `output_dir: "."` because it was executed in a
specialized wrapper; do not reuse that value for a new generic batch run.

**Main options**

Use `--experiment-root` only on scripts that expose it. `experiment_paths.py`
provides validation and unique log names but there is no generic run-creation
CLI.

**Input**

Experiment config, dynamic prototype config, RT material config, optional actor
config, and chosen frozen pose logs.

**Output**

Run-local resolved JSON files and an explicit run identity.

**Check**

Confirm `experiment_name`, frame count, TX/RX order, `output_dir`, and all
referenced files before any stage writes data.

**Continuing after interruption**

Do not alter the config used by the run after a later generated file exists.
Create a new run for a changed experiment definition.

**Common problem**

Batch scripts write to repository root because `output_dir` is `.` or two
experiments share the same output root.

## Stage 3 — launch Gazebo and record motion inputs

**Purpose**

Capture synchronized Panda and UR5 pose streams, or explicitly reuse frozen
pose logs.

**Required before starting**

Stage 1, `PIPELINE_RUN_DIR`, and a running `myworld_rt.sdf` world.

**Command**

Terminal A:

```bash
source rt_out/scripts/ops/setup_gazebo_env.sh
bash rt_out/scripts/ops/run_gazebo_gpu.sh myworld_rt.sdf
```

Terminal B:

```bash
export PIPELINE_RUN_DIR="$RUN_ROOT"
bash rt_out/scripts/ops/run_all.sh
```

The helper subscribes to `/model/Panda/pose` and `/model/ur5_rg2/pose`, starts
`run_panda.sh` and `run_ur5.sh`, and stops both subscriptions on exit.

**Main options**

`run_gazebo_gpu.sh` takes `<world.sdf> [extra gz args...]`. The pose scripts
take no positional arguments and require `PIPELINE_RUN_DIR`.

**Input**

Running Gazebo world, robot models, and scripted joint motion.

**Output**

`run_all.sh` creates unique run-local
`logs/ops/panda_pose_<timestamp>.log` and
`logs/ops/ur5_pose_<timestamp>.log` files. These timestamped capture files are
not the paths consumed by the dynamic frame builder until they are frozen and
bound below.

**Check**

Check that both logs are non-empty, have the expected `pose { ... }` records,
and cover the same motion window. The prototype config expects 12 Panda links
and 11 UR5 links. Validate sample indices before frame construction.

**Freeze and bind the pose inputs**

Identify the newest logs from this capture, copy them to stable run-local input
paths, and bind those exact files in the run-local dynamic configuration:

```bash
PANDA_CAPTURED_LOG="$(find "$RUN_ROOT/logs/ops" -maxdepth 1 -type f -name 'panda_pose_*.log' -printf '%T@ %p\n' | sort -nr | head -n 1 | cut -d' ' -f2-)"
UR5_CAPTURED_LOG="$(find "$RUN_ROOT/logs/ops" -maxdepth 1 -type f -name 'ur5_pose_*.log' -printf '%T@ %p\n' | sort -nr | head -n 1 | cut -d' ' -f2-)"
test -s "$PANDA_CAPTURED_LOG"
test -s "$UR5_CAPTURED_LOG"
mkdir -p "$RUN_ROOT/inputs/poses"
cp -- "$PANDA_CAPTURED_LOG" "$RUN_ROOT/inputs/poses/panda_pose.log"
cp -- "$UR5_CAPTURED_LOG" "$RUN_ROOT/inputs/poses/ur5_pose.log"

case "$RUN_ROOT" in
  "$REPO_ROOT"/*) RUN_ROOT_REL="${RUN_ROOT#"$REPO_ROOT"/}" ;;
  *) echo "RUN_ROOT must be below REPO_ROOT for repository-relative pose_log fields" >&2; exit 2 ;;
esac
```

There is no supported automatic updater for these JSON fields. Edit only the
following existing fields in
`$RUN_ROOT/config/dynamic_prototype_config.json`:

```json
{
  "dynamic_models": {
    "Panda": {
      "pose_log": "rt_out/experiments/<experiment_name>/<run_id>/inputs/poses/panda_pose.log"
    },
    "ur5_rg2": {
      "pose_log": "rt_out/experiments/<experiment_name>/<run_id>/inputs/poses/ur5_pose.log"
    }
  }
}
```

Replace the two placeholder paths with `$RUN_ROOT_REL/inputs/poses/...`.
The exact implementation fields are `dynamic_models.Panda.pose_log` and
`dynamic_models.ur5_rg2.pose_log`; do not invent `pose_log_path`.
The loader resolves these repository-relative values from `REPO_ROOT`.

Validate the binding before Stage 5:

```bash
python3 - "$REPO_ROOT" "$RUN_ROOT" "$RUN_ROOT/config/dynamic_prototype_config.json" <<'PY'
import json
import sys
from pathlib import Path

repo_root = Path(sys.argv[1]).resolve()
run_root = Path(sys.argv[2]).resolve()
config = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
expected = {
    "Panda": run_root / "inputs/poses/panda_pose.log",
    "ur5_rg2": run_root / "inputs/poses/ur5_pose.log",
}
for model, expected_path in expected.items():
    raw = config["dynamic_models"][model]["pose_log"]
    resolved = Path(raw).expanduser()
    if not resolved.is_absolute():
        resolved = repo_root / resolved
    assert resolved.resolve() == expected_path.resolve(), (model, raw, resolved)
    assert expected_path.is_file() and expected_path.stat().st_size > 0, expected_path
print("pose_log_binding=PASS")
PY
```

The copied files and the two `pose_log` values are the exact pose inputs used
by Stage 5. The generated `dynamic_frames.json` also records the resolved
paths under `dynamic_pose_logs`.

**Continuing after interruption**

The helper allocates non-overwriting log names. A new recording is a new input
set; a frozen run must copy or reference fixed logs and record their hashes.

**Common problem**

Gazebo topics are not available, `gz` uses the wrong world, or the loggers are
started without `PIPELINE_RUN_DIR`.

## Stage 4 — static scene extraction

**Purpose**

Extract manifests, validate them, resolve geometry, assign semantic materials,
convert unsupported meshes, merge static geometry by material, and emit static
Sionna metadata.

**Required before starting**

Stages 1–2 and a resolved static baseline. The current registry builders have
no CLI and retain the old default root
`rt_out/experiments/factory_panda_ur5/legacy_run_20260522_133045`. This is a
known portability limitation, not a hidden stage.

**Command**

For the current implementation, use the extracted legacy baseline explicitly
when it is available (the corresponding source is archived in the repository):

```bash
STATIC_ROOT="$REPO_ROOT/rt_out/experiments/factory_panda_ur5/legacy_run_20260522_133045"

python3 rt_out/scripts/static_scene/extract_scene_manifests.py \
  --root "$REPO_ROOT" \
  --sdf "$REPO_ROOT/myworld_rt.sdf" \
  --models-root "$REPO_ROOT/models" \
  --experiment-root "$STATIC_ROOT" \
  --output-dir "$STATIC_ROOT/manifests"
python3 rt_out/scripts/static_scene/validate_scene_manifests.py \
  --experiment-root "$STATIC_ROOT"
python3 rt_out/scripts/static_scene/build_scene_geometry_registry.py
python3 rt_out/scripts/static_scene/build_static_scene_registry.py

# The registry builders retain the legacy static baseline. Freeze the validated
# dynamic manifest into the new run before any dynamic stage reads it.
mkdir -p "$RUN_ROOT/manifests"
cp -- "$STATIC_ROOT/manifests/dynamic_manifest.json" \
  "$RUN_ROOT/manifests/dynamic_manifest.json"
python3 - "$REPO_ROOT" "$STATIC_ROOT/manifests/dynamic_manifest.json" \
  "$RUN_ROOT/manifests/dynamic_manifest.json" \
  "$RUN_ROOT/manifests/dynamic_manifest_provenance.json" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

repo_root = Path(sys.argv[1]).resolve()
source = Path(sys.argv[2]).resolve()
destination = Path(sys.argv[3]).resolve()
provenance_path = Path(sys.argv[4]).resolve()
assert source.is_file() and destination.is_file()
source_bytes = source.read_bytes()
assert destination.read_bytes() == source_bytes
def relative(path: Path) -> str:
    return str(path.relative_to(repo_root))
provenance_path.write_text(json.dumps({
    "source_manifest": relative(source),
    "destination_manifest": relative(destination),
    "source_sdf": relative(repo_root / "myworld_rt.sdf"),
    "sha256": hashlib.sha256(source_bytes).hexdigest(),
}, indent=2) + "\n", encoding="utf-8")
print("dynamic_manifest_binding=PASS")
PY
python3 rt_out/scripts/static_scene/merge_static_scene_by_material.py \
  --registry "$STATIC_ROOT/manifests/static_registry.json" \
  --out-dir "$STATIC_ROOT/static_scene/export" \
  --blender "$BLENDER" \
  --helper "$REPO_ROOT/rt_out/scripts/static_scene/static_scene_blender_merge_worker.py"
python3 rt_out/scripts/static_scene/build_static_sionna_xml.py \
  --manifest "$STATIC_ROOT/static_scene/export/merged_static_manifest.json" \
  --output "$STATIC_ROOT/static_scene/export/static_scene_sionna.xml"
```

If conversion is required, the merge orchestrator launches the Blender worker;
the standalone Blender converters are:

```bash
"$BLENDER" --background --python rt_out/scripts/static_scene/convert_dae_to_ply_blender.py -- <input.dae> <output.ply>
"$BLENDER" --background --python rt_out/scripts/static_scene/convert_mesh_to_ply_blender.py -- <input.mesh> <output.ply>
```

**Main options**

`extract_scene_manifests.py` supports `--sdf`, `--models-root`,
`--experiment-root`, `--dynamic-prototype-config`, and `--output-dir`.
`merge_static_scene_by_material.py` supports `--registry`, `--out-dir`,
`--blender`, `--helper`, `--export-individual`, and `--manifest-name`.

**Input**

SDF, model assets, `material_map.json`, dynamic config, and source meshes.

**Output**

`static_manifest.json`, `dynamic_manifest.json`, `geometry_registry.json`,
`static_registry.json`, converted meshes, merged material PLYs,
`merged_static_manifest.json`, and `static_scene_sionna.xml`.

**Check**

The manifest validator must pass. Check ready-entry counts, hard errors,
material groups, mesh existence, and XML path resolution. Static merged groups
must be one per emitted material, with no duplicate material class.

**Continuing after interruption**

Manifest extraction and validation are repeatable. Mesh conversion/merge writes
intermediate job metadata but is not an all-or-nothing run; preserve the
failed output and use a new output directory when the baseline is uncertain.

**Common problem**

The no-argument registry stages read their hard-coded legacy root, a Blender
importer is missing, or a source mesh has no material mapping.

## Stage 5 — frame sampling and rigid dynamic processing

**Purpose**

Turn pose logs into sampled frame records, resolve visual-to-link geometry, and
export frame-specific rigid meshes.

**Required before starting**

Static manifests, dynamic manifest, resolved experiment config, and pose logs.

**Command**

```bash
python3 rt_out/scripts/dynamic_rigid/sample_experiment_frames.py \
  --config "$RUN_ROOT/config/experiment_config.json"
python3 rt_out/scripts/dynamic_rigid/build_dynamic_pose_frames.py \
  --experiment-root "$RUN_ROOT" \
  --dynamic-prototype-config "$RUN_ROOT/config/dynamic_prototype_config.json" \
  --dynamic-manifest "$RUN_ROOT/manifests/dynamic_manifest.json" \
  --frames-json "$RUN_ROOT/frames/sampled_frames.json" \
  --output "$RUN_ROOT/frames/dynamic_frames.json"
python3 rt_out/scripts/dynamic_rigid/resolve_dynamic_visual_frames.py \
  --experiment-root "$RUN_ROOT" \
  --dynamic-prototype-config "$RUN_ROOT/config/dynamic_prototype_config.json" \
  --dynamic-manifest "$RUN_ROOT/manifests/dynamic_manifest.json" \
  --frames-json "$RUN_ROOT/frames/sampled_frames.json" \
  --dynamic-frames "$RUN_ROOT/frames/dynamic_frames.json" \
  --output "$RUN_ROOT/frames/dynamic_visual_frames.json"
python3 rt_out/scripts/dynamic/export_dynamic_meshes_batch.py \
  --config "$RUN_ROOT/config/experiment_config.json" \
  --blender "$BLENDER"
```

**Main options**

`--max-frames` is a bounded debug limit on batch export. `--include-actors`
belongs to the alternative actor-aware branch. Per-frame export uses
`dynamic_rigid/export_dynamic_frame_meshes.py --frame-id`.

**Input**

Sampled frame JSON, pose logs, dynamic manifest, model meshes, and config.

**Output**

`frames/sampled_frames.json`, `dynamic_frames.json`,
`dynamic_visual_frames.json`, and per-frame dynamic mesh directories/manifests.

**Check**

Frame IDs, source sample indices, timestamps, Panda/UR5 link counts, visual
counts, transforms, and mesh paths must agree. After the builder completes,
confirm that the copied manifest and recorded pose inputs were actually used:

```bash
test -s "$RUN_ROOT/manifests/dynamic_manifest.json"
test -s "$RUN_ROOT/manifests/dynamic_manifest_provenance.json"
python3 - "$RUN_ROOT/frames/dynamic_frames.json" "$REPO_ROOT" "$RUN_ROOT" <<'PY'
import json
import sys
from pathlib import Path

frames = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
repo_root = Path(sys.argv[2]).resolve()
run_root = Path(sys.argv[3]).resolve()
expected = {
    "Panda": run_root / "inputs/poses/panda_pose.log",
    "ur5_rg2": run_root / "inputs/poses/ur5_pose.log",
}
for model, path in expected.items():
    assert frames["dynamic_pose_logs"][model] == str(path), (model, frames["dynamic_pose_logs"].get(model))
    assert path.is_file() and path.stat().st_size > 0
print("stage5_pose_inputs=PASS")
PY
```

**Continuing after interruption**

Existing frame mesh manifests are checked by scripts that perform several steps;
generic batch export is safer when pointed at a distinct debug root and does not imply that every
existing mesh is scientifically compatible.

**Common problem**

Pose-log sample index mismatch, missing visual/link join, or config `output_dir`
resolving outside `RUN_ROOT`.

## Stage 6 — optional actor-aware processing

**Purpose**

Sample the actor independently, evaluate it in Blender, and produce one baked
actor mesh per selected frame.

**Required before starting**

Stage 5, a Gazebo actor declaration, actor manifest/config, and Blender.

**Command**

```bash
python3 rt_out/scripts/dynamic_actor/extract_actor_manifest.py \
  --world "$REPO_ROOT/myworld_rt.sdf" \
  --models-root "$REPO_ROOT/models" \
  --output "$RUN_ROOT/manifests/actor_manifest.json"
python3 rt_out/scripts/dynamic_actor/build_experiment_actor_frame_samples.py \
  --config "$RUN_ROOT/config/experiment_config.json" \
  --frames-json "$RUN_ROOT/frames/sampled_frames.json" \
  --dynamic-frames "$RUN_ROOT/frames/dynamic_frames.json" \
  --output "$RUN_ROOT/frames/actor_frame_samples.json"
python3 rt_out/scripts/dynamic/export_dynamic_meshes_batch.py \
  --config "$RUN_ROOT/config/experiment_config.json" \
  --include-actors --blender "$BLENDER"
```

**Main options**

Actor export supports `--alignment-policy`, `--z-alignment-policy`, and
`--floor-z`. The current validated policy is
`bounds_center_xy_to_root`, `bounds_min_z_to_floor`, and `0.1`.

**Input**

Actor manifest, actor samples, actor assets, sampled frames, and actor config.

**Output**

`frames/actor_frame_samples.json`, `frames/actor_meshes/`, actor manifests,
Blender specs/summaries, and an actor mesh index.

**Check**

Check actor identity, frame/source index, one actor entry per intended frame,
`human_skin` material, topology, XY alignment, and floor alignment.

**Continuing after interruption**

Actor mesh export is frame-local; existing valid frame manifests can be reused
by the restart-safe script. Invalid existing files must not be silently
treated as completed.

**Common problem**

Missing actor asset, absent Blender `bpy`, mismatched frame list, or an
unintended claim that offline actor sampling matches runtime animation phase.

Actor-free composition and actor-aware composition are alternatives from this
point onward; do not run both into the same output tree.

## Stage 7 — composed frame generation

**Purpose**

Combine the static baseline, rigid frame meshes, and optional actor meshes into
the manifest consumed by XML generation.

**Required before starting**

Static merged manifest, dynamic frame manifests, and actor frame manifests when
selected.

**Command**

```bash
python3 rt_out/scripts/composition/compose_frame_manifests_batch.py \
  --config "$RUN_ROOT/config/experiment_config.json" \
  --include-actors
```

For one prototype frame:

```bash
python3 rt_out/scripts/dynamic_rigid/compose_frame_scene.py \
  --frame-id 0 \
  --static-manifest "$STATIC_ROOT/static_scene/export/merged_static_manifest.json" \
  --dynamic-manifest "$RUN_ROOT/frames/dynamic_meshes/frame_000/dynamic_frame_000_manifest.json" \
  --actor-frame-manifest "$RUN_ROOT/frames/actor_meshes/frame_000/actor_frame_000_manifest.json" \
  --output-manifest "$RUN_ROOT/frames/composed_manifests/frame_000_manifest.json"
```

**Main options**

`--include-actors` is an alternative composition mode. `--max-frames` bounds
batch composition; `--no-progress` and `--progress-every` affect logging only.

**Input**

Static merged manifest, dynamic manifests, optional actor manifests, and config.

**Output**

`frames/composed_manifests/frame_XXX_manifest.json` and a composed-manifest
index. The expected actor-aware counts are 11 static + 21 dynamic + 1 actor =
33 total entries.

**Check**

Verify counts, unique entry IDs, existing mesh paths, material labels, frame
IDs, and source sample indices before XML generation.

**Continuing after interruption**

Existing manifests are reused only when their structural validation passes.
Write bounded tests/debug output to a separate run root.

**Common problem**

Static paths point to a different baseline, actor entries are omitted, or a
frame-local mesh is missing.

## Stage 8 — ground-truth scene point clouds

**Purpose**

Generate mesh-derived labeled ground-truth PCLs and validate their schema.

**Required before starting**

Frame dynamic/actor meshes, fine taxonomy and mapping, and the experiment-local
GT inputs. This stage is downstream of geometry generation, not perception RGB
capture.

**Command**

The current experiment-local producer is a small script that can create a smoke
or full-layout result;
its exact CLI is:

```bash
python3 rt_out/scripts/experiments/semantic_ablation/semantic_ablation_build_gt_scene_pointcloud_smoke.py \
  --experiment-root "$RUN_ROOT" \
  --expected-frame-count 10
python3 rt_out/scripts/experiments/semantic_ablation/semantic_ablation_build_gt_scene_pointcloud_smoke.py \
  --experiment-root "$RUN_ROOT" \
  --expected-frame-count 10 --generate
```

For the separate 100-frame benchmark script, use only its explicit preflight
or small-test options:

```bash
python3 rt_out/scripts/evaluation/run_gt_pointcloud_benchmark.py \
  --root "$RUN_ROOT" --frame-count 100 --preflight
```

There is no current generic `--frame-count 2446` GT producer. The validated
2,446-frame PCL set is a saved result; do not present the smoke script
or 100-frame benchmark as a command that regenerates it.

**Main options**

`--generate` authorizes writing; without it the script performs topology/input
checks. `--expected-frame-count` is mandatory for the intended workload. The
producer uses 100,000 points per frame and a fixed seed in its implementation.

**Input**

Object-level static meshes, frame rigid/actor meshes, taxonomy/mapping, and
frame metadata.

**Output**

`gt_scene_pointclouds/frame_XXX_gt_scene.ply`, `pointcloud_index.csv`,
`label_registry.json`, `sampling_manifest.json`, `progress_manifest.json`, and
`validation_summary.json`.

**Check**

For the validated reference PLY header the fields are exactly:

```text
x y z class_label instance_id material_id object_type_id source_type_id
```

Check frame ID `N` maps to `frame_NNN_gt_scene.ply`, point count, finite values,
label IDs, instance/material consistency, and SHA-256 index entries. These are
not RGB PCLs.

**Continuing after interruption**

The smoke producer stages PLYs and a progress manifest, validates resumed
files, and promotes the output directory only after final validation. It
refuses to overwrite an existing completed output root.

**Common problem**

Confusing merged static meshes with object-level GT sources, missing taxonomy,
partial frame meshes, or assuming the current smoke script is a full-run
2,446-frame implementation.

## Stage 9 — Sionna XML generation

**Purpose**

Convert composed frame manifests into package-relative per-frame Sionna XML.

**Required before starting**

Validated composed manifests, RT material mapping, and all referenced PLYs.

**Command**

```bash
python3 rt_out/scripts/rt/build_sionna_xml_batch.py \
  --config "$RUN_ROOT/config/experiment_config.json"
```

For one frame:

```bash
python3 rt_out/scripts/dynamic_rigid/build_frame_sionna_xml.py \
  --frame-id 0 \
  --rt-material-config "$RUN_ROOT/config/rt_material_mapping.json" \
  --input-manifest "$RUN_ROOT/frames/composed_manifests/frame_000_manifest.json" \
  --output-xml "$RUN_ROOT/sionna_xml/frame_000_sionna.xml"
```

**Main options**

Batch XML supports `--max-frames`, `--no-progress`, and `--progress-every`.
The XML builder emits radio material definitions, static/dynamic/actor shapes,
and relative mesh filenames; TX/RX are configured by RT execution.

**Input**

Composed manifests, material mapping, and PLY meshes.

**Output**

`sionna_xml/frame_XXX_sionna.xml` and `sionna_xml_index.csv`.

**Check**

Parse every XML, check missing mesh targets, material references, and expected
shape counts. The reference actor-aware run has 33 shapes per XML.

**Continuing after interruption**

Batch generation may skip valid existing XMLs; an invalid existing XML must be
removed from the debug run or regenerated in a new run, not accepted silently.

**Common problem**

Manifest paths are absolute/stale, RT material mapping lacks a material class,
or a composed record points at a missing PLY.

## Stage 10 — Sionna RT execution

**Purpose**

Run one compact multi-RX RT solve per XML frame/RX pair and publish validated
CSV rows.

**Required before starting**

Valid XML index, experiment config with TX/RX/frequency, and a Sionna-capable
Python interpreter.

**Command**

Lightweight probe/preflight for the current 2,446-frame actor-aware script:

```bash
python3 rt_out/scripts/experiments/semantic_ablation/semantic_ablation_run_sionna_rt_restart_safe.py \
  --root "$RUN_ROOT" --preflight
python3 rt_out/scripts/experiments/semantic_ablation/semantic_ablation_run_sionna_rt_restart_safe.py \
  --root "$RUN_ROOT" --probe-frame 0 --probe-rx rx_panda_base \
  --sionna-python "$SIONNA_PYTHON"
```

The full script is an alternative to the generic batch runner:

```bash
python3 rt_out/scripts/experiments/semantic_ablation/semantic_ablation_run_sionna_rt_restart_safe.py \
  --root "$RUN_ROOT" --run --sionna-python "$SIONNA_PYTHON"
```

The generic runner is another alternative:

```bash
python3 rt_out/scripts/rt/run_rt_multi_rx_batch.py \
  --config "$RUN_ROOT/config/experiment_config.json" \
  --sionna-python "$SIONNA_PYTHON"
```

Do not run both orchestrators against the same output root.

**Main options**

The reference solver settings are max depth 2, 20,000 samples per source,
10,000 max paths per source, seed 42, synthetic array, LoS and specular
reflection enabled, diffuse/refraction disabled. The generic runner also has
`--max-frames`, `--max-rows`, `--continue-on-error`, and progress options.

**Input**

Sionna XML, TX/RX config, frequency, solver settings, and runtime environment.

**Output**

The restart-safe script writes per-frame `rt_results/staging/frame_NNN.csv`,
`rt_2446frames_multi_rx.csv`, `rt_restart_metrics.json`, and
`rt_validation_summary.json`. Each complete frame has six RX rows.

**Check**

Require 2,446 frames × six RX = 14,676 unique rows, matching XML/frame IDs,
timestamps, TX/RX coordinates, frequency, solver sanity, and no failed rows.
`rx_power_dbm` is a compact received-power summary, not a complete channel
tensor or path-level record.

**Continuing after interruption**

The restart-safe script validates and reuses valid frame chunks and rejects
invalid or mismatched chunks. It refuses to overwrite the final CSV. Probe and
small test runs must use a separate output root.

**Common problem**

Wrong interpreter/Mitsuba variant, stale XML paths, missing RX IDs, or treating
`--continue-on-error` output as a release result.

## Stage 11 — labels and downstream features

**Purpose**

Build temporal targets and optional scene representations after complete PCL/RT
products exist.

**Required before starting**

Validated RT CSV, frame/voxel inputs, and resolved experiment config.

**Command**

```bash
python3 rt_out/scripts/rt/build_rt_labels.py \
  --config "$RUN_ROOT/config/experiment_config.json" \
  --horizon-frames 10 --one-second-split
python3 rt_out/scripts/features/build_segmentation_ablation_voxels.py \
  --config "$RUN_ROOT/config/experiment_config.json" --voxel-size 0.04
python3 rt_out/scripts/features/build_classical_ml_descriptors.py \
  --root "$REPO_ROOT"
```

The main 2,446-frame target builder used by the reference run is also
available:

```bash
python3 rt_out/scripts/experiments/semantic_ablation/semantic_ablation_build_canonical_horizon10_supervised_targets.py \
  --root "$REPO_ROOT" --validate-only
```

**Main options**

`build_rt_labels.py` defaults to horizon 1; pass `--horizon-frames 10
--one-second-split` for the 2,446-frame format. Voxel generation supports
`--smoke-frames`, `--validate-only`, and `--resolution-audit`. Descriptor v2
must be checked against its validation summary; v1 is partial in the current
run.

**Input**

RT CSV, GT PCL/voxel files, paired index, taxonomy, and frame metadata.

**Output**

Temporal label CSVs, paired/split manifests, voxel NPZ/NPY arrays, descriptor
staging/consolidated arrays, and validation reports.

**Check**

Check source/target frame offset, split counts, RX order, no target leakage,
feature dimensions, and row-key alignment. The reference horizon-10 domain is
2,436 source frames × six RX = 14,616 rows with train/excluded/test
`10170/120/4326`.

**Continuing after interruption**

Many feature builders refuse or overwrite outputs according to their own
current implementation. Validate before rerunning and use a new run for a
changed target definition.

**Common problem**

Building labels from a debug RT CSV, using a mismatched horizon, or claiming a
complete v1 descriptor from the three staging files that are actually present.

## Stage 12 — final validation and packaging

**Purpose**

Check the completed run without launching expensive jobs, then package only
the intended artifacts.

**Required before starting**

All selected products and their validation reports.

**Command**

```bash
python3 -m compileall -q rt_out/scripts scripts
find rt_out/scripts -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
python3 -m json.tool "$RUN_ROOT/config/experiment_config.json" >/dev/null
python3 -m json.tool "$RUN_ROOT/rt_results/rt_validation_summary.json" >/dev/null
python3 - <<'PY'
import csv
import os
from pathlib import Path
root = Path(os.environ["PIPELINE_RUN_DIR"])
xmls = sorted((root / "sionna_xml").glob("frame_*_sionna.xml"))
rows = list(csv.DictReader((root / "rt_results/rt_2446frames_multi_rx.csv").open(newline="")))
assert len(xmls) == 2446
assert len(rows) == 2446 * 6
assert len({(r["frame_id"], r["rx_id"]) for r in rows}) == len(rows)
print("frame_xml_rt_alignment=PASS")
PY
rg -n '/home/|/mnt/|/tmp/' "$RUN_ROOT" || true
```

The quoted heredoc keeps shell interpolation out of the Python block; the
block reads the exported `PIPELINE_RUN_DIR` directly.

**Main options**

Use a temporary extraction directory to validate an archive. Do not package
`models/`, predictions, trained models, or generated files unless the
release scope explicitly includes them.

**Input**

Run tree, manifests, XML, CSV/JSON reports, PLY headers, and release inventory.

**Output**

Validation logs and an archive created outside the source run. The report
`zenodo_payload_inventory.json` is a check report; it is not a substitute for
validating the extracted archive.

**Check**

Check frame/RX/timestamp alignment, XML parsing and mesh targets, PLY headers,
JSON/CSV parsing, relative paths, absence of private absolute paths, and exact
archive contents after extraction.

**Continuing after interruption**

Validation is read-only. Packaging must write a new archive and never replace
the source run.

**Common problem**

Including full local model/result directories in a reduced archive, old
absolute paths after extraction, or treating a partial feature family as a
complete release.

## Old names

Names such as `00_extract_scene_manifests.py`, `30_build_prototype_dynamic_frames.py`,
and `35_run_prototype_three_frame_rt_sanity.py` are not current filenames. The
current functional paths are documented in [script_reference.md](script_reference.md).
