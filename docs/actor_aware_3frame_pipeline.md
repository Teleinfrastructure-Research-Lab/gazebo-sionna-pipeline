# Actor-Aware 3-Frame Prototype Pipeline

This document covers the optional actor branch for the validated three-frame
prototype. For broad architecture and extension guidance, see
[Pipeline Overview](pipeline_overview.md) and [Developer Guide](developer_guide.md).
For the actor-aware 200-frame experiment branch, see
[Actor-Aware Semantic Ablation 200f Pipeline](semantic_ablation_actor_200f_pipeline.md).

## Scope

The actor branch supports:

- extracting Gazebo `<actor>` metadata from `myworld_rt.sdf`
- generating actor samples for the three prototype frames
- exporting posed actor meshes through Blender
- composing actor meshes into the normal frame manifests
- emitting Sionna XML with actor material labels
- running `35 --include-actors` and `36 --include-actors`
- visual and geometric validation through the `validation/` scripts

It does not expand the separate 200-frame experiment branches. Keep this page
for the validated three-frame actor prototype only.

Current validation status:

- actor-aware `35` passes
- actor-aware `36` passes for all 9 frame/RX rows
- delay statistics are populated for non-zero-path rows

## Data Flow

```text
myworld_rt.sdf + models/
  -> dynamic_actor/40_extract_actor_manifest.py
  -> rt_out/manifests/actor_manifest.json

actor_manifest.json + actor_dynamic_config.json
  -> dynamic_actor/41_build_actor_frame_samples.py
  -> rt_out/dynamic_frames/actor_frame_samples.json

actor_frame_samples.json + actor_manifest.json
  -> dynamic_actor/42_export_actor_frame_meshes.py
  -> rt_out/dynamic_scene/frame_XXX/actor_frame_XXX_manifest.json
  -> rt_out/dynamic_scene/frame_XXX/actor_meshes/*.ply

actor frame manifest + static baseline + Panda/UR5 dynamic manifest
  -> dynamic_rigid/33_compose_prototype_frame_scene.py
  -> dynamic_rigid/34_build_prototype_frame_sionna_xml.py
  -> Sionna sanity through 35/36
```

Actor geometry is included only when an actor frame manifest is passed to `33`
or when `35`/`36` are run with `--include-actors`.

## Current Actor Outputs

Current three-frame actor outputs are under:

```text
rt_out/manifests/actor_manifest.json
rt_out/dynamic_frames/actor_frame_samples.json
rt_out/dynamic_scene/frame_000/actor_frame_000_manifest.json
rt_out/dynamic_scene/frame_001/actor_frame_001_manifest.json
rt_out/dynamic_scene/frame_002/actor_frame_002_manifest.json
rt_out/dynamic_scene/frame_XXX/actor_meshes/
rt_out/dynamic_scene/frame_XXX/actor_metadata/
```

Actor entries are composed into:

```text
rt_out/composed_scene/frame_XXX/composed_frame_XXX_manifest.json
rt_out/composed_scene/frame_XXX/frame_XXX_sionna.xml
```

## Alignment Policy

Actor export uses explicit geometry corrections:

- `bounds_center_xy_to_root`: shifts baked vertices in XY so the mesh bounds center matches the sampled root pose.
- `bounds_min_z_to_floor`: shifts baked vertices in Z so the mesh lower bound sits on the floor plane.
- `floor_z = 0.1`: the floor plane used by the current validated prototype.

These are export-time corrections for RT geometry. They are not a claim that the
exported mesh is a perfect Gazebo-runtime animation phase match.

## Build Actor Inputs

### 1. Extract Actor Metadata

```bash
python3 rt_out/scripts/dynamic_actor/40_extract_actor_manifest.py \
  --world myworld_rt.sdf \
  --models-root models \
  --output rt_out/manifests/actor_manifest.json
```

### 2. Build Actor Frame Samples

```bash
python3 rt_out/scripts/dynamic_actor/41_build_actor_frame_samples.py \
  --actor-manifest rt_out/manifests/actor_manifest.json \
  --actor-config rt_out/config/actor_dynamic_config.json \
  --dynamic-prototype-config rt_out/config/dynamic_prototype_config.json \
  --rt-material-config rt_out/config/rt_material_mapping.json \
  --output rt_out/dynamic_frames/actor_frame_samples.json
```

## Export Actor Meshes Manually

Usually `35 --include-actors` and `36 --include-actors` call `42`
automatically. Manual export is useful for debugging one frame:

```bash
python3 rt_out/scripts/dynamic_actor/42_export_actor_frame_meshes.py \
  --frame-id 0 \
  --actor-samples rt_out/dynamic_frames/actor_frame_samples.json \
  --actor-manifest rt_out/manifests/actor_manifest.json \
  --output-root rt_out/dynamic_scene \
  --alignment-policy bounds_center_xy_to_root \
  --z-alignment-policy bounds_min_z_to_floor \
  --floor-z 0.1
```

Expected frame-0 output:

```text
rt_out/dynamic_scene/frame_000/actor_frame_000_manifest.json
rt_out/dynamic_scene/frame_000/actor_meshes/
rt_out/dynamic_scene/frame_000/actor_metadata/
```

## Compose One Actor-Aware Frame Manually

```bash
python3 rt_out/scripts/dynamic_rigid/33_compose_prototype_frame_scene.py \
  --frame-id 0 \
  --actor-frame-manifest rt_out/dynamic_scene/frame_000/actor_frame_000_manifest.json

python3 rt_out/scripts/dynamic_rigid/34_build_prototype_frame_sionna_xml.py \
  --frame-id 0

/path/to/your/sionna/python \
  rt_out/scripts/static_scene/24_run_sionna_rt_sanity.py \
  --xml rt_out/composed_scene/frame_000/frame_000_sionna.xml
```

## End-To-End Actor Runs

Single-RX three-frame sanity:

```bash
python3 rt_out/scripts/dynamic_rigid/35_run_prototype_three_frame_rt_sanity.py --include-actors
```

Three-frame, three-RX sanity:

```bash
python3 rt_out/scripts/dynamic_rigid/36_run_three_frame_three_rx_rt_sanity.py --include-actors
```

Both commands export actor meshes for frames `0`, `1`, and `2`, compose actor
entries, build frame XML, and run Sionna sanity checks. `35` and `36` remain
actor-free by default.

## Validation And Debug Tools

Prerequisites before running validation/debug scripts:

- actor manifest exists at `rt_out/manifests/actor_manifest.json`
- actor frame samples exist at `rt_out/dynamic_frames/actor_frame_samples.json`
- actor meshes have been exported for the frame being inspected
- composed frame manifest exists when using the composed-frame Blender builder
- `BLENDER` points to a usable Blender binary for Blender scene builders

| Script | Purpose | Prerequisite | Typical command |
| --- | --- | --- | --- |
| `rt_out/scripts/validation/50_build_actor_validation_samples.py` | Build larger offline actor validation samples. | actor manifest and actor config | see `--help` |
| `rt_out/scripts/validation/51_export_actor_validation_meshes.py` | Export actor validation mesh batches. | validation samples, actor manifest, Blender | see `--help` |
| `rt_out/scripts/validation/52_build_actor_blender_validation_scene.py` | Build actor-only Blender validation scenes. | exported validation meshes, static context, Blender | see `--help` |
| `rt_out/scripts/validation/53_diagnose_actor_validation_alignment.py` | Diagnose horizontal actor/path alignment. | exported actor metadata | see `--help` |
| `rt_out/scripts/validation/54_build_actor_prototype_mesh_index.py` | Build a mesh index for three-frame actor inspection. | actor frame manifests from `42` or `35 --include-actors` | see `--help` |
| `rt_out/scripts/validation/55_diagnose_actor_floor_alignment.py` | Diagnose actor/floor vertical alignment. | exported actor metadata and static floor context | see `--help` |
| `rt_out/scripts/validation/56_build_composed_frame_blender_scene.py` | Import a composed frame into Blender for inspection. | composed frame manifest and Blender | see complete sequence below |

Complete composed-frame Blender inspection sequence:

```bash
python3 rt_out/scripts/dynamic_actor/40_extract_actor_manifest.py
python3 rt_out/scripts/dynamic_actor/41_build_actor_frame_samples.py
python3 rt_out/scripts/dynamic_rigid/35_run_prototype_three_frame_rt_sanity.py --include-actors

BLENDER=blender \
python3 rt_out/scripts/validation/56_build_composed_frame_blender_scene.py \
  --composed-manifest rt_out/composed_scene/frame_000/composed_frame_000_manifest.json \
  --output-root rt_out/composed_scene/frame_000/blender_inspection_after_reorg
```

Use `BLENDER=/path/to/blender` instead if Blender is not on `PATH`.

## Limitations

- Actor support is validated only for the three-frame prototype branch.
- Actor geometry is baked for RT export; it is not live Gazebo actor simulation.
- The current horizontal and vertical alignment policies are export-time corrections.
- The actor-aware 200-frame experiment is documented separately in `semantic_ablation_actor_200f_pipeline.md`.
- Legacy actor spike scripts remain in `rt_out/scripts/legacy/` for reference only.
