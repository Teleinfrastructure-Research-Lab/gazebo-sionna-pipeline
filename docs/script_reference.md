# Script Reference

This file documents the current script set as it exists in the repository today.

Status labels used here:

- **active**: part of the current validated pipeline
- **experiment**: experiment-local wrappers layered on top of the validated pipeline
- **helper**: directly supports the pipeline, including operational/data-generation helpers
- **misc**: useful project tooling, launch helpers, or experiments, but not part of the main RT chain
- **legacy/historical**: kept for reference or history, not part of the active path

## Active Pipeline Overview

| Script | Status | Stage |
| --- | --- | --- |
| `00_extract_scene_manifests.py` | active | Gazebo scene extraction |
| `01_validate_scene_manifests.py` | active | Manifest validation |
| `02_build_scene_geometry_registry.py` | active | Geometry flattening |
| `03_build_static_scene_registry.py` | active | Static preprocessing |
| `20_merge_static_scene_by_material.py` | active | Static merge |
| `22_build_static_mitsuba_xml.py` | active | Static Mitsuba XML |
| `23_build_static_sionna_xml.py` | active | Static Sionna XML |
| `24_run_sionna_rt_sanity.py` | active | RT sanity / scene load |
| `30_build_prototype_dynamic_frames.py` | active | Dynamic frame parsing |
| `31_build_prototype_dynamic_visual_frames.py` | active | Dynamic frame-to-visual join |
| `32_export_dynamic_frame_meshes.py` | active | Dynamic per-frame mesh export |
| `33_compose_prototype_frame_scene.py` | active | Static + dynamic composition |
| `34_build_prototype_frame_sionna_xml.py` | active | Frame Sionna XML |
| `35_run_prototype_three_frame_rt_sanity.py` | active | 3-frame single-RX sanity |
| `36_run_three_frame_three_rx_rt_sanity.py` | active | 3-frame x 3-RX sanity |

## Experiment-Local Scripts Overview

| Script | Status | Stage |
| --- | --- | --- |
| `exp_sample_frames.py` | experiment | sampled-frame selection |
| `exp_export_dynamic_meshes_batch.py` | experiment | batch dynamic mesh export |
| `exp_compose_frame_manifests_batch.py` | experiment | batch static+dynamic composition |
| `exp_build_sionna_xml_batch.py` | experiment | batch frame XML generation |
| `exp_run_rt_multi_rx_batch.py` | experiment | batch multi-RX RT evaluation |
| `exp_build_rt_labels.py` | experiment | frame-to-frame label generation |
| `exp_build_object_features.py` | experiment | object-aware feature table build |
| `exp_build_raw_occupancy_features.py` | experiment | raw occupancy baseline build |
| `exp_run_semantic_ablation.py` | experiment | classical-model ablation evaluation |

## Helper / Support Scripts Overview

| Script | Status | Role |
| --- | --- | --- |
| `10_convert_dae_to_ply_blender.py` | helper | Blender DAE -> PLY conversion utility |
| `11_convert_mesh_to_ply_blender.py` | helper | Blender mesh -> PLY conversion utility |
| `21_merge_static_scene_blender_worker.py` | helper | Blender worker used by static merge |
| `dynamic_prototype_config.py` | helper | Loads and validates dynamic prototype config |
| `rt_material_config.py` | helper | Loads RT material/runtime config and emits radio-material XML |

## Operational / Data-Generation Helpers Overview

| Script | Status | Role |
| --- | --- | --- |
| `rt_out/scripts/run_all.sh` | helper | Records Panda/UR5 pose logs while running both motion scripts |
| `rt_out/scripts/run_panda.sh` | helper | Panda motion helper used to generate prototype pose logs |
| `rt_out/scripts/run_ur5.sh` | helper | UR5/RG2 motion helper used to generate prototype pose logs |

## Misc / Operational Scripts Overview

| Script | Status | Role |
| --- | --- | --- |
| `run_myworld.sh` | misc | Launch Gazebo on `myworld.sdf` |
| `run_myworld_rt.sh` | misc | Launch Gazebo on `myworld_rt.sdf` |
| `rt_out/scripts/sionna_test.py` | misc | Exploratory multi-RX static RT test script |
| `scripts/generate_wall_uv_meshes.py` | misc | World/asset authoring helper for UV-aware wall meshes |
| `rt_out/scripts/actor_spike_export_actor_walking.py` | misc | Offline actor-mesh export spike |
| `rt_out/scripts/actor_spike_blender_sample_actor.py` | misc | Blender actor sampling helper |

---

## Active Scripts

### `00_extract_scene_manifests.py`

- **Location:** [`rt_out/scripts/00_extract_scene_manifests.py`](../rt_out/scripts/00_extract_scene_manifests.py)
- **Status:** active
- **Stage:** scene extraction
- **Purpose:** reads the Gazebo RT world and model SDFs, then splits scene content into static and dynamic manifests
- **When to use it:** after editing [`myworld_rt.sdf`](../myworld_rt.sdf), model SDFs, or the dynamic prototype model list
- **Expected inputs:**
  - [`myworld_rt.sdf`](../myworld_rt.sdf)
  - model SDFs under [`models/`](../models)
  - [`rt_out/config/dynamic_prototype_config.json`](../rt_out/config/dynamic_prototype_config.json)
- **Expected outputs:**
  - [`rt_out/manifests/static_manifest.json`](../rt_out/manifests/static_manifest.json)
  - [`rt_out/manifests/dynamic_manifest.json`](../rt_out/manifests/dynamic_manifest.json)
- **Typical usage:**
  - `python3 rt_out/scripts/00_extract_scene_manifests.py`
- **Important CLI arguments:** none
- **Dependencies / assumptions:** Python, `numpy`, SDF/XML parsing
- **Writes files or read-only:** writes JSON manifests
- **Notes / gotchas:**
  - Only processes `<model>` and `<include>` nodes
  - Ignores Gazebo `<actor>` entries by implementation
  - Dynamic model names come from the prototype config; everything else is treated as static

### `01_validate_scene_manifests.py`

- **Location:** [`rt_out/scripts/01_validate_scene_manifests.py`](../rt_out/scripts/01_validate_scene_manifests.py)
- **Status:** active
- **Stage:** manifest validation
- **Purpose:** validates structure, poses, geometry types, mesh URI resolution, and expected dynamic model set
- **When to use it:** immediately after `00`
- **Expected inputs:**
  - [`rt_out/manifests/static_manifest.json`](../rt_out/manifests/static_manifest.json)
  - [`rt_out/manifests/dynamic_manifest.json`](../rt_out/manifests/dynamic_manifest.json)
  - [`models/`](../models)
  - [`rt_out/config/dynamic_prototype_config.json`](../rt_out/config/dynamic_prototype_config.json)
- **Expected outputs:**
  - [`rt_out/manifests/manifest_validation_report.json`](../rt_out/manifests/manifest_validation_report.json)
- **Typical usage:**
  - `python3 rt_out/scripts/01_validate_scene_manifests.py`
- **Important CLI arguments:** none
- **Dependencies / assumptions:** model URIs must resolve under the current repo
- **Writes files or read-only:** writes a validation report; does not rewrite manifests
- **Notes / gotchas:**
  - Fails if the dynamic manifest contains models outside the configured prototype set
  - Also checks for the presence of `factory_shell` in the static manifest

### `02_build_scene_geometry_registry.py`

- **Location:** [`rt_out/scripts/02_build_scene_geometry_registry.py`](../rt_out/scripts/02_build_scene_geometry_registry.py)
- **Status:** active
- **Stage:** geometry flattening
- **Purpose:** flattens static and dynamic manifest visuals into one registry with normalized geometry records
- **When to use it:** after manifest validation
- **Expected inputs:**
  - [`rt_out/manifests/static_manifest.json`](../rt_out/manifests/static_manifest.json)
  - [`rt_out/manifests/dynamic_manifest.json`](../rt_out/manifests/dynamic_manifest.json)
- **Expected outputs:**
  - [`rt_out/manifests/geometry_registry.json`](../rt_out/manifests/geometry_registry.json)
- **Typical usage:**
  - `python3 rt_out/scripts/02_build_scene_geometry_registry.py`
- **Important CLI arguments:** none
- **Dependencies / assumptions:** URI resolution must succeed for mesh visuals
- **Writes files or read-only:** writes the registry JSON
- **Notes / gotchas:**
  - Supports `mesh`, `box`, `cylinder`, and `sphere`
  - Keeps both static and dynamic records in one file; later stages filter from it

### `03_build_static_scene_registry.py`

- **Location:** [`rt_out/scripts/03_build_static_scene_registry.py`](../rt_out/scripts/03_build_static_scene_registry.py)
- **Status:** active
- **Stage:** static preprocessing
- **Purpose:** filters the geometry registry to static entries, assigns semantic material classes, computes `to_world`, and prepares merge-ready static records
- **When to use it:** after `02`
- **Expected inputs:**
  - [`rt_out/manifests/geometry_registry.json`](../rt_out/manifests/geometry_registry.json)
  - [`rt_out/materials/material_map.json`](../rt_out/materials/material_map.json)
- **Expected outputs:**
  - [`rt_out/manifests/static_registry.json`](../rt_out/manifests/static_registry.json)
- **Typical usage:**
  - `python3 rt_out/scripts/03_build_static_scene_registry.py`
- **Important CLI arguments:** none
- **Dependencies / assumptions:**
  - static mesh conversion targets live under [`rt_out/static_scene/converted_meshes/`](../rt_out/static_scene/converted_meshes)
  - material rules must cover all entries that will later reach Sionna XML
- **Writes files or read-only:** writes a new static registry
- **Notes / gotchas:**
  - Uses semantic material classes such as `panel_wall`, `metal`, `human_skin`
  - `material="__skip__"` rules in [`material_map.json`](../rt_out/materials/material_map.json) remove entries from the static RT scene
  - Non-`PLY`/`OBJ` static mesh sources must already have converted mesh files present or they stay non-ready

### `20_merge_static_scene_by_material.py`

- **Location:** [`rt_out/scripts/20_merge_static_scene_by_material.py`](../rt_out/scripts/20_merge_static_scene_by_material.py)
- **Status:** active
- **Stage:** static merge
- **Purpose:** groups ready static entries by semantic material and launches Blender to bake them into merged per-material meshes
- **When to use it:** after `03`
- **Expected inputs:**
  - [`rt_out/manifests/static_registry.json`](../rt_out/manifests/static_registry.json)
  - Blender
  - helper worker [`21_merge_static_scene_blender_worker.py`](../rt_out/scripts/21_merge_static_scene_blender_worker.py)
- **Expected outputs:**
  - merged PLYs under [`rt_out/static_scene/export/merged_by_material/`](../rt_out/static_scene/export/merged_by_material)
  - debug job/result JSON under [`rt_out/static_scene/export/debug/`](../rt_out/static_scene/export/debug)
  - [`rt_out/static_scene/export/merged_static_manifest.json`](../rt_out/static_scene/export/merged_static_manifest.json)
- **Typical usage:**
  - `python3 rt_out/scripts/20_merge_static_scene_by_material.py`
- **Important CLI arguments:**
  - `--registry`
  - `--out-dir`
  - `--blender`
  - `--helper`
  - `--export-individual`
  - `--manifest-name`
- **Dependencies / assumptions:** Blender must be discoverable via `BLENDER`, `PATH`, or repo/home fallback locations
- **Writes files or read-only:** writes merged geometry and manifest outputs
- **Notes / gotchas:**
  - Only merges `status=ready` static entries
  - `--export-individual` is useful for per-entry debug PLYs
  - Corrected shelf orientation is part of the normal merge path through the Blender worker

### Blender Inspection Note

For Blender-based visual inspection:

- the merged **static** scene does not include dynamic prototype robots, so importing static-only outputs will not show `Panda` or `ur5_rg2`
- importing raw/source/cache robot meshes directly can make them appear stacked or misplaced because those meshes are usually still in local mesh coordinates
- for placement checks, use baked outputs:
  - composed frame scenes under [`rt_out/composed_scene/`](../rt_out/composed_scene)
  - or transformed dynamic meshes under [`rt_out/dynamic_scene/`](../rt_out/dynamic_scene)

### `22_build_static_mitsuba_xml.py`

- **Location:** [`rt_out/scripts/22_build_static_mitsuba_xml.py`](../rt_out/scripts/22_build_static_mitsuba_xml.py)
- **Status:** active
- **Stage:** static visual/debug XML
- **Purpose:** builds a Mitsuba scene from merged static PLYs with simple visual/debug BSDFs
- **When to use it:** after `20`, mainly for visual inspection/debugging
- **Expected inputs:**
  - [`rt_out/static_scene/export/merged_static_manifest.json`](../rt_out/static_scene/export/merged_static_manifest.json)
- **Expected outputs:**
  - [`rt_out/static_scene/export/static_scene_mitsuba.xml`](../rt_out/static_scene/export/static_scene_mitsuba.xml)
- **Typical usage:**
  - `python3 rt_out/scripts/22_build_static_mitsuba_xml.py`
- **Important CLI arguments:**
  - `--manifest`
  - `--output`
  - `--geometry-only`
  - camera/render settings
- **Dependencies / assumptions:** merged static meshes must already exist
- **Writes files or read-only:** writes XML
- **Notes / gotchas:** this is a visual/debug XML, not the RT material XML used by Sionna

### `23_build_static_sionna_xml.py`

- **Location:** [`rt_out/scripts/23_build_static_sionna_xml.py`](../rt_out/scripts/23_build_static_sionna_xml.py)
- **Status:** active
- **Stage:** static RT XML
- **Purpose:** builds a Sionna-compatible XML scene with one radio material per used semantic material class
- **When to use it:** after `20`, before RT sanity
- **Expected inputs:**
  - [`rt_out/static_scene/export/merged_static_manifest.json`](../rt_out/static_scene/export/merged_static_manifest.json)
  - [`rt_out/config/rt_material_mapping.json`](../rt_out/config/rt_material_mapping.json)
- **Expected outputs:**
  - [`rt_out/static_scene/export/static_scene_sionna.xml`](../rt_out/static_scene/export/static_scene_sionna.xml)
- **Typical usage:**
  - `python3 rt_out/scripts/23_build_static_sionna_xml.py`
- **Important CLI arguments:**
  - `--manifest`
  - `--output`
- **Dependencies / assumptions:** every material class in the merged manifest must have an RT mapping
- **Writes files or read-only:** writes XML
- **Notes / gotchas:**
  - Uses true custom `radio-material` XML for `human_skin`
  - Pulls the 28 GHz baseline and material definitions from config through [`rt_material_config.py`](../rt_out/scripts/rt_material_config.py)

### `24_run_sionna_rt_sanity.py`

- **Location:** [`rt_out/scripts/24_run_sionna_rt_sanity.py`](../rt_out/scripts/24_run_sionna_rt_sanity.py)
- **Status:** active
- **Stage:** RT sanity / scene load validation
- **Purpose:** loads a Sionna XML scene, explicitly sets `scene.frequency`, adds one TX/RX pair, and checks path computation
- **When to use it:** after generating static or frame-level Sionna XML
- **Expected inputs:**
  - a Sionna XML scene, by default [`rt_out/static_scene/export/static_scene_sionna.xml`](../rt_out/static_scene/export/static_scene_sionna.xml)
  - [`rt_out/config/rt_material_mapping.json`](../rt_out/config/rt_material_mapping.json)
- **Expected outputs:** stdout diagnostics only
- **Typical usage:**
  - `python3 rt_out/scripts/24_run_sionna_rt_sanity.py --xml rt_out/static_scene/export/static_scene_sionna.xml`
- **Important CLI arguments:**
  - `--xml`
  - `--tx`
  - `--rx`
  - `--frequency-hz`
  - `--max-depth`
  - `--samples-per-src`
  - `--max-num-paths-per-src`
  - `--seed`
  - `--enable-refraction`
  - `--use-fallback-variant`
- **Dependencies / assumptions:** Sionna RT, Mitsuba, and a suitable Mitsuba variant ending in `_ad_mono_polarized`
- **Writes files or read-only:** read-only
- **Notes / gotchas:**
  - Explicitly overrides Sionna’s default frequency with the configured carrier frequency
  - Requires scenes to contain explicit radio materials, not visual-only BSDFs

### `30_build_prototype_dynamic_frames.py`

- **Location:** [`rt_out/scripts/30_build_prototype_dynamic_frames.py`](../rt_out/scripts/30_build_prototype_dynamic_frames.py)
- **Status:** active
- **Stage:** dynamic frame parsing
- **Purpose:** parses Panda and UR5 pose logs into a strict, canonical 3-frame motion manifest
- **When to use it:** after recording pose logs or changing the dynamic prototype config
- **Expected inputs:**
  - [`rt_out/poses/panda/panda_pose.log`](../rt_out/poses/panda/panda_pose.log)
  - [`rt_out/poses/ur5/ur5_pose.log`](../rt_out/poses/ur5/ur5_pose.log)
  - [`rt_out/manifests/dynamic_manifest.json`](../rt_out/manifests/dynamic_manifest.json)
  - [`rt_out/config/dynamic_prototype_config.json`](../rt_out/config/dynamic_prototype_config.json)
- **Expected outputs:**
  - [`rt_out/dynamic_frames/prototype_frames.json`](../rt_out/dynamic_frames/prototype_frames.json)
- **Typical usage:**
  - `python3 rt_out/scripts/30_build_prototype_dynamic_frames.py`
- **Important CLI arguments:** none
- **Dependencies / assumptions:** pose logs must use the expected Gazebo pose message text format
- **Writes files or read-only:** writes JSON
- **Notes / gotchas:**
  - Uses **source sample index**, not timestamp, as the canonical frame key
  - Reconstructs samples by full expected-link-set completion, not by fixed block size
  - Fails on duplicate links, missing links, malformed scoped names, or per-sample timestamp mismatches

### `31_build_prototype_dynamic_visual_frames.py`

- **Location:** [`rt_out/scripts/31_build_prototype_dynamic_visual_frames.py`](../rt_out/scripts/31_build_prototype_dynamic_visual_frames.py)
- **Status:** active
- **Stage:** dynamic frame-to-visual join
- **Purpose:** joins trusted per-link motion frames with visual-bearing dynamic geometry metadata
- **When to use it:** after `30`
- **Expected inputs:**
  - [`rt_out/dynamic_frames/prototype_frames.json`](../rt_out/dynamic_frames/prototype_frames.json)
  - [`rt_out/manifests/dynamic_manifest.json`](../rt_out/manifests/dynamic_manifest.json)
  - model assets under [`models/`](../models)
- **Expected outputs:**
  - [`rt_out/dynamic_frames/dynamic_visual_frames.json`](../rt_out/dynamic_frames/dynamic_visual_frames.json)
- **Typical usage:**
  - `python3 rt_out/scripts/31_build_prototype_dynamic_visual_frames.py`
- **Important CLI arguments:** none
- **Dependencies / assumptions:** dynamic manifest and frame manifest must match the configured model/link counts
- **Writes files or read-only:** writes JSON
- **Notes / gotchas:**
  - Validates exact renderable and non-renderable link sets from config
  - Resolves source mesh URIs against the current repo, not stale absolute paths
  - Keeps `panda_link8` and `tool0` as non-renderable bookkeeping links

### `32_export_dynamic_frame_meshes.py`

- **Location:** [`rt_out/scripts/32_export_dynamic_frame_meshes.py`](../rt_out/scripts/32_export_dynamic_frame_meshes.py)
- **Status:** active
- **Stage:** dynamic per-frame geometry export
- **Purpose:** exports transformed, dynamic-only PLY meshes for one prototype frame
- **When to use it:** after `31`, once per frame you want to bake
- **Expected inputs:**
  - [`rt_out/dynamic_frames/dynamic_visual_frames.json`](../rt_out/dynamic_frames/dynamic_visual_frames.json)
  - Blender
- **Expected outputs:**
  - frame folder under [`rt_out/dynamic_scene/`](../rt_out/dynamic_scene)
  - per-visual PLYs under `raw_visual_meshes/`
  - per-frame manifest like `dynamic_frame_000_manifest.json`
  - reusable converted source cache under [`rt_out/dynamic_scene/converted_mesh_cache/`](../rt_out/dynamic_scene/converted_mesh_cache)
- **Typical usage:**
  - `python3 rt_out/scripts/32_export_dynamic_frame_meshes.py --frame-id 0`
- **Important CLI arguments:**
  - `--frame-id`
  - `--source-sample-index`
  - `--output-root`
- **Dependencies / assumptions:** Blender is required; current validated dynamic visuals are all mesh geometry
- **Writes files or read-only:** writes cached and transformed meshes plus a manifest
- **Notes / gotchas:**
  - Applies `final_transform = link_to_world * visual_pose_matrix * scale_matrix`
  - Converts raw source meshes into a cache before per-frame transforms are baked
  - Defaults to frame `0` if no `--frame-id` is supplied

### `33_compose_prototype_frame_scene.py`

- **Location:** [`rt_out/scripts/33_compose_prototype_frame_scene.py`](../rt_out/scripts/33_compose_prototype_frame_scene.py)
- **Status:** active
- **Stage:** scene composition
- **Purpose:** builds a flat composed scene manifest containing all merged static material groups plus all dynamic per-visual frame meshes
- **When to use it:** after `32`
- **Expected inputs:**
  - static merged manifest, by default [`rt_out/static_scene/export/merged_static_manifest.json`](../rt_out/static_scene/export/merged_static_manifest.json)
  - one dynamic frame export manifest under [`rt_out/dynamic_scene/`](../rt_out/dynamic_scene)
- **Expected outputs:**
  - frame manifest under [`rt_out/composed_scene/frame_XXX/`](../rt_out/composed_scene)
- **Typical usage:**
  - `python3 rt_out/scripts/33_compose_prototype_frame_scene.py --frame-id 0`
- **Important CLI arguments:**
  - `--frame-id`
  - `--static-manifest`
  - `--dynamic-manifest`
  - `--output-manifest`
- **Dependencies / assumptions:** all referenced static and dynamic mesh paths must exist
- **Writes files or read-only:** writes a composed manifest
- **Notes / gotchas:**
  - Keeps static entries as already-baked merged material groups
  - Keeps dynamic entries as already-baked per-visual meshes
  - Supports path rerooting for static manifest paths that still point at old project roots

### `34_build_prototype_frame_sionna_xml.py`

- **Location:** [`rt_out/scripts/34_build_prototype_frame_sionna_xml.py`](../rt_out/scripts/34_build_prototype_frame_sionna_xml.py)
- **Status:** active
- **Stage:** frame RT XML emission
- **Purpose:** converts one composed frame manifest into a Sionna-compatible XML scene
- **When to use it:** after `33`
- **Expected inputs:**
  - a composed frame manifest under [`rt_out/composed_scene/`](../rt_out/composed_scene)
  - [`rt_out/config/rt_material_mapping.json`](../rt_out/config/rt_material_mapping.json)
  - [`rt_out/config/dynamic_prototype_config.json`](../rt_out/config/dynamic_prototype_config.json)
- **Expected outputs:**
  - frame XML under [`rt_out/composed_scene/frame_XXX/`](../rt_out/composed_scene)
- **Typical usage:**
  - `python3 rt_out/scripts/34_build_prototype_frame_sionna_xml.py --frame-id 0`
- **Important CLI arguments:**
  - `--frame-id`
  - `--input-manifest`
  - `--output-xml`
- **Dependencies / assumptions:** all mesh paths in the composed manifest must exist
- **Writes files or read-only:** writes XML
- **Notes / gotchas:**
  - Static entries keep their semantic material labels
  - Dynamic entries are forced by config to `metal` for `Panda` and `ur5_rg2`
  - No additional transforms are emitted because the geometry is already baked into world space

### `35_run_prototype_three_frame_rt_sanity.py`

- **Location:** [`rt_out/scripts/35_run_prototype_three_frame_rt_sanity.py`](../rt_out/scripts/35_run_prototype_three_frame_rt_sanity.py)
- **Status:** active
- **Stage:** end-to-end three-frame sanity
- **Purpose:** runs the full 3-frame prototype flow for one TX/RX pair and writes a compact CSV summary
- **When to use it:** after static export is ready and dynamic frame data is available
- **Expected inputs:**
  - static merged manifest, default [`rt_out/static_scene/export/merged_static_manifest.json`](../rt_out/static_scene/export/merged_static_manifest.json)
  - dynamic frame definitions / visual frames
  - collabpaper Sionna environment
- **Expected outputs:**
  - composed manifests / XMLs under [`rt_out/composed_scene/`](../rt_out/composed_scene)
  - [`rt_out/composed_scene/three_frame_rt_summary.csv`](../rt_out/composed_scene/three_frame_rt_summary.csv)
- **Typical usage:**
  - `python3 rt_out/scripts/35_run_prototype_three_frame_rt_sanity.py`
- **Important CLI arguments:**
  - `--static-manifest`
  - `--composed-root`
  - `--output-suffix`
  - `--summary-csv`
- **Dependencies / assumptions:**
  - requires a `collabpaper` Python environment or `COLLABPAPER_PYTHON`
  - runs `32`, `33`, `34`, and `24`
- **Writes files or read-only:** writes dynamic exports, composed outputs, XMLs, and summary CSV
- **Notes / gotchas:**
  - Uses the configured 28 GHz frequency explicitly
  - Computes `tau_min` / `tau_max` through an inline helper after the main sanity run succeeds
  - Defaults to the standard, unsuffixed output branch

### `36_run_three_frame_three_rx_rt_sanity.py`

- **Location:** [`rt_out/scripts/36_run_three_frame_three_rx_rt_sanity.py`](../rt_out/scripts/36_run_three_frame_three_rx_rt_sanity.py)
- **Status:** active
- **Stage:** multi-RX prototype evaluation
- **Purpose:** runs the 3-frame x 3-RX RT sanity evaluation using the approved TX/RX config
- **When to use it:** for the current multi-receiver validation pass
- **Expected inputs:**
  - [`rt_out/config/prototype_radio_sites.json`](../rt_out/config/prototype_radio_sites.json)
  - static merged manifest, default [`rt_out/static_scene/export/merged_static_manifest.json`](../rt_out/static_scene/export/merged_static_manifest.json)
  - existing dynamic frame exports under [`rt_out/dynamic_scene/`](../rt_out/dynamic_scene)
- **Expected outputs:**
  - composed manifests / XMLs under [`rt_out/composed_scene/`](../rt_out/composed_scene)
  - [`rt_out/composed_scene/three_frame_three_rx_rt_summary.csv`](../rt_out/composed_scene/three_frame_three_rx_rt_summary.csv)
- **Typical usage:**
  - `python3 rt_out/scripts/36_run_three_frame_three_rx_rt_sanity.py`
- **Important CLI arguments:**
  - `--radio-sites`
  - `--static-manifest`
  - `--composed-root`
  - `--output-csv`
- **Dependencies / assumptions:**
  - requires the collabpaper environment / `COLLABPAPER_PYTHON`
  - requires already-exported dynamic frame meshes
  - reuses `33`, `34`, and `24`; does **not** rerun `32`
- **Writes files or read-only:** writes frame XMLs/manifests under the main branch plus a 9-row CSV
- **Notes / gotchas:**
  - This script now targets the unsuffixed main branch by default
  - Uses the approved TX/RX site config from [`prototype_radio_sites.json`](../rt_out/config/prototype_radio_sites.json)

---

## Experiment-Local Scripts

These scripts are not part of the minimal validated 3-frame sanity chain, but
they are part of the current repository and are used by the
`semantic_ablation_rigid_200f` branch documented in
[`docs/semantic_ablation_200f_pipeline.md`](./semantic_ablation_200f_pipeline.md).

### `exp_sample_frames.py`

- **Location:** [`rt_out/scripts/exp_sample_frames.py`](../rt_out/scripts/exp_sample_frames.py)
- **Status:** experiment
- **Purpose:** finds the common valid Panda/UR5 pose-sample range and builds a monotonic sampled-frame list for an experiment branch
- **Inputs:** experiment config, pose logs, dynamic prototype config
- **Outputs:** `rt_out/experiments/<experiment_name>/frames/sampled_frames.json`
- **Important CLI arguments:** `--config`
- **Notes:** uses source-sample index rather than timestamps because pose logs can contain duplicate timestamps

### `exp_export_dynamic_meshes_batch.py`

- **Location:** [`rt_out/scripts/exp_export_dynamic_meshes_batch.py`](../rt_out/scripts/exp_export_dynamic_meshes_batch.py)
- **Status:** experiment
- **Purpose:** loops over sampled frames and reuses `32_export_dynamic_frame_meshes.py` unchanged
- **Inputs:** experiment config, `dynamic_visual_frames.json`, Blender
- **Outputs:** `frames/dynamic_meshes/` plus `dynamic_mesh_index.csv`
- **Important CLI arguments:** `--config`, `--no-progress`, `--progress-every`
- **Notes:** fail-fast by default; designed to keep heavy mesh generation out of Git

### `exp_compose_frame_manifests_batch.py`

- **Location:** [`rt_out/scripts/exp_compose_frame_manifests_batch.py`](../rt_out/scripts/exp_compose_frame_manifests_batch.py)
- **Status:** experiment
- **Purpose:** batch wrapper around `33_compose_prototype_frame_scene.py`
- **Inputs:** experiment config, `dynamic_mesh_index.csv`, frozen static merged manifest
- **Outputs:** `frames/composed_manifests/` plus `composed_manifest_index.csv`
- **Important CLI arguments:** `--config`, `--no-progress`, `--progress-every`

### `exp_build_sionna_xml_batch.py`

- **Location:** [`rt_out/scripts/exp_build_sionna_xml_batch.py`](../rt_out/scripts/exp_build_sionna_xml_batch.py)
- **Status:** experiment
- **Purpose:** batch wrapper around `34_build_prototype_frame_sionna_xml.py`
- **Inputs:** experiment config, `composed_manifest_index.csv`
- **Outputs:** `sionna_xml/` plus `sionna_xml_index.csv`
- **Important CLI arguments:** `--config`, `--no-progress`, `--progress-every`

### `exp_run_rt_multi_rx_batch.py`

- **Location:** [`rt_out/scripts/exp_run_rt_multi_rx_batch.py`](../rt_out/scripts/exp_run_rt_multi_rx_batch.py)
- **Status:** experiment
- **Purpose:** runs one RT solve per XML/RX pair by calling `24_run_sionna_rt_sanity.py`, then adds helper-derived path/delay/gain summaries
- **Inputs:** experiment config, `sionna_xml_index.csv`
- **Outputs:** `rt_results/rt_<num_frames>frames_multi_rx.csv`
- **Important CLI arguments:** `--config`, `--continue-on-error`, `--max-frames`, `--max-rows`, `--no-progress`, `--progress-every`
- **Notes:** names the RT batch CSV from `experiment_config.num_frames`, e.g. `rt_200frames_multi_rx.csv`; uses `--tx=<...>` / `--rx=<...>` argument passing for negative coordinates

### `exp_build_rt_labels.py`

- **Location:** [`rt_out/scripts/exp_build_rt_labels.py`](../rt_out/scripts/exp_build_rt_labels.py)
- **Status:** experiment
- **Purpose:** converts per-frame RT rows into per-RX frame-to-frame labels such as `y_path_change` and `y_adaptation_trigger_1db`
- **Inputs:** experiment config, `rt_<num_frames>frames_multi_rx.csv`
- **Outputs:** `rt_<num_frames>frames_multi_rx_labeled.csv`, `rt_label_summary.csv`
- **Important CLI arguments:** `--config`, `--eta-tau`, `--allow-failed`
- **Notes:** `rx_power_dbm` is derived from `tx_power_dbm + path_gain_db`; the resulting RT columns are targets/metadata for later learning, not proactive input features

### `exp_build_object_features.py`

- **Location:** [`rt_out/scripts/exp_build_object_features.py`](../rt_out/scripts/exp_build_object_features.py)
- **Status:** experiment
- **Purpose:** joins labeled RT rows with object-aware geometry/material/semantic descriptors
- **Inputs:** experiment config, composed-manifest index, labeled RT CSV
- **Outputs:** `features/object_features_rt_labels.csv`
- **Important CLI arguments:** `--config`
- **Notes:** intended to approximate descriptors from object masks/instances rather than raw occupancy alone

### `exp_build_raw_occupancy_features.py`

- **Location:** [`rt_out/scripts/exp_build_raw_occupancy_features.py`](../rt_out/scripts/exp_build_raw_occupancy_features.py)
- **Status:** experiment
- **Purpose:** builds a class-agnostic raw-geometry baseline from sampled mesh vertices
- **Inputs:** experiment config, `object_features_rt_labels.csv`, composed manifests and referenced meshes
- **Outputs:** `features/raw_occupancy_features_rt_labels.csv`
- **Important CLI arguments:** `--config`
- **Notes:** uses no semantic/material/object identity as model inputs; approximates raw 3D / occupancy-style wireless baselines

### `exp_run_semantic_ablation.py`

- **Location:** [`rt_out/scripts/exp_run_semantic_ablation.py`](../rt_out/scripts/exp_run_semantic_ablation.py)
- **Status:** experiment
- **Purpose:** evaluates grouped frame-level classical baselines on `wide`, `compact`, or `raw` feature tables
- **Inputs:** experiment config, feature table chosen by `--feature-mode`
- **Outputs:** experiment-local result CSVs under `results/`
- **Important CLI arguments:** `--config`, `--target`, `--rx-filter`, `--feature-mode`, `--models`
- **Notes:** supports `logistic`, `rf`, `svm`, optional `mlp`; uses grouped splits by `frame_id`; this is a feasibility classifier, not a beamforming/resource-allocation implementation

---

## Helper / Support Scripts

### `10_convert_dae_to_ply_blender.py`

- **Location:** [`rt_out/scripts/10_convert_dae_to_ply_blender.py`](../rt_out/scripts/10_convert_dae_to_ply_blender.py)
- **Status:** helper
- **Purpose:** Blender utility to convert one `DAE` mesh to `PLY`
- **When to use it:** when preparing static conversion cache entries manually
- **Inputs:** one input `.dae`, one output `.ply`
- **Outputs:** converted `.ply`
- **Typical usage:**
  - `blender --background --python rt_out/scripts/10_convert_dae_to_ply_blender.py -- input.dae output.ply`
- **Notes:** not orchestrated as a main pipeline stage today

### `11_convert_mesh_to_ply_blender.py`

- **Location:** [`rt_out/scripts/11_convert_mesh_to_ply_blender.py`](../rt_out/scripts/11_convert_mesh_to_ply_blender.py)
- **Status:** helper
- **Purpose:** Blender utility for `DAE`, `GLB/GLTF`, or `STL` to `PLY`
- **When to use it:** when manually preparing or refreshing static converted meshes
- **Inputs:** one input mesh, one output `.ply`
- **Outputs:** converted `.ply`
- **Typical usage:**
  - `blender --background --python rt_out/scripts/11_convert_mesh_to_ply_blender.py -- input_mesh output.ply`
- **Notes:** not part of the scripted main pipeline chain today

### `21_merge_static_scene_blender_worker.py`

- **Location:** [`rt_out/scripts/21_merge_static_scene_blender_worker.py`](../rt_out/scripts/21_merge_static_scene_blender_worker.py)
- **Status:** helper
- **Purpose:** Blender worker launched by `20` to import entries, apply transforms, join meshes, and export merged PLYs
- **When to use it:** indirectly through `20`
- **Inputs:** merge job JSON generated by `20`
- **Outputs:** merge result JSON and merged/exported PLYs
- **Typical usage:** called by `20`; not usually run directly
- **Notes / gotchas:**
  - Contains asset-local correction hooks for:
    - reflective table mesh orientation
    - `Picking_Shelves` local orientation correction
  - That correction lives here, not in the global transform chain

### `dynamic_prototype_config.py`

- **Location:** [`rt_out/scripts/dynamic_prototype_config.py`](../rt_out/scripts/dynamic_prototype_config.py)
- **Status:** helper
- **Purpose:** loads and validates [`dynamic_prototype_config.json`](../rt_out/config/dynamic_prototype_config.json)
- **Used by:** `00`, `01`, `30`, `31`, `32`, `34`, `35`, `36`
- **Notes:** this is the source of truth for the current Panda/UR5 prototype assumptions

### `rt_material_config.py`

- **Location:** [`rt_out/scripts/rt_material_config.py`](../rt_out/scripts/rt_material_config.py)
- **Status:** helper
- **Purpose:** loads RT material specs and runtime carrier frequency from [`rt_material_mapping.json`](../rt_out/config/rt_material_mapping.json)
- **Used by:** `23`, `24`, `34`, `35`, `36`, `sionna_test.py`
- **Notes:** this is the source of truth for the explicit 28 GHz RT baseline

## Operational / Data-Generation Helper Details

### `rt_out/scripts/run_all.sh`

- **Location:** [`rt_out/scripts/run_all.sh`](../rt_out/scripts/run_all.sh)
- **Status:** helper
- **Purpose:** starts Panda and UR5 pose loggers, then launches both robot motion scripts to generate the prototype motion dataset
- **When to use it:** when you need fresh pose logs for `30_build_prototype_dynamic_frames.py`
- **Expected inputs:**
  - a running Gazebo world with `Panda` and `ur5_rg2`
  - Gazebo CLI available as `gz`
- **Expected outputs:**
  - [`rt_out/poses/panda/panda_pose.log`](../rt_out/poses/panda/panda_pose.log)
  - [`rt_out/poses/ur5/ur5_pose.log`](../rt_out/poses/ur5/ur5_pose.log)
- **Typical usage:**
  - `bash rt_out/scripts/run_all.sh`
- **Notes / gotchas:** this is a data-generation helper for the dynamic prototype, not a postprocessing step

### `rt_out/scripts/run_panda.sh`

- **Location:** [`rt_out/scripts/run_panda.sh`](../rt_out/scripts/run_panda.sh)
- **Status:** helper
- **Purpose:** sends the current scripted Panda joint sequence over Gazebo topics
- **When to use it:** normally via `run_all.sh`, or directly if you only want Panda motion
- **Expected inputs:** a running Gazebo world with the `Panda` model
- **Expected outputs:** robot motion in simulation; indirectly contributes to `panda_pose.log`
- **Typical usage:**
  - `bash rt_out/scripts/run_panda.sh`
- **Notes / gotchas:** the sequence is operational/project-specific, but it is the current data source for the trusted Panda prototype frames

### `rt_out/scripts/run_ur5.sh`

- **Location:** [`rt_out/scripts/run_ur5.sh`](../rt_out/scripts/run_ur5.sh)
- **Status:** helper
- **Purpose:** sends the current scripted UR5/RG2 joint sequence over Gazebo topics
- **When to use it:** normally via `run_all.sh`, or directly if you only want UR5 motion
- **Expected inputs:** a running Gazebo world with the `ur5_rg2` model
- **Expected outputs:** robot motion in simulation; indirectly contributes to `ur5_pose.log`
- **Typical usage:**
  - `bash rt_out/scripts/run_ur5.sh`
- **Notes / gotchas:** like the Panda helper, this is operational data generation for the current prototype
