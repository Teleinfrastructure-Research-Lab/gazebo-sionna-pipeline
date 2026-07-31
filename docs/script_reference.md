# Script reference

This page documents every source file under `rt_out/scripts/` and `scripts/`:
**81 Python files, 7 shell files, and 2 C++ files**. The paths below are the
current source paths. Old numbered names such as `00_extract...` and
`30_build...` are not present in this repository version.

Use [Pipeline execution order](pipeline_execution_order.md) for the execution
sequence, [Configuration](configuration.md) for file ownership, and
[Developer guide](pipeline_execution_order.md) for generated-file formats.

## Invocation and path rules

Run commands from the repository root. For a new experiment, set
`PIPELINE_RUN_DIR` to a unique writable directory and pass an explicit
`--experiment-root` or `--config` where the command supports it. Scripts
with old defaults are identified in their descriptions; those defaults do not
provide a portable way to create a new run.

`--help` is a safe interface check. Blender, Gazebo, Sionna RT, point-cloud,
feature, and training commands may start workloads or write generated files.

## Workflow order

The normal sequence is static-scene extraction and validation, geometry
conversion and XML creation, frame sampling and pose processing, mesh export
and frame composition, Sionna RT execution, label and feature generation,
perception capture or reconstruction, evaluation, and training. Use the
complete sequence in [Pipeline execution order](pipeline_execution_order.md)
when a command's position matters.

The sections below keep each source path with its purpose, input, output,
options, existing-file behavior, continuation behavior, and an example.

### `rt_out/scripts/composition/compose_frame_manifests_batch.py`

**What it does**

Combines static, rigid, and optional actor frame manifests and writes the batch composition index.

**When to run it**

Run after dynamic and actor visual-frame manifests exist and before per-frame Sionna XML generation.

**Required software**

Python 3, JSON manifest validation, and the referenced PLY files.

**Input**

Experiment config, static manifest, selected frames, dynamic frame outputs, and optional actor frame outputs.

**Output**

One composed manifest per selected frame plus the composed-scene index and validation metadata.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--config` | PATH | Yes | None | Path to experiment_config.json |
| `--no-progress` | flag | No | None | Disable progress bars / periodic progress prints. |
| `--progress-every` | INT | No | 10 | Fallback text progress print frequency when tqdm is unavailable. |
| `--max-frames` | INT | No | None | Optional debug limit on the number of frames to compose. |
| `--include-actors` | flag | No | None | Also include actor frame manifests from <output_root>/frames/actor_meshes/actor_mesh_index.csv. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/composition/compose_frame_manifests_batch.py --config "$RUN_ROOT/config/experiment_config.json" --include-actors
```


### `rt_out/scripts/datasets/canonical_segmentation_voxel_dataset.py`

**What it does**

Loads the canonical sparse voxel dataset, validates schemas and chronological splits, and optionally samples one item per split.

**When to run it**

Run after voxel files, paired index, and supervised targets exist; use --smoke for a small adapter check.

**Required software**

Python 3 and NumPy; the adapter reads existing sparse voxel files.

**Input**

The --root tree must contain representation_schema.json, semantic_channel_manifest.json, material_lut_manifest.json, paired_index.csv, link_context.npy, scene_index.csv, frame NPZ files, and beam_results/canonical_4x4_dft16/supervised_targets_horizon10.csv.

**Output**

Prints a JSON validation summary; --smoke also prints dimensions, dtypes, split samples, and voxel counts without creating artifacts.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--root` | PATH | Yes | None | Repository or experiment root containing the input tree. |
| `--view` | VALUE | No | GSIM | Feature view or dataset representation to load. |
| `--target` | VALUE | No | y_adaptation_trigger_1db | Target column or label definition to load or build. |
| `--cache-frames` | INT | No | 2 | Number of decoded frames retained by the in-memory cache. |
| `--smoke` | flag | No | None | Run the reduced smoke path. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/datasets/canonical_segmentation_voxel_dataset.py --root "$RUN_ROOT/features/segmentation_ablation_voxels/voxel_0.04m" --view GSIM --target y_adaptation_trigger_1db --cache-frames 2 --smoke
```


### `rt_out/scripts/dynamic/export_dynamic_meshes_batch.py`

**What it does**

Exports posed rigid-body meshes for selected visual frames by invoking the Blender frame exporter in a batch.

**When to run it**

Run after dynamic_visual_frames.json is validated and before composing frame manifests.

**Required software**

Python 3, JSON/SDF parsing, repository mesh assets, and Blender for mesh-export stages.

**Input**

Experiment config, normalized dynamic visual frames, model/link mesh references, poses, and optional actor settings.

**Output**

Per-frame dynamic PLYs, frame manifests, export index, and Blender metadata.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--config` | PATH | Yes | None | Path to experiment_config.json |
| `--no-progress` | flag | No | None | Disable progress bars / periodic progress prints. |
| `--progress-every` | INT | No | 10 | Fallback text progress print frequency when tqdm is unavailable. |
| `--max-frames` | INT | No | None | Optional debug limit on the number of frames to export. |
| `--include-actors` | flag | No | None | Also export actor meshes into <output_root>/frames/actor_meshes and write actor_mesh_index.csv. |
| `--blender` | PATH | No | None | Optional explicit Blender executable. Defaults to BLENDER, then the blender executable on PATH, then common local install layouts. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/dynamic/export_dynamic_meshes_batch.py --config "$RUN_ROOT/config/experiment_config.json" --blender "$BLENDER"
```


### `rt_out/scripts/dynamic_actor/actor_blender_export_frame_meshes.py`

- **Type:** Blender worker for actor frame mesh export
- **Started by:** `rt_out/scripts/dynamic_actor/export_actor_frame_meshes.py`
- **Input:** Required `--spec` path to a worker specification JSON containing actor meshes, materials, pose, alignment, and destination paths.
- **Output:** Per-part PLY meshes and worker summary/metadata requested by the specification.
- **Run directly:** No; the parent supplies Blender arguments and validates the summary.

### `rt_out/scripts/dynamic_actor/build_actor_frame_samples.py`

**What it does**

Builds actor frame samples from the actor manifest, actor configuration, and prototype timing/material settings.

**When to run it**

Run after actor manifest/configuration exist and before actor mesh export.

**Required software**

Python 3, JSON/SDF parsing, repository mesh assets, and Blender for mesh-export stages.

**Input**

Actor manifest, actor/dynamic/material configuration files, and output path.

**Output**

Actor frame-sample JSON with selected times, poses, and source visual records.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--actor-manifest` | PATH | No | source default | Actor manifest defining links and visuals. If omitted, the script uses its source-defined actor manifest path constant; pass an explicit path for a new run. |
| `--actor-config` | PATH | No | source default | Actor animation/configuration file. If omitted, the script uses its source-defined actor config path constant; pass an explicit path for a new run. |
| `--dynamic-prototype-config` | PATH | No | source default | Dynamic timing and model configuration. If omitted, the script uses its source-defined dynamic prototype config path constant; pass an explicit path for a new run. |
| `--rt-material-config` | PATH | No | source default | Controls the rt material config value used by this script. If omitted, the script uses its source-defined rt material config path constant; pass an explicit path for a new run. |
| `--output` | PATH | No | source default | Destination file or directory. If omitted, the script uses its source-defined output path constant; pass an explicit path for a new run. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/dynamic_actor/build_actor_frame_samples.py --help
```


### `rt_out/scripts/dynamic_actor/build_experiment_actor_frame_samples.py`

**What it does**

Builds actor frame samples from the experiment frame selection and optional frame/time limits.

**When to run it**

Run after experiment configuration and selected frames exist and before actor mesh export.

**Required software**

Python 3, JSON/SDF parsing, repository mesh assets, and Blender for mesh-export stages.

**Input**

Experiment config, selected frame JSON, actor manifest/config, and optional frame IDs or limits.

**Output**

Actor sample JSON named by --output.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--config` | PATH | Yes | None | Path to experiment_config.json |
| `--frames-json` | PATH | No | None | Optional sampled-frame JSON. Defaults to <output_root>/frames/sampled_frames.json |
| `--dynamic-frames` | PATH | No | None | Optional dynamic-frames JSON. Defaults to <output_root>/frames/dynamic_frames.json when actor_time_policy=timestamp_mod_trajectory_duration |
| `--max-frames` | INT | No | None | Optional debug limit on the number of selected frame records. |
| `--frame-ids` | LIST | No | None | Optional comma-separated list of frame_ids to select. |
| `--output` | PATH | No | None | Optional output JSON path. Defaults to <output_root>/frames/actor_frame_samples.json |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/dynamic_actor/build_experiment_actor_frame_samples.py --config "$RUN_ROOT/config/experiment_config.json" --output "$RUN_ROOT/frames/actor_frame_samples.json"
```


### `rt_out/scripts/dynamic_actor/export_actor_frame_meshes.py`

**What it does**

Exports one actor frame to Blender-baked PLY meshes and records alignment and material metadata.

**When to run it**

Run after actor samples and actor manifest exist; the batch exporter calls it per frame.

**Required software**

Python 3, JSON/SDF parsing, repository mesh assets, and Blender for mesh-export stages.

**Input**

Frame ID, actor samples, actor manifest, optional visual mapping, output root, Blender executable, and alignment settings.

**Output**

Actor PLY files, frame manifest, and export metadata.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--frame-id` | INT | Yes | None | Frame identifier to inspect or export. |
| `--actor-samples` | PATH | No | source default | Actor frame-sample JSON. If omitted, the script uses its source-defined actor samples path constant; pass an explicit path for a new run. |
| `--actor-manifest` | PATH | No | source default | Actor manifest defining links and visuals. If omitted, the script uses its source-defined actor manifest path constant; pass an explicit path for a new run. |
| `--output-root` | PATH | No | source default | Destination root for generated per-frame files. If omitted, the script uses its source-defined output root path constant; pass an explicit path for a new run. |
| `--blender` | PATH | No | None | Blender executable path. |
| `--alignment-policy` | VALUE | No | none | Experimental post-evaluation alignment policy. Default 'none' preserves existing export behavior; 'bounds_center_xy_to_root' shifts baked vertices in XY so their bounds center matches root_pose6. |
| `--z-alignment-policy` | VALUE | No | none | Experimental vertical post-evaluation alignment policy. Default 'none' preserves existing export behavior; 'bounds_min_z_to_floor' shifts baked vertices in Z so bounds_min_z equals --floor-z. |
| `--floor-z` | FLOAT | No | None | Floor Z used by bounds_min_z_to_floor. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/dynamic_actor/export_actor_frame_meshes.py --frame-id 0 --actor-samples "$RUN_ROOT/frames/actor_frame_samples.json" --actor-manifest "$RUN_ROOT/manifests/actor_manifest.json" --output-root "$RUN_ROOT/frames/actor_meshes" --blender "$BLENDER"
```


### `rt_out/scripts/dynamic_actor/extract_actor_manifest.py`

**What it does**

Reads the world SDF and model assets and extracts actor links, visuals, mesh references, and material information.

**When to run it**

Run after the world SDF and models directory are fixed and before actor frame sampling.

**Required software**

Python 3, JSON/SDF parsing, repository mesh assets, and Blender for mesh-export stages.

**Input**

World SDF, models root, and actor-manifest output path.

**Output**

JSON actor manifest with actor identity, links, visuals, meshes, and source references.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--world` | PATH | No | source default | World SDF containing top-level <actor> entries. If omitted, the script uses its source-defined world path constant; pass an explicit path for a new run. |
| `--models-root` | PATH | No | source default | Root directory used to resolve model:// actor assets. If omitted, the script uses its source-defined models root path constant; pass an explicit path for a new run. |
| `--output` | PATH | No | source default | Output actor manifest JSON path. If omitted, the script uses its source-defined output path constant; pass an explicit path for a new run. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/dynamic_actor/extract_actor_manifest.py --world myworld_rt.sdf --models-root models --output "$RUN_ROOT/manifests/actor_manifest.json"
```


### `rt_out/scripts/dynamic_prototype_config.py`

- **Type:** Imported configuration loader
- **Imported by:** Dynamic pose, visual-frame, actor, composition, and RT sanity scripts.
- **Input:** Dynamic prototype configuration JSON; relative `pose_log` values resolve from its owning run when it is stored under `<run>/config/`.
- **Output:** Normalized dynamic model/link, pose, and timing settings in memory.
- **Run directly:** No; importing it does not create or modify experiment artifacts.

### `rt_out/scripts/dynamic_rigid/build_dynamic_pose_frames.py`

**What it does**

Parses Panda and UR5 pose logs and aligns them with the selected experiment frames.

**When to run it**

Run after pose logs, dynamic_manifest.json, and sampled_frames.json exist and before visual-frame resolution.

**Required software**

Python 3, JSON/SDF parsing, repository mesh assets, and Blender for mesh-export stages.

**Input**

Dynamic manifest/config, sampled frames, and non-empty Panda/UR5 pose logs.

**Output**

dynamic_frames.json with normalized poses, source log references, timing, and validation.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--experiment-root` | PATH | No | None | Optional run root; derives config/, manifests/, and dynamic_frames/ paths. |
| `--dynamic-prototype-config` | PATH | No | None | Dynamic prototype configuration JSON. Overrides --experiment-root/config/. |
| `--dynamic-manifest` | PATH | No | None | Extracted dynamic manifest JSON. Overrides --experiment-root/manifests/. |
| `--frames-json` | PATH | No | None | Optional frame selection JSON with frame_id/source_sample records. |
| `--output` | PATH | No | None | Output JSON path. Defaults to the validated prototype output path. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/dynamic_rigid/build_dynamic_pose_frames.py --experiment-root "$RUN_ROOT" --dynamic-prototype-config "$RUN_ROOT/config/dynamic_prototype_config.json" --dynamic-manifest "$RUN_ROOT/manifests/dynamic_manifest.json" --frames-json "$RUN_ROOT/frames/sampled_frames.json" --output "$RUN_ROOT/frames/dynamic_frames.json"
```


### `rt_out/scripts/dynamic_rigid/build_frame_sionna_xml.py`

**What it does**

Serializes one composed frame manifest into a Sionna-compatible XML scene for inspection or a batch caller.

**When to run it**

Run after one composed frame manifest and referenced meshes pass validation.

**Required software**

Python 3, JSON/SDF parsing, repository mesh assets, and Blender for mesh-export stages.

**Input**

Frame ID, composed manifest, dynamic/material configuration, and optional TX/RX/output arguments.

**Output**

One XML scene at --output-xml.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--frame-id` | INT | No | 0 | Prototype frame id to emit |
| `--dynamic-prototype-config` | PATH | No | None | Dynamic prototype configuration JSON; loaded after CLI parsing. |
| `--rt-material-config` | PATH | No | None | RT material/runtime JSON; loaded after CLI parsing. |
| `--input-manifest` | PATH | No | None | composed_frame_XXX_manifest.json path |
| `--output-xml` | PATH | No | None | Output frame_XXX_sionna.xml path |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/dynamic_rigid/build_frame_sionna_xml.py --frame-id 0 --rt-material-config "$RUN_ROOT/config/rt_material_mapping.json" --input-manifest "$RUN_ROOT/frames/composed_manifests/frame_000_manifest.json" --output-xml "$RUN_ROOT/sionna_xml/frame_000_sionna.xml"
```


### `rt_out/scripts/dynamic_rigid/compose_frame_scene.py`

**What it does**

Combines static, rigid, and optional actor frame records into one composed scene manifest for a single frame.

**When to run it**

Run after dynamic and optional actor frame outputs exist and before frame XML generation.

**Required software**

Python 3, JSON/SDF parsing, repository mesh assets, and Blender for mesh-export stages.

**Input**

Frame ID, static manifest, dynamic frame manifest, optional actor frame manifest, and prototype configuration.

**Output**

Composed frame manifest and referenced per-frame output directory.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--frame-id` | INT | No | 0 | Prototype frame id to compose |
| `--dynamic-prototype-config` | PATH | No | None | Dynamic prototype configuration JSON; loaded after CLI parsing. |
| `--static-manifest` | PATH | No | STATIC_MANIFEST_PATH | Frozen merged_static_manifest.json path |
| `--dynamic-manifest` | PATH | No | None | dynamic_frame_XXX_manifest.json path |
| `--output-manifest` | PATH | No | None | Output composed_frame_XXX_manifest.json path |
| `--actor-frame-manifest` | PATH | No | None | Optional actor_frame_XXX_manifest.json path to append baked actor meshes. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/dynamic_rigid/compose_frame_scene.py --help
```


### `rt_out/scripts/dynamic_rigid/export_dynamic_frame_meshes.py`

**What it does**

Exports posed rigid meshes for one selected frame, optionally delegating Blender work to a worker process.

**When to run it**

Run after dynamic_visual_frames.json identifies frame visuals and before composing that frame.

**Required software**

Python 3, JSON/SDF parsing, repository mesh assets, and Blender for mesh-export stages.

**Input**

Frame ID, visual-frame records, dynamic config, output root, and optional Blender worker arguments.

**Output**

Frame directory with posed PLYs, frame manifest, and export metadata.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--frame-id` | INT | No | 0 | Prototype frame id to export |
| `--source-sample-index` | INT | No | None | Expected source sample index for the selected frame |
| `--output-root` | PATH | No | source default | Base directory for frame_XXX dynamic exports If omitted, the script uses its source-defined output root path constant; pass an explicit path for a new run. |
| `--dynamic-prototype-config` | PATH | No | None | Dynamic prototype configuration JSON; loaded after CLI parsing. |
| `--visual-frames-json` | PATH | No | None | Optional visual-frame metadata JSON path. Defaults to the validated prototype file. |
| `--blender-worker` | flag | No | None | Controls the blender worker value used by this script. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/dynamic_rigid/export_dynamic_frame_meshes.py --help
```


### `rt_out/scripts/dynamic_rigid/resolve_dynamic_visual_frames.py`

**What it does**

Resolves each dynamic link visual to a concrete mesh, material, and transform for normalized frames.

**When to run it**

Run after dynamic poses are built and before Blender mesh export.

**Required software**

Python 3, JSON/SDF parsing, repository mesh assets, and Blender for mesh-export stages.

**Input**

Dynamic manifest, normalized dynamic frames, model root, and optional frame/config paths.

**Output**

dynamic_visual_frames.json with resolved mesh/material/transform records.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--experiment-root` | PATH | No | None | Optional run root; derives config/, manifests/, and dynamic_frames/ paths. |
| `--dynamic-prototype-config` | PATH | No | None | Dynamic prototype configuration JSON. Overrides --experiment-root/config/. |
| `--models-root` | PATH | No | None | Root containing dynamic model assets. Defaults to the repository models/ directory. |
| `--dynamic-manifest` | PATH | No | None | Extracted dynamic manifest JSON. Overrides --experiment-root/manifests/. |
| `--frames-json` | PATH | No | None | Optional frame selection JSON with frame_id/source_sample records. |
| `--dynamic-frames` | PATH | No | None | Input dynamic frame records JSON. Defaults to the validated prototype output. |
| `--output` | PATH | No | None | Output visual-frame metadata JSON path. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/dynamic_rigid/resolve_dynamic_visual_frames.py --experiment-root "$RUN_ROOT" --dynamic-manifest "$RUN_ROOT/manifests/dynamic_manifest.json" --dynamic-frames "$RUN_ROOT/frames/dynamic_frames.json" --output "$RUN_ROOT/frames/dynamic_visual_frames.json"
```


### `rt_out/scripts/dynamic_rigid/run_three_frame_multi_rx_rt_sanity.py`

**What it does**

Runs a small three-frame RT check for multiple receivers and writes compact per-frame diagnostics.

**When to run it**

Run only when checking a three-frame actor-aware scene before a larger RT batch.

**Required software**

Python 3, JSON/SDF parsing, repository mesh assets, and Blender for mesh-export stages.

**Input**

Static manifest, radio sites, composed outputs, runtime config, and optional actor inputs.

**Output**

Compact CSV summary and receiver diagnostics.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--radio-sites` | PATH | No | source default | Path to prototype_radio_sites.json If omitted, the script uses its source-defined radio sites path constant; pass an explicit path for a new run. |
| `--static-manifest` | PATH | No | source default | Static merged manifest path If omitted, the script uses its source-defined static manifest path constant; pass an explicit path for a new run. |
| `--composed-root` | PATH | No | source default | Composed scene root If omitted, the script uses its source-defined composed root path constant; pass an explicit path for a new run. |
| `--output-csv` | PATH | No | source default | Output CSV path If omitted, the script uses its source-defined output csv path constant; pass an explicit path for a new run. |
| `--dynamic-prototype-config` | PATH | No | None | Dynamic prototype configuration JSON; loaded after CLI parsing. |
| `--rt-runtime-config` | PATH | No | None | RT material/runtime JSON; loaded after CLI parsing. |
| `--include-actors` | flag | No | None | Export and compose the validated three-frame actor branch. Default behavior remains actor-free. |
| `--actor-samples` | PATH | No | source default | Actor frame samples JSON used when --include-actors is passed. If omitted, the script uses its source-defined actor samples path constant; pass an explicit path for a new run. |
| `--actor-manifest` | PATH | No | source default | Actor manifest JSON used when --include-actors is passed. If omitted, the script uses its source-defined actor manifest path constant; pass an explicit path for a new run. |
| `--actor-alignment-policy` | VALUE | No | bounds_center_xy_to_root | Actor XY alignment policy passed to export_actor_frame_meshes.py when --include-actors is used. |
| `--actor-z-alignment-policy` | VALUE | No | bounds_min_z_to_floor | Actor Z alignment policy passed to export_actor_frame_meshes.py when --include-actors is used. |
| `--actor-floor-z` | FLOAT | No | 0.1 | Floor z passed to export_actor_frame_meshes.py when actor Z alignment requires it. |
| `--sionna-python` | PATH | No | None | Optional explicit Python interpreter with Sionna RT/Mitsuba installed. Defaults to SIONNA_PYTHON, then the legacy COLLABPAPER_PYTHON, then the current interpreter if it already imports sionna.rt. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/dynamic_rigid/run_three_frame_multi_rx_rt_sanity.py --help
```


### `rt_out/scripts/dynamic_rigid/run_three_frame_rt_sanity.py`

**What it does**

Runs a small three-frame RT check for the default receiver set and records summary diagnostics.

**When to run it**

Run only when checking a three-frame scene before a larger RT batch.

**Required software**

Python 3, JSON/SDF parsing, repository mesh assets, and Blender for mesh-export stages.

**Input**

Static manifest, composed root, runtime/material settings, and optional actor samples.

**Output**

Diagnostic CSV and per-frame RT check output.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--static-manifest` | PATH | No | source default | Static merged manifest to compose with each prototype frame. If omitted, the script uses its source-defined static manifest path constant; pass an explicit path for a new run. |
| `--composed-root` | PATH | No | source default | Root directory for composed manifests, XML files, and summary CSV. If omitted, the script uses its source-defined composed root path constant; pass an explicit path for a new run. |
| `--output-suffix` | TEXT | No |  | Optional suffix added before .json/.xml/.csv. |
| `--summary-csv` | PATH | No | None | Optional explicit output CSV path. |
| `--dynamic-prototype-config` | PATH | No | None | Dynamic prototype configuration JSON; loaded after CLI parsing. |
| `--rt-runtime-config` | PATH | No | None | RT material/runtime JSON; loaded after CLI parsing. |
| `--include-actors` | flag | No | None | Export and compose the validated three-frame actor branch. Default behavior remains actor-free. |
| `--actor-samples` | PATH | No | source default | Actor frame samples JSON used when --include-actors is passed. If omitted, the script uses its source-defined actor samples path constant; pass an explicit path for a new run. |
| `--actor-manifest` | PATH | No | source default | Actor manifest JSON used when --include-actors is passed. If omitted, the script uses its source-defined actor manifest path constant; pass an explicit path for a new run. |
| `--actor-alignment-policy` | VALUE | No | bounds_center_xy_to_root | Actor XY alignment policy passed to export_actor_frame_meshes.py when --include-actors is used. |
| `--actor-z-alignment-policy` | VALUE | No | bounds_min_z_to_floor | Actor Z alignment policy passed to export_actor_frame_meshes.py when --include-actors is used. |
| `--actor-floor-z` | FLOAT | No | 0.1 | Floor z passed to export_actor_frame_meshes.py when actor Z alignment requires it. |
| `--sionna-python` | PATH | No | None | Optional explicit Python interpreter with Sionna RT/Mitsuba installed. Defaults to SIONNA_PYTHON, then the legacy COLLABPAPER_PYTHON, then the current interpreter if it already imports sionna.rt. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/dynamic_rigid/run_three_frame_rt_sanity.py --static-manifest "$STATIC_ROOT/static_scene/export/merged_static_manifest.json" --composed-root "$RUN_ROOT/composed_scene"
```


### `rt_out/scripts/dynamic_rigid/sample_experiment_frames.py`

**What it does**

Selects experiment frame IDs and source sample indices from the experiment configuration.

**When to run it**

Run at the start of the dynamic-frame stage, before pose parsing or mesh export.

**Required software**

Python 3, JSON/SDF parsing, repository mesh assets, and Blender for mesh-export stages.

**Input**

Experiment configuration and frame/time sampling parameters.

**Output**

sampled_frames.json with ordered frame IDs, timestamps, and source sample indices.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--config` | PATH | Yes | None | Path to experiment_config.json |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/dynamic_rigid/sample_experiment_frames.py --config "$RUN_ROOT/config/experiment_config.json"
```


### `rt_out/scripts/evaluation/compare_rt_labels.py`

**What it does**

Joins baseline and actor RT label CSVs by frame, source sample, and receiver, then compares binary labels and continuous metrics.

**When to run it**

Run after both label CSVs exist and before interpreting actor-versus-baseline differences.

**Required software**

Python 3 and NumPy; Open3D is used only by the GT visualization script.

**Input**

Baseline labels, actor labels, and output directory; inputs contain the expected 1,194 keyed rows.

**Output**

Four comparison files: label_comparison_summary.csv, label_comparison_by_rx.csv, continuous_metric_comparison.csv, and actor_vs_rigid_label_comparison.md.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--baseline-labels` | PATH | Yes | None | Controls the baseline labels value used by this script. |
| `--actor-labels` | PATH | Yes | None | Controls the actor labels value used by this script. |
| `--output-dir` | PATH | Yes | None | Destination directory for generated reports or indexes. |

**Existing files**

Input artifacts are read-only; diagnostic or validation destinations may be replaced.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/evaluation/compare_rt_labels.py --help
```


### `rt_out/scripts/evaluation/probe_beam_selection_feasibility.py`

**What it does**

Inspects one frame/receiver beam-selection row and checks whether the selected beam meets feasibility conditions.

**When to run it**

Run for a focused diagnostic before changing beam-selection or target-generation logic.

**Required software**

Python 3 and NumPy; Open3D is used only by the GT visualization script.

**Input**

Frame ID, receiver ID, canonical beam rows, and optional diagnostic output path.

**Output**

Console feasibility diagnostic and an optional selected-row diagnostic.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--frame-id` | INT | No | 0 | Frame identifier to inspect or export. |
| `--rx-id` | VALUE | No | rx_panda_base | Receiver identifier for the beam diagnostic. |
| `--output` | PATH | No | None | Destination file or directory. |
| `--validate-only` | flag | No | None | Check existing files without regenerating them. |

**Existing files**

Input artifacts are read-only; diagnostic or validation destinations may be replaced.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/evaluation/probe_beam_selection_feasibility.py --help
```


### `rt_out/scripts/evaluation/run_gt_pointcloud_benchmark.py`

**What it does**

Prepares, preflights, or runs the separate 100-frame GT point-cloud benchmark and can write its summary.

**When to run it**

Run only for the limited GT benchmark; it is not a generic 2,446-frame producer.

**Required software**

Python 3 and NumPy; Open3D is used only by the GT visualization script.

**Input**

Benchmark root, frame count, taxonomy/geometry inputs, and prepare/preflight/run/summary mode.

**Output**

Limited benchmark files and reports/benchmark_summary.json when requested; preflight is read-only.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--root` | PATH | No | source default | Repository or experiment root containing the input tree. If omitted, the script uses its source-defined root path constant; pass an explicit path for a new run. |
| `--frame-count` | INT | No | source default | Canonical consecutive frame count (default: 100). If omitted, the script uses its source-defined frame count path constant; pass an explicit path for a new run. |
| `--prepare` | flag | No | None | Prepare benchmark inputs. |
| `--preflight` | flag | No | None | Validate an existing root without creating or changing files. |
| `--run` | flag | No | None | Execute the selected workload. |
| `--write-summary` | flag | No | None | Write reports/benchmark_summary.json from existing raw telemetry without rerunning stages. |
| `--install-fine-mapping` | flag | No | None | Install missing final fine taxonomy files; never overwrites them. |

**Existing files**

Input artifacts are read-only; diagnostic or validation destinations may be replaced.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/evaluation/run_gt_pointcloud_benchmark.py --root "$RUN_ROOT" --preflight
```


### `rt_out/scripts/evaluation/visualize_gt_scene_pointcloud.py`

**What it does**

Loads one GT scene point cloud, reports semantic/instance/material metadata, and optionally opens an Open3D view.

**When to run it**

Run for visual inspection of one frame or a frame-to-frame comparison after GT clouds exist.

**Required software**

Python 3 and NumPy; Open3D is used only by the GT visualization script.

**Input**

GT root, required frame, optional comparison frame, display mode, and camera/line options.

**Output**

Console counts/metadata and an optional Open3D view; no dataset artifact is created.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--root` | PATH | No | source default | Repository or experiment root containing the input tree. If omitted, the script uses its source-defined root path constant; pass an explicit path for a new run. |
| `--frame` | INT | Yes | None | First sparse frame ID, e.g. 0. |
| `--compare-frame` | INT | No | None | Second frame ID for ordered comparison. |
| `--mode` | VALUE | No | semantic | Operation or visualization mode. |
| `--lines-every` | INT | No | 0 | Motion-only: draw every Nth non-static displacement line. |
| `--no-view` | flag | No | None | Validate/report without opening Open3D. |

**Existing files**

Input artifacts are read-only; diagnostic or validation destinations may be replaced.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/evaluation/visualize_gt_scene_pointcloud.py --help
```


### `rt_out/scripts/experiment_paths.py`

**What it does**

Allocates a run-local log path and validates that an experiment root is suitable for operational output.

**When to run it**

Use before a shell process needs a unique run-local log path; run_gazebo_gpu.sh and run_all.sh call it.

**Required software**

Python 3 and the filesystem.

**Input**

Existing experiment root, relative log name, and optional timestamp flag.

**Output**

Creates the log parent and prints one allocated path; it does not create log contents.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--experiment-root` | PATH | Yes | None | Single run directory for generated outputs. Relative paths are resolved from the repository root; PIPELINE_RUN_DIR is accepted when this option is omitted. |
| `--log-name` | VALUE | Yes | None | Run-local relative log name. |
| `--timestamp` | flag | No | None | Allocate a timestamped non-colliding path. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/experiment_paths.py --experiment-root "$RUN_ROOT" --log-name ops/panda_pose.log --timestamp
```


### `rt_out/scripts/experiments/run_semantic_ablation.py`

**What it does**

Dispatches classical semantic-ablation jobs, validates result trees, and builds model-family or combined aggregates.

**When to run it**

Run after feature/label inputs and the canonical manifest exist; validate before release packaging.

**Required software**

Python 3, NumPy, scikit-learn for classical models, and Sionna RT only for the RT runner.

**Input**

Experiment root, task/view/model selectors, feature tables, target labels, and validation/aggregation scope.

**Output**

Job result trees, aggregate reports, validation diagnostics, and provenance metadata.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--config` | PATH | Yes | None | Path to experiment_config.json |
| `--target` | VALUE | Yes | None | Binary target column from the selected feature table |
| `--rx-filter` | LIST | No | None | Optional comma-separated RX ID filter, e.g. rx_panda_base,rx_ur5_base |
| `--feature-mode` | VALUE | No | wide | Feature subset mode. Default: wide |
| `--models` | LIST | No | logistic | Comma-separated model list. Supported: logistic,rf,svm,mlp. Default: logistic |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/experiments/run_semantic_ablation.py --help
```


### `rt_out/scripts/experiments/semantic_ablation/release_hardening.py`

- **Type:** Imported release-validation and transaction utility
- **Imported by:** Semantic-ablation runners and release-hardening tests.
- **Input:** Experiment manifests, invocation/provenance records, result trees, and candidate aggregate files.
- **Output:** Validation results, canonical hashes, manifest records, and transactional JSON/CSV operations at caller-selected paths.
- **Run directly:** No; it has no standalone CLI.

### `rt_out/scripts/experiments/semantic_ablation/semantic_ablation_build_canonical_horizon10_supervised_targets.py`

**What it does**

Builds the canonical horizon-10 supervised target table from aligned beam results and frame/index metadata.

**When to run it**

Run after canonical beam scores and the paired frame index exist and before feature/dataset validation.

**Required software**

Python 3, NumPy, scikit-learn for classical models, and Sionna RT only for the RT runner.

**Input**

Experiment root, canonical beam results, frame/source index, horizon definition, and target thresholds.

**Output**

Supervised target CSVs and target-audit metadata.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--root` | PATH | No | Path.cwd() | Repository or experiment root containing the input tree. |
| `--validate-only` | flag | No | None | Check existing files without regenerating them. |
| `--refresh-audit` | flag | No | None | Controls the refresh audit value used by this script. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/experiments/semantic_ablation/semantic_ablation_build_canonical_horizon10_supervised_targets.py --root "$RUN_ROOT" --validate-only
```


### `rt_out/scripts/experiments/semantic_ablation/semantic_ablation_build_gt_scene_pointcloud_smoke.py`

**What it does**

Validates the limited GT scene point-cloud smoke tree and optionally creates its small test dataset.

**When to run it**

Run for the smoke dataset only; use the recorded 2,446-frame run for validation, not generation.

**Required software**

Python 3, NumPy, scikit-learn for classical models, and Sionna RT only for the RT runner.

**Input**

Smoke root, expected frame count, taxonomy mapping, scene geometry, and generate/validation mode.

**Output**

Smoke PLY files, scene index, and reports in generate mode; validation mode reports without writing.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--generate` | flag | No | None | Build PLY outputs after the topology-only gate passes. |
| `--experiment-root` | PATH | No | source default | Existing run root containing this operation's manifests and outputs. If omitted, the script uses its source-defined experiment root path constant; pass an explicit path for a new run. |
| `--expected-frame-count` | INT | No | 10 | Controls the expected frame count value used by this script. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/experiments/semantic_ablation/semantic_ablation_build_gt_scene_pointcloud_smoke.py --experiment-root "$RUN_ROOT" --expected-frame-count 10
```


### `rt_out/scripts/experiments/semantic_ablation/semantic_ablation_extract_canonical_beam_scores.py`

**What it does**

Extracts a bounded canonical beam-score table and checks the selected frame interval and receiver rows.

**When to run it**

Run after canonical RT results exist and before building supervised targets.

**Required software**

Python 3, NumPy, scikit-learn for classical models, and Sionna RT only for the RT runner.

**Input**

Canonical beam-result files, frame bounds, receiver selection, and output location.

**Output**

Bounded beam-score CSV and validation metadata.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--start-frame` | INT | No | 0 | First source frame in the selected interval. |
| `--end-frame` | INT | No | N - 1 | Last source frame in the selected interval. |
| `--validate-only` | flag | No | None | Check existing files without regenerating them. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/experiments/semantic_ablation/semantic_ablation_extract_canonical_beam_scores.py --start-frame 0 --validate-only
```


### `rt_out/scripts/experiments/semantic_ablation/semantic_ablation_run_best_beam_power_regression.py`

- **Type:** Compatibility import module
- **Imported by:** Legacy callers using the semantic-ablation module path.
- **Input:** The public regression runner and its helper modules.
- **Output:** Re-exported regression entry points; it creates no result files.
- **Run directly:** No; use `rt_out/scripts/training/run_best_beam_power_regression.py`.

### `rt_out/scripts/experiments/semantic_ablation/semantic_ablation_run_classical_ml_ablation.py`

**What it does**

Runs and validates the classical semantic-ablation inventory, including release-gated model-family and combined aggregates.

**When to run it**

Run after descriptor/target inputs validate; use --validate-results before release summarization.

**Required software**

Python 3, NumPy, scikit-learn for classical models, and Sionna RT only for the RT runner.

**Input**

Experiment root, task/view/model selectors, feature/target inputs, invocation metadata, and smoke/full mode.

**Output**

Classical job directories, aggregate results, validation reports, and provenance manifests.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--root` | PATH | No | Path.cwd() | Repository or experiment root containing the input tree. |
| `--experiment-root` | PATH | No | None | Run root containing features/, beam_results/, and results/. |
| `--task` | VALUE | No | None | Task selecting the target and feature family. |
| `--view` | VALUE | No | None | Feature view or dataset representation to load. |
| `--model` | VALUE | No | None | Model family to run or validate. |
| `--smoke` | flag | No | None | Run the reduced smoke path. |
| `--run-all` | flag | No | None | Controls the run all value used by this script. |
| `--validate-only` | flag | No | None | Check existing files without regenerating them. |
| `--aggregate-combined` | flag | No | None | Controls the aggregate combined value used by this script. |
| `--validate-combined` | flag | No | None | Controls the validate combined value used by this script. |
| `--validate-results` | flag | No | None | Validate an existing result tree and its manifests. |
| `--validation-scope` | VALUE | No | model_family | Validation inventory scope. |
| `--force` | flag | No | None | Replace artifacts only for one explicit task/view/model job. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/experiments/semantic_ablation/semantic_ablation_run_classical_ml_ablation.py --experiment-root "$RUN_ROOT" --validate-results
```


### `rt_out/scripts/experiments/semantic_ablation/semantic_ablation_run_rbf_svm_ablation.py`

**What it does**

Runs and validates the RBF-SVM semantic-ablation inventory with release inventory and invocation checks.

**When to run it**

Run after RBF feature/target inputs validate; validate the complete model family before release packaging.

**Required software**

Python 3, NumPy, scikit-learn for classical models, and Sionna RT only for the RT runner.

**Input**

Experiment root, RBF feature/target inputs, task/view selectors, model inventory, and invocation metadata.

**Output**

RBF-SVM result directories, metrics, aggregate files, validation reports, and provenance manifests.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--root` | PATH | No | Path.cwd() | Repository or experiment root containing the input tree. |
| `--experiment-root` | PATH | No | None | Run root containing features/, beam_results/, and results/. |
| `--task` | VALUE | No | None | Task selecting the target and feature family. |
| `--view` | VALUE | No | None | Feature view or dataset representation to load. |
| `--smoke` | flag | No | None | Run the reduced smoke path. |
| `--run-all` | flag | No | None | Controls the run all value used by this script. |
| `--validate-results` | flag | No | None | Validate an existing result tree and its manifests. |
| `--force` | flag | No | None | Replace artifacts only for one explicit task/view job. |
| `--validation-scope` | VALUE | No | model_family | Validation inventory scope. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/experiments/semantic_ablation/semantic_ablation_run_rbf_svm_ablation.py --experiment-root "$RUN_ROOT" --validate-results
```


### `rt_out/scripts/experiments/semantic_ablation/semantic_ablation_run_sionna_rt_restart_safe.py`

**What it does**

Runs a bounded semantic RT preflight/probe and restart-safe workload, preserving staged rows and a final summary.

**When to run it**

Run after XML and RT runtime configuration validate; use --preflight or a bounded probe before a larger run.

**Required software**

Python 3, NumPy, scikit-learn for classical models, and Sionna RT only for the RT runner.

**Input**

Experiment root, XML/configuration, optional frame/receiver probe, and explicit preflight/run mode.

**Output**

Preflight/probe diagnostics, staging rows, progress metadata, and final RT outputs.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--root` | PATH | Yes | None | Repository or experiment root containing the input tree. |
| `--preflight` | flag | No | None | Validate inputs without running the workload. |
| `--run` | flag | No | None | Execute the selected workload. |
| `--probe-frame` | INT | No | None | Frame used by the RT probe. |
| `--probe-rx` | VALUE | No | None | Receiver used by the RT probe. |
| `--sionna-python` | PATH | No | None | Python executable used for Sionna RT. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/experiments/semantic_ablation/semantic_ablation_run_sionna_rt_restart_safe.py --root "$RUN_ROOT" --preflight
```


### `rt_out/scripts/experiments/semantic_ablation/test_release_hardening.py`

- **Type:** unittest module
- **Started by:** `python3 -m unittest rt_out.scripts.experiments.semantic_ablation.test_release_hardening`
- **Input:** Temporary synthetic manifests, invocations, result trees, and tampering fixtures.
- **Output:** Test results; fixtures are created below temporary directories.
- **Run directly:** No production workflow is executed.

### `rt_out/scripts/features/build_canonical_r1_r4_features.py`

**What it does**

Builds or validates the canonical R1, R2, R3, and R4 feature representations from aligned scene/RT inputs.

**When to run it**

Run after labeled point clouds, link context, and target alignment exist and before model training.

**Required software**

Python 3 and NumPy with the aligned feature, label, and point-cloud inputs.

**Input**

Feature config, aligned labels/point clouds, link context, and optional smoke frame count or validation mode.

**Output**

Canonical R1-R4 arrays, schema/index files, and validation reports.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--config` | PATH | Yes | None | Configuration file used to resolve inputs and output paths. |
| `--smoke-frames` | INT | No | None | Limit feature generation to a small frame count. |
| `--validate-only` | flag | No | None | Check existing files without regenerating them. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/features/build_canonical_r1_r4_features.py --help
```


### `rt_out/scripts/features/build_classical_ml_descriptors.py`

**What it does**

Builds the classical ML descriptor arrays for the configured frame interval and representation inputs.

**When to run it**

Run after canonical source features and labels exist and before classical model training.

**Required software**

Python 3 and NumPy with the aligned feature, label, and point-cloud inputs.

**Input**

Run root, frame interval, source feature/label arrays, and descriptor configuration.

**Output**

Classical descriptor arrays/index files and validation metadata.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--root` | PATH | No | Path.cwd() | Repository or experiment root containing the input tree. |
| `--start-frame` | INT | No | 0 | First source frame in the selected interval. |
| `--end-frame` | INT | No | N_SOURCE - 1 | Last source frame in the selected interval. |
| `--validate-only` | flag | No | None | Check existing files without regenerating them. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/features/build_classical_ml_descriptors.py --help
```


### `rt_out/scripts/features/build_object_features.py`

**What it does**

Builds object-aware feature arrays and object/index metadata from labeled scene records.

**When to run it**

Run after labeled point clouds and object registry exist and before object-aware training.

**Required software**

Python 3 and NumPy with the aligned feature, label, and point-cloud inputs.

**Input**

Feature config, object/semantic manifests, labeled scene data, and output locations.

**Output**

Object feature arrays, object index/metadata files, and validation summaries.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--config` | PATH | Yes | None | Path to experiment_config.json |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/features/build_object_features.py --help
```


### `rt_out/scripts/features/build_raw_occupancy_features.py`

**What it does**

Builds the raw occupancy baseline representation without semantic object channels.

**When to run it**

Run after aligned occupancy inputs exist when the raw baseline is needed for comparison.

**Required software**

Python 3 and NumPy with the aligned feature, label, and point-cloud inputs.

**Input**

Feature config, scene occupancy inputs, link context, frame selection, and output locations.

**Output**

Raw occupancy arrays, index/schema metadata, and validation summaries.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--config` | PATH | Yes | None | Path to experiment_config.json |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/features/build_raw_occupancy_features.py --help
```


### `rt_out/scripts/features/build_segmentation_ablation_voxels.py`

**What it does**

Builds segmentation-ablation sparse voxel representations at the selected voxel size.

**When to run it**

Run after labeled point clouds and link context are aligned; use --resolution-audit to inspect voxel-size effects.

**Required software**

Python 3 and NumPy with the aligned feature, label, and point-cloud inputs.

**Input**

Feature config, labeled scene inputs, link context, voxel size, smoke frames, and audit frame count.

**Output**

Sparse voxel arrays/indices, representation metadata, paired indexes, and validation/audit reports.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--config` | PATH | Yes | None | Configuration file used to resolve inputs and output paths. |
| `--voxel-size` | FLOAT | No | 0.04 | Voxel edge length for sparse voxel construction. |
| `--smoke-frames` | INT | No | None | Limit feature generation to a small frame count. |
| `--validate-only` | flag | No | None | Check existing files without regenerating them. |
| `--resolution-audit` | flag | No | None | Run the voxel-resolution comparison audit. |
| `--audit-frames` | INT | No | 30 | Frames sampled by the resolution audit. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/features/build_segmentation_ablation_voxels.py --config "$RUN_ROOT/config/experiment_config.json" --voxel-size 0.04 --validate-only
```


### `rt_out/scripts/ops/run_all.sh`

**What it does**

Starts Panda and UR5 motion publishers and records their Gazebo pose topics into run-local logs.

**When to run it**

Run after Gazebo serves Panda and UR5 and before parsing pose frames.

**Required software**

Bash, `gz`, Python 3 for `experiment_paths.py`, and a writable `PIPELINE_RUN_DIR`.

**Input**

PIPELINE_RUN_DIR; allocates ops/panda_pose.log and ops/ur5_pose.log and subscribes to /model/Panda/pose and /model/ur5_rg2/pose.

**Output**

Two run-local pose logs and child motion processes; the EXIT trap kills topic subscribers.

**Options**

No command-line options.

**Existing files**

Existing run-local logs are not silently overwritten; failures propagate to the caller.

**Continuing after interruption**

Inspect run-local logs and start a new process or run root rather than assuming completion.

**Example**

```bash
bash rt_out/scripts/ops/run_all.sh
```


### `rt_out/scripts/ops/run_gazebo_gpu.sh`

**What it does**

Sources GPU environment setup, launches gz sim, and redirects simulator output to a run-local log.

**When to run it**

Run after exporting PIPELINE_RUN_DIR and choosing a world SDF; it is the live simulator process.

**Required software**

Bash, `gz`, Python 3 for `experiment_paths.py`, and a writable `PIPELINE_RUN_DIR`.

**Input**

At least one positional world argument followed by optional gz sim arguments; PIPELINE_RUN_DIR selects the log root.

**Output**

An allocated gazebo/gazebo_sim.log and the foreground gz sim -v 4 -r process.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `<world.sdf>` | PATH | Yes | None | World SDF passed as the first argument to `gz sim`. |
| `[extra gz args...]` | TEXT | No | None | Additional arguments forwarded unchanged to `gz sim`. |

**Existing files**

Existing run-local logs are not silently overwritten; failures propagate to the caller.

**Continuing after interruption**

Inspect run-local logs and start a new process or run root rather than assuming completion.

**Example**

```bash
bash rt_out/scripts/ops/run_gazebo_gpu.sh ./myworld_rt.sdf
```


### `rt_out/scripts/ops/run_panda.sh`

**What it does**

Publishes Panda joint and gripper command messages that drive the configured motion sequence.

**When to run it**

Run while Gazebo is running and the Panda model is available; run_all.sh starts it as a child.

**Required software**

Bash, `gz`, and a writable `PIPELINE_RUN_DIR`.

**Input**

PIPELINE_RUN_DIR plus Panda topics such as /model/Panda/joint/<joint>/0/cmd_pos.

**Output**

Gazebo joint-command messages only; run_all.sh owns pose logging.

**Options**

No command-line options.

**Existing files**

Existing run-local logs are not silently overwritten; failures propagate to the caller.

**Continuing after interruption**

Inspect run-local logs and start a new process or run root rather than assuming completion.

**Example**

```bash
bash rt_out/scripts/ops/run_panda.sh
```


### `rt_out/scripts/ops/run_ur5.sh`

**What it does**

Publishes UR5 and RG2 joint command messages that drive the configured motion sequence.

**When to run it**

Run while Gazebo is running and the ur5_rg2 model is available; run_all.sh starts it as a child.

**Required software**

Bash, `gz`, and a writable `PIPELINE_RUN_DIR`.

**Input**

PIPELINE_RUN_DIR plus topics such as /model/ur5_rg2/joint/<joint>/0/cmd_pos.

**Output**

Gazebo joint-command messages only; run_all.sh owns pose logging.

**Options**

No command-line options.

**Existing files**

Existing run-local logs are not silently overwritten; failures propagate to the caller.

**Continuing after interruption**

Inspect run-local logs and start a new process or run root rather than assuming completion.

**Example**

```bash
bash rt_out/scripts/ops/run_ur5.sh
```


### `rt_out/scripts/ops/setup_gazebo_env.sh`

**What it does**

Exports repository model paths and NVIDIA rendering variables into the current shell.

**When to run it**

Source it once before run_gazebo_gpu.sh or another Gazebo process in the same shell.

**Required software**

Bash and the repository model directories; source this file into the current shell.

**Input**

Existing GZ_SIM_RESOURCE_PATH and IGN_GAZEBO_RESOURCE_PATH values plus repository model directories under models/.

**Output**

Updated GZ_SIM_RESOURCE_PATH, IGN_GAZEBO_RESOURCE_PATH, and NVIDIA/GL variables; no files are created.

**Options**

No command-line options.

**Existing files**

The script only modifies the shell environment; it does not create or overwrite files.

**Continuing after interruption**

Source it again in the shell that will launch the next Gazebo process.

**Example**

```bash
source rt_out/scripts/ops/setup_gazebo_env.sh
```


### `rt_out/scripts/perception/capture/build_labeled_gazebo_world.py`

**What it does**

Creates labeled Gazebo world variants for stable-instance panoptic capture, debug splits, or camera tuning.

**When to run it**

Run before Gazebo capture when a labeled world variant is missing or camera/debug options changed.

**Required software**

Python 3, NumPy, and the configured Gazebo/point-cloud dependencies for this perception stage.

**Input**

Perception config, base world/factory shell, camera settings, and selected world-build flags.

**Output**

Generated SDF/world directories for stable-instance, debug-split, or camera-tuning variants.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--config` | PATH | No | str(DEFAULT_CONFIG) | Perception dataset config JSON. |
| `--build-stable-instance-panoptic-world` | flag | No | None | Build an additional stable-instance panoptic world without changing the primary semantic panoptic world behavior. |
| `--build-debug-split-worlds` | flag | No | None | Also rebuild legacy semantic/instance split worlds under the experiment's legacy/ tree. |
| `--debug-camera-visuals` | flag | No | None | Also generate a debug-only native world with visible camera helpers for rig inspection. |
| `--camera-tuning-world` | flag | No | None | Also generate a movable camera-tuning world with real segmentation sensors plus visible helpers. |
| `--camera-helper-scale` | FLOAT | No | 1 | Scale factor for debug camera helper geometry. Default keeps helpers visible at room scale. |
| `--force` | flag | No | None | Overwrite generated native-world outputs. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/perception/capture/build_labeled_gazebo_world.py --help
```


### `rt_out/scripts/perception/capture/build_perception_instance_registry.py`

**What it does**

Builds a stable instance registry by combining selected perception frames with the semantic label map and static/actor metadata.

**When to run it**

Run after frame selection and label-map preparation and before live capture or reconstruction.

**Required software**

Python 3, NumPy, and the configured Gazebo/point-cloud dependencies for this perception stage.

**Input**

Selected-frame JSON/CSV, semantic label map, static registry/manifest, optional actor manifest, and output paths.

**Output**

Instance registry JSON, summary JSON, and optional review CSV.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--config` | PATH | No | source default | Configuration file used to resolve inputs and output paths. If omitted, the script uses its source-defined config path constant; pass an explicit path for a new run. |
| `--selected-frames` | PATH | No | None | Selected-frame file for perception capture. |
| `--semantic-label-map` | PATH | No | None | Semantic label map for stable instance records. |
| `--output` | PATH | No | None | Destination file or directory. |
| `--summary-output` | PATH | No | None | Destination summary for selected records. |
| `--review-csv` | PATH | No | None | Destination manual-review CSV. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/perception/capture/build_perception_instance_registry.py --help
```


### `rt_out/scripts/perception/capture/capture_panoptic_topics.py`

**What it does**

Captures configured Gazebo panoptic image topics for each camera and writes native topic frames plus capture metadata.

**When to run it**

Run after the labeled world and instance registry are ready while Gazebo publishes configured topics.

**Required software**

Python 3, NumPy, and the configured Gazebo/point-cloud dependencies for this perception stage.

**Input**

Perception config, panoptic mode, camera topics, message limit, timeout, and capture root.

**Output**

Per-camera panoptic images, topic metadata, capture summaries, and process diagnostics.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--config` | PATH | No | str(DEFAULT_CONFIG) | Perception dataset config JSON. |
| `--mode` | VALUE | No | panoptic | Capture panoptic topics from the active Gazebo-native world. |
| `--max-messages-per-topic` | INT | No | 5 | How many messages to save per topic. |
| `--timeout-seconds` | INT | No | 30 | Maximum topic capture duration. |
| `--force` | flag | No | None | Overwrite existing mode outputs and summary files. |
| `--no-build` | flag | No | None | Skip rebuilding the C++ capture utility. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Capture is not an implicit resume; validate completed groups and use a new capture root after interruption.

**Example**

```bash
python3 rt_out/scripts/perception/capture/capture_panoptic_topics.py --config "$RUN_ROOT/config/perception_dataset_config.json" --mode panoptic --no-build
```


### `rt_out/scripts/perception/capture/capture_synchronized_stable_instance_rgb_pcl.py`

**What it does**

Captures synchronized stable-instance labels, RGB images, and point clouds from Gazebo topics.

**When to run it**

Run after panoptic world/registry setup while Gazebo publishes synchronized camera topics.

**Required software**

Python 3, NumPy, and the configured Gazebo/point-cloud dependencies for this perception stage.

**Input**

Perception config, camera group limit, timeout, stride, synchronization tolerance, and capture root.

**Output**

Per-camera RGB/label/PCL files, metadata JSON, group summaries, and failure diagnostics.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--config` | PATH | No | str(DEFAULT_CONFIG) | Perception dataset config JSON. |
| `--max-groups-per-camera` | INT | No | 3 | How many synchronized label/RGB/PCL groups to save per camera. |
| `--timeout-seconds` | INT | No | 30 | Maximum capture duration. |
| `--stride` | INT | No | 4 | Stride over organized point-cloud pixels when writing PLY. |
| `--max-sync-delta-ms` | FLOAT | No | 50 | Maximum allowed label/RGB/PCL timestamp delta in milliseconds. |
| `--force` | flag | No | None | Overwrite existing synchronized stable-instance capture outputs and summaries. |
| `--no-build` | flag | No | None | Skip rebuilding the C++ capture utility. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Capture is not an implicit resume; validate completed groups and use a new capture root after interruption.

**Example**

```bash
python3 rt_out/scripts/perception/capture/capture_synchronized_stable_instance_rgb_pcl.py --help
```


### `rt_out/scripts/perception/capture/cpp/build_capture_segmentation_topics.sh`

**What it does**

Compiles the panoptic segmentation-topic capture helper.

**When to run it**

Run before `capture_panoptic_topics.py` when the helper binary is missing or the C++ source changed.

**Required software**

Bash, pkg-config, a compiler chosen from g++, clang++, or gcc, gz-transport/gz-msgs, and optional opencv4.

**Input**

`capture_segmentation_topics.cpp` in the same directory plus the pkg-config development packages.

**Output**

`capture_segmentation_topics` beside the source; the compile command replaces an existing binary.

**Options**

No command-line options.

**Existing files**

The compile command replaces the binary at its fixed output path; a failed compile leaves no usable helper.

**Continuing after interruption**

Rerun the build after source or dependency changes; the parent capture script checks that the resulting binary exists.

**Example**

```bash
bash rt_out/scripts/perception/capture/cpp/build_capture_segmentation_topics.sh
```


### `rt_out/scripts/perception/capture/cpp/build_capture_synchronized_stable_instance_rgb_pcl_topics.sh`

**What it does**

Compiles the synchronized RGB, label, and PCL capture helper.

**When to run it**

Run before synchronized capture when the helper binary is missing or the C++ source changed.

**Required software**

Bash, pkg-config, a compiler chosen from g++, clang++, or gcc, gz-transport/gz-msgs, and optional opencv4.

**Input**

`capture_synchronized_stable_instance_rgb_pcl_topics.cpp` plus the pkg-config development packages.

**Output**

`capture_synchronized_stable_instance_rgb_pcl_topics` beside the source; the compile command replaces an existing binary.

**Options**

No command-line options.

**Existing files**

The compile command replaces the binary at its fixed output path; a failed compile leaves no usable helper.

**Continuing after interruption**

Rerun the build after source or dependency changes; the parent capture script checks that the resulting binary exists.

**Example**

```bash
bash rt_out/scripts/perception/capture/cpp/build_capture_synchronized_stable_instance_rgb_pcl_topics.sh
```


### `rt_out/scripts/perception/capture/cpp/capture_segmentation_topics.cpp`

- **Type:** C++ Gazebo Transport image-capture helper
- **Compiled by:** `build_capture_segmentation_topics.sh`
- **Started by:** `capture_panoptic_topics.py` when native topic capture is enabled.
- **Gazebo topics read:** Image topics supplied with `--topic`; the topic path identifies camera and map type.
- **Files or messages written:** Per-camera PPM/PGM/PGM16 files, metadata JSON, and a JSON status record on stdout below `--output-root`.
- **Standalone execution:** No; the Python capture script supplies the topic list and output root.

### `rt_out/scripts/perception/capture/cpp/capture_synchronized_stable_instance_rgb_pcl_topics.cpp`

- **Type:** C++ Gazebo Transport synchronized RGB/label/PCL capture helper
- **Compiled by:** `build_capture_synchronized_stable_instance_rgb_pcl_topics.sh`
- **Started by:** `capture_synchronized_stable_instance_rgb_pcl.py` for each configured camera group.
- **Gazebo topics read:** Stable-instance labels/colored maps, RGB images, and `PointCloudPacked` topics supplied by the parent.
- **Files or messages written:** Synchronized label/RGB images, PLY point clouds, metadata JSON, and a JSON status record on stdout below `--output-root`.
- **Standalone execution:** No; the Python capture script validates topic counts and supplies the output root.

### `rt_out/scripts/perception/capture/extract_camera_rig_from_gazebo_pose.py`

**What it does**

Converts a Gazebo pose log into the camera-rig JSON expected by the perception pipeline.

**When to run it**

Run after the camera pose log exists and before capture validation or reconstruction.

**Required software**

Python 3, NumPy, and the configured Gazebo/point-cloud dependencies for this perception stage.

**Input**

Pose log, rig template, camera naming/configuration, and output JSON.

**Output**

Resolved camera-rig JSON with camera poses and source-log metadata.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--config` | PATH | No | str(DEFAULT_CONFIG) | Perception dataset config JSON. |
| `--pose-log` | VALUE | Yes | None | Text file copied from gz topic pose output. |
| `--template-rig` | VALUE | No | None | Optional camera rig JSON used as the output template. |
| `--output-json` | VALUE | No | None | Optional output JSON path for the extracted camera rig snippet. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/perception/capture/extract_camera_rig_from_gazebo_pose.py --help
```


### `rt_out/scripts/perception/capture/preview_panoptic_capture.py`

**What it does**

Reads a panoptic capture and opens or reports a preview of selected camera frames.

**When to run it**

Run after panoptic capture exists to inspect labels, alignment, and metadata before validation.

**Required software**

Python 3, NumPy, and the configured Gazebo/point-cloud dependencies for this perception stage.

**Input**

Perception config, capture root, selected camera/frame settings, and preview controls.

**Output**

Preview output and console diagnostics; canonical capture artifacts are not generated.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--config` | PATH | No | str(DEFAULT_CONFIG) | Perception dataset config JSON. |
| `--force` | flag | No | None | Overwrite existing preview outputs. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/perception/capture/preview_panoptic_capture.py --help
```


### `rt_out/scripts/perception/capture/run_gazebo_capture_helper.py`

**What it does**

Optionally launches Gazebo and the configured motion helper for a perception capture attempt.

**When to run it**

Run after labeled world, capture config, and motion script are ready for a controlled live capture.

**Required software**

Python 3, NumPy, and the configured Gazebo/point-cloud dependencies for this perception stage.

**Input**

Perception config, capture mode, motion script, Gazebo executable, GUI flag, timeout, and run root.

**Output**

Launched Gazebo/motion processes and their run-local logs/capture outputs.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--config` | PATH | No | str(DEFAULT_CONFIG) | Perception dataset config JSON. |
| `--mode` | VALUE | No | panoptic | Which native world variant to run. |
| `--run-motion` | flag | No | None | Run the configured motion script while Gazebo is alive. |
| `--motion-script` | VALUE | No | str(DEFAULT_MOTION_SCRIPT) | Motion script to run when --run-motion is enabled. |
| `--gazebo-bin` | VALUE | No | gz | Gazebo executable to invoke. |
| `--gui` | flag | No | None | Run Gazebo with the GUI path instead of server-only mode. |
| `--timeout-seconds` | INT | No | 240 | Maximum duration for each capture run. |
| `--force` | flag | No | None | Overwrite selected capture outputs and logs. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/perception/capture/run_gazebo_capture_helper.py --help
```


### `rt_out/scripts/perception/capture/select_perception_frames.py`

**What it does**

Selects a bounded or strided set of source frames for the perception capture run.

**When to run it**

Run before registry construction, labeled-world generation, and live topic capture.

**Required software**

Python 3, NumPy, and the configured Gazebo/point-cloud dependencies for this perception stage.

**Input**

Source frame records, frame count, stride, and output/summary paths.

**Output**

Selected-frame JSON/CSV and a selection summary.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--config` | PATH | No | source default | Perception dataset config JSON path. If omitted, the script uses its source-defined config path constant; pass an explicit path for a new run. |
| `--source-frames` | PATH | No | None | Optional override for the source sampled_frames JSON. |
| `--output` | PATH | No | None | Optional override for selected_frames.json output path. |
| `--summary-output` | PATH | No | None | Optional override for selected_frames_summary.json output path. |
| `--frame-count` | INT | No | None | Optional override for the number of selected frames. |
| `--stride` | INT | No | None | Optional override for every-nth selection stride. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/perception/capture/select_perception_frames.py --help
```


### `rt_out/scripts/perception/capture/validate_panoptic_capture.py`

**What it does**

Validates native panoptic topic captures, expected message counts, image dimensions, and zero-label rates.

**When to run it**

Run after capture_panoptic_topics.py completes and before instance reconstruction.

**Required software**

Python 3, NumPy, and the configured Gazebo/point-cloud dependencies for this perception stage.

**Input**

Perception config, camera capture files, expected message count, zero threshold, and diagnostic options.

**Output**

Validation summary and optional per-camera diagnostics.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--config` | PATH | No | str(DEFAULT_CONFIG) | Perception dataset config JSON. |
| `--zero-threshold` | FLOAT | No | source default | Maximum allowed zero-label ratio per semantic-decoded mask. Label 0 is invalid/unlabeled. If omitted, the script uses its source-defined zero threshold path constant; pass an explicit path for a new run. |
| `--expected-messages-per-camera` | INT | No | source default | Expected decoded panoptic message count per camera. If omitted, the script uses its source-defined expected messages per camera path constant; pass an explicit path for a new run. |
| `--write-diagnostics` | flag | No | None | Also write supplementary histogram and invalid-pixel CSV diagnostics. |

**Existing files**

Input artifacts are read-only; diagnostic or validation destinations may be replaced.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/perception/capture/validate_panoptic_capture.py --config "$RUN_ROOT/config/perception_dataset_config.json"
```


### `rt_out/scripts/perception/capture/validate_synchronized_stable_instance_rgb_pcl.py`

**What it does**

Validates synchronized RGB/label/PCL groups, point counts, timestamps, and synchronization deltas.

**When to run it**

Run after synchronized capture completes and before building labeled point clouds.

**Required software**

Python 3, NumPy, and the configured Gazebo/point-cloud dependencies for this perception stage.

**Input**

Perception config, expected groups, minimum PCL points, maximum sync delta, and capture files.

**Output**

Synchronized-capture validation summary with per-camera/group diagnostics.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--config` | PATH | No | str(DEFAULT_CONFIG) | Perception dataset config JSON. |
| `--expected-groups-per-camera` | INT | No | 3 | Expected synchronized group count per camera. |
| `--min-points-per-cloud` | INT | No | 1000 | Minimum point count required per synchronized PLY. |
| `--max-sync-delta-ms` | FLOAT | No | 50 | Maximum allowed label/RGB/PCL timestamp delta in milliseconds. |

**Existing files**

Input artifacts are read-only; diagnostic or validation destinations may be replaced.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/perception/capture/validate_synchronized_stable_instance_rgb_pcl.py --help
```


### `rt_out/scripts/perception/reconstruction/build_labeled_colorized_point_cloud.py`

**What it does**

Combines synchronized RGB/PCL data with stable-instance labels and writes labeled, colorized PLY clouds.

**When to run it**

Run after synchronized capture validation and before building the panoptic dataset index.

**Required software**

Python 3, NumPy, and the configured Gazebo/point-cloud dependencies for this perception stage.

**Input**

Perception config, synchronized capture root, frame/camera filters, and output directory.

**Output**

Labeled/colorized PLY files, per-cloud metadata, and reconstruction summaries.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--config` | PATH | No | source default | Perception dataset config JSON. If omitted, the script uses its source-defined config path constant; pass an explicit path for a new run. |
| `--sync-root` | PATH | No | None | Root directory containing synchronized stable-instance RGB/PCL capture outputs. |
| `--output-dir` | PATH | No | None | Output directory for final labeled colorized point clouds. |
| `--frame-filter` | TEXT | No | None | Optional comma-separated selected_frame_id filter, e.g. 0,1,2. |
| `--camera-filter` | TEXT | No | None | Optional comma-separated camera_id filter. |
| `--force` | flag | No | None | Overwrite output directory. |
| `--pretty-json` | flag | No | None | Pretty-print JSON outputs. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/perception/reconstruction/build_labeled_colorized_point_cloud.py --help
```


### `rt_out/scripts/perception/reconstruction/build_panoptic_dataset_index.py`

**What it does**

Builds CSV and JSON indexes for labeled panoptic point clouds and can join RT labels and source-experiment metadata.

**When to run it**

Run after labeled/colorized clouds exist and their validation passes.

**Required software**

Python 3, NumPy, and the configured Gazebo/point-cloud dependencies for this perception stage.

**Input**

Dataset config, labeled root, optional source experiment, RT CSV, labels CSV, strict/max-row settings, and output directory.

**Output**

Panoptic dataset CSV/JSON indexes and a summary of included rows.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--config` | PATH | Yes | None | Perception dataset config JSON path. |
| `--output-dir` | PATH | No | None | Optional override for output directory. Defaults to <experiment_root>/dataset_index. |
| `--source-experiment` | PATH | No | None | Optional override for the source RT experiment directory. |
| `--rt-csv` | PATH | No | None | Optional explicit RT CSV path. |
| `--labels-csv` | PATH | No | None | Optional explicit labels CSV path. |
| `--force` | flag | No | None | Overwrite existing outputs. |
| `--strict` | flag | No | None | Treat missing expected files or RT links as errors. |
| `--pretty-json` | flag | No | None | Write indented JSON outputs. |
| `--max-rows` | INT | No | None | Optional debug limit applied after candidate frame-camera rows are built. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/perception/reconstruction/build_panoptic_dataset_index.py --config "$RUN_ROOT/config/perception_dataset_config.json" --strict
```


### `rt_out/scripts/perception/reconstruction/validate_labeled_colorized_point_cloud.py`

**What it does**

Checks that each labeled/colorized PLY exists, has the expected count, and meets the minimum point threshold.

**When to run it**

Run after point-cloud reconstruction and before indexing or packaging.

**Required software**

Python 3, NumPy, and the configured Gazebo/point-cloud dependencies for this perception stage.

**Input**

Perception config, labeled root, expected cloud count, and minimum points per cloud.

**Output**

Console validation status and per-cloud diagnostics; --dry-run reports without writing.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--config` | PATH | No | source default | Perception dataset config JSON. If omitted, the script uses its source-defined config path constant; pass an explicit path for a new run. |
| `--labeled-root` | PATH | No | None | Root directory containing final labeled point-cloud outputs. |
| `--expected-cloud-count` | INT | Yes | None | Expected number of valid labeled point clouds. |
| `--min-points-per-cloud` | INT | No | 1000 | Minimum point count required per final labeled cloud. |

**Existing files**

Input artifacts are read-only; diagnostic or validation destinations may be replaced.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/perception/reconstruction/validate_labeled_colorized_point_cloud.py --help
```


### `rt_out/scripts/perception/run_perception_pipeline.py`

**What it does**

Runs the ordered perception stages or prints their commands in --dry-run mode.

**When to run it**

Run after perception config is resolved; use --dry-run to inspect stage order before live capture.

**Required software**

Python 3, NumPy, and the configured Gazebo/point-cloud dependencies for this perception stage.

**Input**

Perception config, expected cloud count, and stage flags forwarded to capture/validation/reconstruction.

**Output**

Selected-frame, registry, capture, validation, reconstruction, and index outputs unless --dry-run is used.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--config` | PATH | Yes | None | Run-local perception dataset config JSON. |
| `--expected-cloud-count` | INT | Yes | None | Expected final labeled point-cloud count for validation, e.g. 24 for the pilot. |
| `--min-points-per-cloud` | INT | No | 1000 | Minimum point count per cloud. |
| `--force` | flag | No | None | Forward overwrite permission to stages that support it. |
| `--dry-run` | flag | No | None | Print the ordered commands without executing them. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/perception/run_perception_pipeline.py --config "$RUN_ROOT/config/perception_dataset_config.json" --expected-cloud-count 24 --dry-run
```


### `rt_out/scripts/rt/build_rt_labels.py`

**What it does**

Builds temporal wireless labels and canonical target columns from validated RT rows.

**When to run it**

Run after RT CSV and paired frame/index inputs validate and before feature/model training.

**Required software**

Python 3 and the XML/manifest inputs; Sionna RT is required only for RT execution.

**Input**

Experiment config, RT CSV, frame/source index, horizon/threshold settings, and output locations.

**Output**

Label CSV plus target-audit metadata.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--config` | PATH | Yes | None | Path to experiment_config.json |
| `--eta-tau` | FLOAT | No | None | Override the delay-spread increase threshold. Default: 0.25 * std(delay_spread). |
| `--allow-failed` | flag | No | None | Allow rows with sanity_ok != True to be skipped instead of failing. |
| `--horizon-frames` | INT | No | 1 | Temporal target horizon; default preserves consecutive-frame labels. |
| `--one-second-split` | flag | No | None | Apply the fixed 2446-frame chronological split for a 10-frame horizon. |
| `--validate-only` | flag | No | None | Validate the canonical 1-second input/output contract without writing files. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/rt/build_rt_labels.py --config "$RUN_ROOT/config/experiment_config.json" --horizon-frames 10 --validate-only
```


### `rt_out/scripts/rt/build_sionna_xml_batch.py`

**What it does**

Generates one package-relative Sionna XML scene per composed frame and records an XML index.

**When to run it**

Run after composed manifests, static geometry, material mappings, and radio configuration validate.

**Required software**

Python 3 and the XML/manifest inputs; Sionna RT is required only for RT execution.

**Input**

Experiment config, composed manifests, material config, static/dynamic/actor PLYs, and frame selection.

**Output**

Per-frame XML files plus an XML index and generation metadata.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--config` | PATH | Yes | None | Path to experiment_config.json |
| `--no-progress` | flag | No | None | Disable progress bars / periodic progress prints. |
| `--progress-every` | INT | No | 10 | Fallback text progress print frequency when tqdm is unavailable. |
| `--max-frames` | INT | No | None | Optional debug limit on the number of composed-manifest rows to process. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/rt/build_sionna_xml_batch.py --config "$RUN_ROOT/config/experiment_config.json" --no-progress
```


### `rt_out/scripts/rt/run_rt_multi_rx_batch.py`

**What it does**

Runs Sionna RT for frame/receiver jobs and collects compact link-feature rows.

**When to run it**

Run after XML batch and radio-site inputs validate; keep this root isolated from other RT attempts.

**Required software**

Python 3 and the XML/manifest inputs; Sionna RT is required only for RT execution.

**Input**

Experiment config, XML index, TX/RX/radio sites, frequency, job limits, and output root.

**Output**

RT CSV rows, staging/progress metadata, per-job diagnostics, and aggregate validation reports.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--config` | PATH | Yes | None | Path to experiment_config.json |
| `--continue-on-error` | flag | No | None | Continue collecting rows after a failing XML/RX run instead of failing fast. |
| `--max-frames` | INT | No | None | Optional debug limit on the number of XML frames to process. |
| `--max-rows` | INT | No | None | Optional debug limit on the total number of XML/RX rows to process. |
| `--no-progress` | flag | No | None | Disable progress bars / periodic progress prints. |
| `--progress-every` | INT | No | 10 | Fallback text progress print frequency when tqdm is unavailable. |
| `--sionna-python` | PATH | No | None | Optional explicit Python interpreter with Sionna RT/Mitsuba installed. Defaults to SIONNA_PYTHON, then the legacy COLLABPAPER_PYTHON, then the current interpreter if it already imports sionna.rt. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/rt/run_rt_multi_rx_batch.py --config "$RUN_ROOT/config/experiment_config.json" --sionna-python "$SIONNA_PYTHON"
```


### `rt_out/scripts/rt_material_config.py`

- **Type:** Imported material-mapping loader
- **Imported by:** Static/dynamic XML builders, mesh exporters, and RT sanity scripts.
- **Input:** RT material mapping JSON and source material names.
- **Output:** Normalized material assignments and lookup helpers in memory.
- **Run directly:** No; importing it does not write scene files.

### `rt_out/scripts/runtime_config.py`

- **Type:** Imported executable/runtime resolver
- **Imported by:** Gazebo, Blender, Sionna, and RT orchestration scripts.
- **Input:** Runtime configuration values and environment overrides.
- **Output:** Resolved executable paths and runtime settings in memory.
- **Run directly:** No; it does not start the resolved programs.

### `rt_out/scripts/static_scene/build_scene_geometry_registry.py`

**What it does**

Builds the geometry registry from the configured static manifest and resolved mesh records.

**When to run it**

Run after static_manifest.json and converted mesh paths exist and before static material merging.

**Required software**

Python 3, SDF/JSON parsing, repository meshes, and Blender or Sionna RT only for the conversion/RT stages.

**Input**

Configured STATIC_MANIFEST_PATH and its resolved mesh/material records; there is no path CLI.

**Output**

Geometry registry at the source-defined registry location.

**Options**

No command-line options.

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/static_scene/build_scene_geometry_registry.py
```


### `rt_out/scripts/static_scene/build_static_mitsuba_xml.py`

**What it does**

Serializes the merged static scene manifest and material assignments into Mitsuba XML.

**When to run it**

Run after merged static PLYs and their manifest validate when a Mitsuba-compatible scene is needed.

**Required software**

Python 3, SDF/JSON parsing, repository meshes, and Blender or Sionna RT only for the conversion/RT stages.

**Input**

Merged static manifest, material mapping, optional TX/RX/camera settings, and output XML path.

**Output**

One static Mitsuba XML with shape references and material BSDF assignments.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--manifest` | PATH | No | None | Path to merged_static_manifest.json |
| `--output` | PATH | No | None | Output XML path |
| `--geometry-only` | flag | No | None | Write only mesh shapes without camera, emitter, or integrator |
| `--camera-origin` | VALUE | No | 12, 12, 8 | Inspection camera origin. |
| `--camera-target` | VALUE | No | 0, 0, 1 | Inspection camera target. |
| `--camera-up` | VALUE | No | 0, 0, 1 | Inspection camera up vector. |
| `--width` | INT | No | 1280 | Inspection window width. |
| `--height` | INT | No | 720 | Inspection window height. |
| `--spp` | INT | No | 16 | Inspection samples per pixel. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/static_scene/build_static_mitsuba_xml.py --help
```


### `rt_out/scripts/static_scene/build_static_scene_registry.py`

**What it does**

Builds the static scene registry from the geometry registry and material mapping.

**When to run it**

Run after geometry registry and RT material mapping exist and before static XML generation.

**Required software**

Python 3, SDF/JSON parsing, repository meshes, and Blender or Sionna RT only for the conversion/RT stages.

**Input**

Configured geometry registry and material mapping; there is no path CLI.

**Output**

Static scene registry at the source-defined registry location.

**Options**

No command-line options.

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/static_scene/build_static_scene_registry.py
```


### `rt_out/scripts/static_scene/build_static_sionna_xml.py`

**What it does**

Serializes the merged static scene manifest into package-relative Sionna XML.

**When to run it**

Run after merged static geometry, static registry, and material definitions validate and before RT.

**Required software**

Python 3, SDF/JSON parsing, repository meshes, and Blender or Sionna RT only for the conversion/RT stages.

**Input**

Merged static manifest, material mapping, XML options, and selected output path.

**Output**

One static Sionna XML whose shape paths and material assignments match the manifest.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--manifest` | PATH | No | None | Path to merged_static_manifest.json |
| `--output` | PATH | No | None | Output Sionna XML path |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/static_scene/build_static_sionna_xml.py --manifest "$STATIC_ROOT/static_scene/export/merged_static_manifest.json" --output "$STATIC_ROOT/static_scene/export/static_scene_sionna.xml"
```


### `rt_out/scripts/static_scene/convert_dae_to_ply_blender.py`

- **Type:** Blender conversion worker
- **Started by:** `rt_out/scripts/static_scene/merge_static_scene_by_material.py`
- **Input:** Blender arguments identifying one DAE mesh and one output PLY.
- **Output:** One converted PLY plus conversion status.
- **Run directly:** No; the parent controls the worker invocation.

### `rt_out/scripts/static_scene/convert_mesh_to_ply_blender.py`

- **Type:** Blender conversion worker
- **Started by:** `rt_out/scripts/static_scene/merge_static_scene_by_material.py`
- **Input:** Blender arguments identifying one source mesh and one output PLY.
- **Output:** One converted PLY plus conversion status.
- **Run directly:** No; the parent controls the worker invocation.

### `rt_out/scripts/static_scene/extract_scene_manifests.py`

**What it does**

Parses the world SDF into static and dynamic scene manifests with resolved model/link/visual records.

**When to run it**

Run as the first static-scene step, before registry construction or mesh conversion.

**Required software**

Python 3, SDF/JSON parsing, repository meshes, and Blender or Sionna RT only for the conversion/RT stages.

**Input**

World SDF, models root, optional experiment configuration, and output directory.

**Output**

Static and dynamic manifest JSON files plus extraction metadata.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--root` | PATH | No | source default | Repository root containing myworld_rt.sdf and models/. If omitted, the script uses its source-defined root path constant; pass an explicit path for a new run. |
| `--sdf` | PATH | No | None | Explicit SDF world path. |
| `--models-root` | PATH | No | None | Explicit model asset root. |
| `--experiment-root` | PATH | No | None | Run root used to resolve config/ and manifests/. |
| `--dynamic-prototype-config` | PATH | No | None | Dynamic prototype config loaded after CLI parsing. |
| `--output-dir` | PATH | No | None | Output directory for static_manifest.json and dynamic_manifest.json. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/static_scene/extract_scene_manifests.py --root "$REPO_ROOT" --sdf "$REPO_ROOT/myworld_rt.sdf" --models-root "$REPO_ROOT/models" --experiment-root "$STATIC_ROOT" --output-dir "$STATIC_ROOT/manifests"
```


### `rt_out/scripts/static_scene/merge_static_scene_by_material.py`

**What it does**

Converts static meshes and merges them by RT material, coordinating Blender workers and manifest creation.

**When to run it**

Run after static manifests and geometry registry validate and before static XML generation.

**Required software**

Python 3, SDF/JSON parsing, repository meshes, and Blender or Sionna RT only for the conversion/RT stages.

**Input**

Static/geometry registries, model meshes, material mapping, output directory, Blender executable, and export flags.

**Output**

Converted PLYs, material-merged PLYs, merged static manifest, output metadata, and optional individual meshes.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--registry` | PATH | No | None | Path to static_registry.json |
| `--out-dir` | PATH | No | None | Output directory for merged static scene data |
| `--blender` | PATH | No | None | Path to the Blender executable. Defaults to BLENDER, PATH, then repo-local candidates. |
| `--helper` | PATH | No | None | Path to the Blender helper script |
| `--export-individual` | flag | No | None | Also export transformed per-entry debug meshes |
| `--manifest-name` | VALUE | No | merged_static_manifest.json | Output manifest filename inside --out-dir |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/static_scene/merge_static_scene_by_material.py --registry "$STATIC_ROOT/manifests/static_registry.json" --out-dir "$STATIC_ROOT/static_scene/export" --blender "$BLENDER" --helper rt_out/scripts/static_scene/static_scene_blender_merge_worker.py
```


### `rt_out/scripts/static_scene/run_sionna_rt_sanity.py`

**What it does**

Loads the static Sionna scene and runs a small one-scene RT diagnostic for configured TX/RX positions.

**When to run it**

Run after static XML and runtime configuration validate, before a production RT batch.

**Required software**

Python 3, SDF/JSON parsing, repository meshes, and Blender or Sionna RT only for the conversion/RT stages.

**Input**

Static XML, TX/RX positions, path-depth/sample limits, frequency, and optional runtime settings.

**Output**

Console diagnostic metrics and a selected diagnostic output separate from the release RT tree.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--xml` | PATH | No | source default | Path to static_scene_sionna.xml If omitted, the script uses its source-defined xml path constant; pass an explicit path for a new run. |
| `--tx` | lambda value: parse_vec3(value, field='--tx') | No | source default | Transmitter position as x,y,z in meters If omitted, the script uses its source-defined tx path constant; pass an explicit path for a new run. |
| `--rx` | lambda value: parse_vec3(value, field='--rx') | No | source default | Receiver position as x,y,z in meters If omitted, the script uses its source-defined rx path constant; pass an explicit path for a new run. |
| `--max-depth` | INT | No | 2 | Maximum RT path depth. |
| `--samples-per-src` | INT | No | 20000 | RT samples per source position. |
| `--max-num-paths-per-src` | INT | No | 10000 | Maximum RT paths per source. |
| `--seed` | INT | No | 42 | Random seed recorded in result metadata. |
| `--frequency-hz` | FLOAT | No | None | Carrier frequency in Hz. Defaults to the legacy run's resolved RT material config metadata.carrier_frequency_hz. |
| `--enable-refraction` | flag | No | None | Enable refraction. Disabled by default for this first sanity check. |
| `--use-fallback-variant` | flag | No | None | Use the configured fallback scene/runtime variant. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/static_scene/run_sionna_rt_sanity.py --xml "$STATIC_ROOT/static_scene/export/static_scene_sionna.xml"
```


### `rt_out/scripts/static_scene/static_scene_blender_merge_worker.py`

- **Type:** Blender merge worker
- **Started by:** `rt_out/scripts/static_scene/merge_static_scene_by_material.py`
- **Input:** Merge specification JSON with static mesh records, material groups, and destinations.
- **Output:** Material-merged PLY files, merged manifest data, and worker status.
- **Run directly:** No; the parent supplies the worker specification.

### `rt_out/scripts/static_scene/validate_scene_manifests.py`

**What it does**

Validates static/dynamic manifest schemas, asset resolution, mesh paths, counts, and scene assumptions.

**When to run it**

Run immediately after manifest extraction and after geometry path migration or registry changes.

**Required software**

Python 3, SDF/JSON parsing, repository meshes, and Blender or Sionna RT only for the conversion/RT stages.

**Input**

Experiment root or explicit manifests plus model/geometry roots used for path resolution.

**Output**

Console validation status and a validation report.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--experiment-root` | PATH | No | None | Existing run root containing this operation's manifests and outputs. |
| `--dynamic-prototype-config` | PATH | No | None | Dynamic timing and model configuration. |

**Existing files**

Input artifacts are read-only; diagnostic or validation destinations may be replaced.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/static_scene/validate_scene_manifests.py --experiment-root "$STATIC_ROOT"
```


### `rt_out/scripts/training/add_per_rx_median_baseline.py`

**What it does**

Adds and evaluates the per-receiver median baseline against regression target rows.

**When to run it**

Run after regression targets/features validate when the per-RX baseline is part of the comparison set.

**Required software**

Python 3, NumPy, and the model/data dependencies selected by the training mode.

**Input**

Experiment root with aligned target rows and per-receiver training/evaluation splits.

**Output**

Per-RX median predictions, metrics, result metadata, and provenance.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--experiment-root` | PATH | Yes | None | Existing run root containing this operation's manifests and outputs. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Validate completed jobs first and rerun only missing or failed jobs with unchanged input hashes.

**Example**

```bash
python3 rt_out/scripts/training/add_per_rx_median_baseline.py --help
```


### `rt_out/scripts/training/best_beam_power_regression.py`

- **Type:** Imported regression data-preparation module
- **Imported by:** `rt_out/scripts/training/run_best_beam_power_regression.py` and regression tests.
- **Input:** Aligned feature/target CSV and array files plus representation/target settings.
- **Output:** Targets, aligned arrays, temporal splits, metrics, source-path records, and CSV/JSON operations used by the runner.
- **Run directly:** No; it does not define the regression CLI.

### `rt_out/scripts/training/run_best_beam_power_regression.py`

**What it does**

Runs the best-beam power regression inventory, validates result trees, and writes release-aware summaries.

**When to run it**

Use audit/build/input-validation modes before fitting and result validation before release summarization.

**Required software**

Python 3, NumPy, and the model/data dependencies selected by the training mode.

**Input**

Experiment root, aligned feature/target files, execution mode, representations/models, seed, and provenance inputs.

**Output**

Predictions, serialized models, metrics, provenance/artifact manifests, and best_model_summary.csv.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--experiment-root` | PATH | Yes | None | Existing run root containing this operation's manifests and outputs. |
| `--audit-target` | flag | No | None | Inspect target construction inputs and stop. |
| `--build-targets` | flag | No | None | Build supervised targets and stop. |
| `--validate-inputs` | flag | No | None | Validate aligned feature and target inputs. |
| `--validate-results` | flag | No | None | Validate an existing result tree and its manifests. |
| `--dry-run` | flag | No | None | Report the planned operation without starting the workload. |
| `--smoke` | flag | No | None | Run the reduced smoke path. |
| `--full` | flag | No | None | Run the complete configured inventory. |
| `--summarize-results` | flag | No | None | Write the best-model summary transactionally. |
| `--result-mode` | VALUE | No | full | Regression result tree, such as smoke or full. |
| `--representation` | VALUE | No | None | Feature representation; repeat for each selection. |
| `--model` | VALUE | No | None | Model family to run or validate. |
| `--seed` | INT | No | 42 | Random seed recorded in result metadata. |
| `--force` | flag | No | None | Allow replacement of an output that normal checks would reject. |
| `--allow-legacy-summary` | flag | No | None | Allow a non-release summary for provenance-missing results. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Validate completed jobs first and rerun only missing or failed jobs with unchanged input hashes.

**Example**

```bash
python3 rt_out/scripts/training/run_best_beam_power_regression.py --experiment-root "$RUN_ROOT" --smoke --result-mode smoke --representation G --model ridge
```


### `rt_out/scripts/training/test_best_beam_power_regression.py`

- **Type:** unittest module
- **Started by:** `python3 -m unittest rt_out.scripts.training.test_best_beam_power_regression`
- **Input:** Temporary regression fixtures and tampered result trees.
- **Output:** Test results; temporary files are isolated from experiment artifacts.
- **Run directly:** No production regression is run.

### `rt_out/scripts/training/train_segmentation_smoke.py`

**What it does**

Trains or checks the small sparse segmentation model for the geometry or step smoke experiment.

**When to run it**

Run only on the reduced smoke dataset after voxel inputs and labels validate; it is not the full segmentation trainer.

**Required software**

Python 3, NumPy, and the model/data dependencies selected by the training mode.

**Input**

Smoke root, geometry or step mode, target, sparse voxel frames, labels, and split metadata.

**Output**

Smoke training/evaluation metrics, model checkpoint or report files, and console validation output.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--root` | PATH | Yes | None | Repository or experiment root containing the input tree. |
| `--mode` | VALUE | Yes | None | Operation or visualization mode. |
| `--target` | VALUE | No | source default | Target column or label definition to load or build. If omitted, the script uses its source-defined target path constant; pass an explicit path for a new run. |

**Existing files**

Existing generated files are checked before replacement; invalid or partial output is not accepted as complete.

**Continuing after interruption**

Validate completed jobs first and rerun only missing or failed jobs with unchanged input hashes.

**Example**

```bash
python3 rt_out/scripts/training/train_segmentation_smoke.py --help
```


### `rt_out/scripts/validation/build_actor_blender_validation_scene.py`

**What it does**

Builds a Blender inspection scene from the actor mesh index and static manifest for actor-placement review.

**When to run it**

Run after actor validation meshes/indexes exist and before visual inspection of actor placement.

**Required software**

Python 3, actor/manifest inputs, and Blender for inspection or export stages.

**Input**

Actor mesh index, static manifest, output root, Blender executable, and optional scene/marker settings.

**Output**

Blender scene, preview assets, and inspection metadata.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--mesh-index` | PATH | No | source default | Actor mesh index for validation. If omitted, the script uses its source-defined mesh index path constant; pass an explicit path for a new run. |
| `--static-manifest` | PATH | No | source default | Static manifest whose shapes are included or checked. If omitted, the script uses its source-defined static manifest path constant; pass an explicit path for a new run. |
| `--output-root` | PATH | No | source default | Destination root for generated per-frame files. If omitted, the script uses its source-defined output root path constant; pass an explicit path for a new run. |
| `--blender` | PATH | No | None | Blender executable path. |
| `--blender-worker` | flag | No | None | Controls the blender worker value used by this script. |

**Existing files**

Input artifacts are read-only; diagnostic or validation destinations may be replaced.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/validation/build_actor_blender_validation_scene.py --help
```


### `rt_out/scripts/validation/build_actor_prototype_mesh_index.py`

**What it does**

Combines actor frame manifests into a prototype mesh index used by alignment diagnostics and Blender inspection.

**When to run it**

Run after actor frame mesh exports complete and before actor alignment/floor diagnostics.

**Required software**

Python 3, actor/manifest inputs, and Blender for inspection or export stages.

**Input**

One or more actor frame manifests and an optional output path.

**Output**

Actor prototype mesh-index JSON with frame, mesh, transform, and source metadata.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--actor-frame-manifests` | PATH... | Yes | None | Actor frame manifest JSON files from the selected experiment run's dynamic_scene/frame_*/. |
| `--output` | PATH | No | source default | Destination file or directory. If omitted, the script uses its source-defined output path constant; pass an explicit path for a new run. |

**Existing files**

Input artifacts are read-only; diagnostic or validation destinations may be replaced.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/validation/build_actor_prototype_mesh_index.py --help
```


### `rt_out/scripts/validation/build_actor_validation_samples.py`

**What it does**

Builds time-sampled actor validation records from the actor manifest and animation configuration.

**When to run it**

Run before exporting validation meshes and before alignment diagnosis.

**Required software**

Python 3, actor/manifest inputs, and Blender for inspection or export stages.

**Input**

Actor manifest, actor config, actor name, frame/time range, animation policy, and output path.

**Output**

Actor validation-sample JSON with selected frames/times and source references.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--actor-manifest` | PATH | No | source default | Actor manifest defining links and visuals. If omitted, the script uses its source-defined actor manifest path constant; pass an explicit path for a new run. |
| `--actor-config` | PATH | No | source default | Actor animation/configuration file. If omitted, the script uses its source-defined actor config path constant; pass an explicit path for a new run. |
| `--actor-name` | NAME | No | None | Optional enabled actor name to sample. |
| `--num-frames` | INT | No | 80 | Number of actor validation samples. |
| `--start-time` | FLOAT | No | 0 | First actor time. |
| `--end-time` | FLOAT | No | None | Optional final actor time. |
| `--animation-time-policy` | VALUE | No | same_as_actor_time | How to convert actor trajectory time into animation clip time. |
| `--animation-loop-duration-seconds` | FLOAT | No | None | Positive clip loop duration required when --animation-time-policy=mod_clip_duration. |
| `--output` | PATH | No | source default | Destination file or directory. If omitted, the script uses its source-defined output path constant; pass an explicit path for a new run. |

**Existing files**

Input artifacts are read-only; diagnostic or validation destinations may be replaced.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/validation/build_actor_validation_samples.py --help
```


### `rt_out/scripts/validation/build_composed_frame_blender_scene.py`

**What it does**

Builds a one-frame Blender inspection scene from a composed frame manifest with optional radio markers.

**When to run it**

Run after the composed frame manifest and mesh references validate when inspecting one frame.

**Required software**

Python 3, actor/manifest inputs, and Blender for inspection or export stages.

**Input**

Composed manifest, output root, optional TX/RX marker positions, and Blender worker settings.

**Output**

One-frame Blender inspection scene and metadata; the composed manifest is not changed.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--composed-manifest` | PATH | No | source default | Composed frame manifest for inspection. If omitted, the script uses its source-defined composed manifest path constant; pass an explicit path for a new run. |
| `--output-root` | PATH | No | source default | Destination root for generated per-frame files. If omitted, the script uses its source-defined output root path constant; pass an explicit path for a new run. |
| `--dynamic-prototype-config` | PATH | No | None | Dynamic prototype configuration JSON; loaded after CLI parsing. |
| `--blender` | PATH | No | None | Blender executable path. |
| `--show-radio-markers` | flag | No | None | Add TX/RX markers and a reference line. |
| `--tx` | TEXT | No | -0.3,-3.8,1.3 | TX position as x,y,z. |
| `--rx` | TEXT | No | 2.5,-3.1,1.3 | RX position as x,y,z. |
| `--blender-worker` | flag | No | None | Controls the blender worker value used by this script. |

**Existing files**

Input artifacts are read-only; diagnostic or validation destinations may be replaced.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/validation/build_composed_frame_blender_scene.py --composed-manifest "$RUN_ROOT/frames/composed_manifests/frame_000_manifest.json" --blender "$BLENDER"
```


### `rt_out/scripts/validation/build_experiment_timeline_blender_scene.py`

**What it does**

Builds a Blender timeline inspection scene from the composed index and selected frame IDs.

**When to run it**

Run after the composed index and frame manifests validate when reviewing a sequence.

**Required software**

Python 3, actor/manifest inputs, and Blender for inspection or export stages.

**Input**

Experiment config or composed index, frame limit/step/IDs, static visibility, marker settings, and output root.

**Output**

Timeline Blender inspection scene and metadata for the selected sequence.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--config` | PATH | No | source default | Configuration file used to resolve inputs and output paths. If omitted, the script uses its source-defined config path constant; pass an explicit path for a new run. |
| `--dynamic-prototype-config` | PATH | No | None | Dynamic prototype configuration JSON; loaded after CLI parsing. |
| `--composed-index` | PATH | No | None | Composed index for timeline selection. |
| `--output-root` | PATH | No | None | Destination root for generated per-frame files. |
| `--max-frames` | INT | No | None | Bound the number of selected frames for a small run. |
| `--frame-step` | INT | No | 1 | Select every Nth timeline frame. |
| `--frame-ids` | VALUE | No | None | Comma-separated frame_id list. |
| `--show-radio-markers/--no-show-radio-markers` | flag | No | true | Show TX/RX markers and TX->RX reference lines. |
| `--hide-static` | flag | No | None | Hide static objects for the whole timeline. |
| `--blender` | PATH | No | None | Blender executable path. |
| `--blender-worker` | flag | No | None | Controls the blender worker value used by this script. |
| `--payload` | PATH | No | None | Blender worker payload JSON. |

**Existing files**

Input artifacts are read-only; diagnostic or validation destinations may be replaced.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/validation/build_experiment_timeline_blender_scene.py --help
```


### `rt_out/scripts/validation/diagnose_actor_floor_alignment.py`

**What it does**

Computes actor-to-floor alignment diagnostics from the actor mesh index and static manifest.

**When to run it**

Run after the actor prototype mesh index and static floor/reference geometry exist.

**Required software**

Python 3, actor/manifest inputs, and Blender for inspection or export stages.

**Input**

Actor mesh index, static manifest, floor/reference settings, and output JSON path.

**Output**

Floor-alignment diagnostics JSON with per-frame offsets and validation status.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--mesh-index` | PATH | No | source default | Actor mesh index for validation. If omitted, the script uses its source-defined mesh index path constant; pass an explicit path for a new run. |
| `--static-manifest` | PATH | No | source default | Static manifest whose shapes are included or checked. If omitted, the script uses its source-defined static manifest path constant; pass an explicit path for a new run. |
| `--output-json` | PATH | No | source default | Destination JSON diagnostic. If omitted, the script uses its source-defined output json path constant; pass an explicit path for a new run. |

**Existing files**

Input artifacts are read-only; diagnostic or validation destinations may be replaced.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/validation/diagnose_actor_floor_alignment.py --mesh-index "$RUN_ROOT/frames/actor_meshes/actor_mesh_index.csv" --static-manifest "$STATIC_ROOT/static_scene/export/merged_static_manifest.json"
```


### `rt_out/scripts/validation/diagnose_actor_validation_alignment.py`

**What it does**

Compares actor validation mesh transforms with the Blender worker summary and writes alignment diagnostics.

**When to run it**

Run after validation mesh export and before accepting actor placement.

**Required software**

Python 3, actor/manifest inputs, and Blender for inspection or export stages.

**Input**

Actor mesh index, worker summary, output JSON, and optional output CSV.

**Output**

Alignment diagnostic JSON and CSV with per-frame transform/offset checks.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--mesh-index` | PATH | No | source default | Actor mesh index for validation. If omitted, the script uses its source-defined mesh index path constant; pass an explicit path for a new run. |
| `--worker-summary` | PATH | No | source default | Blender worker summary for alignment. If omitted, the script uses its source-defined worker summary path constant; pass an explicit path for a new run. |
| `--output-json` | PATH | No | source default | Destination JSON diagnostic. If omitted, the script uses its source-defined output json path constant; pass an explicit path for a new run. |
| `--output-csv` | PATH | No | source default | Destination CSV diagnostic or summary. If omitted, the script uses its source-defined output csv path constant; pass an explicit path for a new run. |

**Existing files**

Input artifacts are read-only; diagnostic or validation destinations may be replaced.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/validation/diagnose_actor_validation_alignment.py --help
```


### `rt_out/scripts/validation/export_actor_validation_meshes.py`

**What it does**

Invokes Blender to export validation actor meshes from sampled actor poses.

**When to run it**

Run after build_actor_validation_samples.py and before mesh-index or alignment diagnostics.

**Required software**

Python 3, actor/manifest inputs, and Blender for inspection or export stages.

**Input**

Validation samples, output root, Blender executable, XY/Z alignment policies, and floor height.

**Output**

Per-frame validation PLY meshes, manifests, Blender summary metadata, and export diagnostics.

**Options**

| Option | Type | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `--validation-samples` | PATH | No | source default | Actor validation sample JSON. If omitted, the script uses its source-defined validation samples path constant; pass an explicit path for a new run. |
| `--output-root` | PATH | No | source default | Destination root for generated per-frame files. If omitted, the script uses its source-defined output root path constant; pass an explicit path for a new run. |
| `--blender` | PATH | No | None | Blender executable path. |
| `--alignment-policy` | VALUE | No | none | Experimental post-evaluation alignment policy. Default 'none' preserves existing export behavior; 'bounds_center_xy_to_root' shifts baked vertices in XY so their bounds center matches root_pose6. |
| `--z-alignment-policy` | VALUE | No | none | Experimental post-evaluation vertical alignment policy. Default 'none' preserves existing validation behavior; 'bounds_min_z_to_floor' shifts baked vertices in Z so bounds_min_z matches --floor-z. |
| `--floor-z` | FLOAT | No | None | Floor Z used by --z-alignment-policy bounds_min_z_to_floor. |

**Existing files**

Input artifacts are read-only; diagnostic or validation destinations may be replaced.

**Continuing after interruption**

Rerun after any input, manifest, or option affecting generated files changes.

**Example**

```bash
python3 rt_out/scripts/validation/export_actor_validation_meshes.py --help
```


### `scripts/generate_wall_uv_meshes.py`

**What it does**

Generates repository wall UV mesh assets from the geometry constants in the script.

**When to run it**

Run only when intentionally rebuilding wall mesh assets; it is not part of RT or dataset execution.

**Required software**

Python 3 standard library only.

**Input**

Source-level geometry/material constants; no CLI arguments are parsed.

**Output**

OBJ files for each wall segment plus `models/factory_shell/meshes/wall_placeholder.mtl`.

**Options**

None; the script has no command-line parser.

**Existing files**

Generated mesh files may be replaced by the script.

**Continuing after interruption**

Rerun from the beginning after checking which generated mesh files exist.

**Example**

```bash
python3 scripts/generate_wall_uv_meshes.py
```

## Safe validation commands

These commands do not run the scientific pipeline:

```bash
python3 -m compileall -q rt_out/scripts scripts
find rt_out/scripts scripts -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
python3 rt_out/scripts/static_scene/extract_scene_manifests.py --help
python3 rt_out/scripts/perception/run_perception_pipeline.py --help
python3 rt_out/scripts/training/run_best_beam_power_regression.py --help
```

Run the release-hardening and regression test modules with the repository test
runner. Compilation and `--help` are not substitutes for generated-output tests.

## Old names and limitations

The old numbered paths (`00_`, `01_`, `02_`, `03_`, `10_`, `20_`, `30_`, and
similar) are not aliases. The current implementation uses the unnumbered paths
listed above. The previous 200-frame and perception runs have dedicated guides
and are not generic producers that can be rerun from the beginning. The current
2,446-frame GT run is a validated recorded run; the available small test
producer is not a promise of a one-command full regeneration.
