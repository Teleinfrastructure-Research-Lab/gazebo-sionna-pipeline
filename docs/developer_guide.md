# Developer Guide

This guide preserves the architectural and contract details needed to extend the
pipeline without mixing them into the quickstart docs.

Current project state to keep in mind while extending the repo:

- the validated RT baseline remains the static, rigid, actor-aware, and
  semantic-ablation branches
- `perception_rt_small_v0` is a pilot extension layered on top of the RT
  branches rather than a replacement for them
- the current final perception artifact is the strict labeled RGB point cloud
  export under
  `rt_out/experiments/perception_rt_small_v0/reconstruction/labeled_colorized_pcl_sync/`
- in this checkout, actor-aware RT/label source data may come from
  `rt_out/experiments/semantic_ablation.zip`; any `semantic_ablation_*`
  deletion or archive decision should be handled separately from normal
  perception pilot updates

## Perception Pilot Contracts

The current perception pilot has a few strict contracts that should not be
blurred while extending the repo:

- stable instance IDs used by the final labeled PCL export come from
  `rt_out/experiments/perception_rt_small_v0/perception_sdf/stable_instance_label_map.json`
- `gazebo_instance_count` from Gazebo panoptic capture is only a bridge/debug
  quantity and is not the final stable `instance_id`
- the final public PLY export under
  `rt_out/experiments/perception_rt_small_v0/reconstruction/labeled_colorized_pcl_sync/`
  contains exactly:
  `x y z red green blue class_label instance_id`
- bridge/debug fields such as `pixel_u`, `pixel_v`,
  `compact_instance_label`, and `gazebo_instance_count` are used internally
  during synchronized labeling but are not exported in the final public PLY
- the simplified central dataset index now tracks selected-frame metadata,
  camera metadata, panoptic artifacts, RT links, wireless labels, and final
  labeled PCL links only; retired RGB-D/direct-PCL/sync-RGB-PCL branches are
  no longer part of the active index contract

## Design Principles

- Keep the static scene frozen and reusable. Once static geometry is merged by
  material, dynamic and experiment branches should compose against the merged
  manifest instead of rebuilding static assets unnecessarily.
- Treat Panda/UR5 as rigid dynamic models. Their motion is represented by pose
  logs, link poses, visual joins, and rigid mesh exports.
- Keep Gazebo actor handling separate. Actors are skinned animated meshes, so
  they need metadata extraction, frame sampling, and Blender evaluation rather
  than the rigid link-pose parser.
- Use composed manifests as the bridge to Sionna XML. XML builders should read a
  composed frame manifest and avoid re-discovering scene structure.
- Make generated outputs reproducible, but avoid committing large or disposable
  generated data unless it is intentionally curated.

## Manifest Contracts

### Static Manifest

`rt_out/manifests/static_manifest.json` is produced by `00`. It records world
models treated as static, their model/link/visual poses, and geometry references.
It is an extraction artifact, not a Sionna-ready scene.

Important expectations:

- model and link records have stable names and poses
- visual records identify geometry type and source mesh where applicable
- actors are not folded into this manifest

### Merged Static Manifest

`rt_out/static_scene/export/merged_static_manifest.json` is produced by `20`.
It is the frozen baseline used by static XML generation and frame composition.

Important expectations:

- entries are grouped by semantic material
- mesh paths point to merged material PLYs
- transforms are already baked into merged meshes where required
- downstream frame composition should not mutate this file

### Dynamic Frame Manifest

`rt_out/dynamic_scene/frame_XXX/dynamic_frame_XXX_manifest.json` is produced by
`32`. It describes frame-local rigid Panda/UR5 meshes.

Important expectations:

- frame ID and source sample index match the configured prototype frame
- each entry represents baked world-space mesh geometry for one renderable visual
- mesh paths exist before composition
- rigid dynamic material assignment is controlled by the dynamic config and XML builder

Illustrative compact shape:

```json
{
  "frame_id": 0,
  "source_sample_index": 0,
  "exported_visuals": [
    {
      "id": "Panda__panda_link0__panda_link0_visual",
      "source": "dynamic",
      "model": "Panda",
      "link_name": "panda_link0",
      "mesh_path": "rt_out/dynamic_scene/frame_000/dynamic_meshes/...",
      "baked_world_geometry": true
    }
  ]
}
```

### Actor Manifest

`rt_out/manifests/actor_manifest.json` is produced by `40`. It records world
actor metadata and resolved asset URIs.

Important expectations:

- actors are sourced from Gazebo `<actor>` entries
- mesh/script/trajectory references are resolved against `models/`
- static actors and trajectory actors are distinguished
- no actor is implicitly included in RT unless later sampling/export enables it

### Actor Frame Samples

`rt_out/dynamic_frames/actor_frame_samples.json` is produced by `41`. It maps
enabled actors to the prototype frame IDs and selected actor times/poses.

Experiment-local branches can emit the same schema under an experiment output
root through `exp_build_actor_frame_samples.py`.

Important expectations:

- frame IDs align with the rigid prototype frames
- material labels are explicit and valid against RT material config
- runtime phase claims are not inferred unless the config explicitly supports them

### Actor Frame Manifest

`rt_out/dynamic_scene/frame_XXX/actor_frame_XXX_manifest.json` is produced by
`42`. It describes baked actor PLYs for one frame.

Important expectations:

- each actor entry has `source == "actor"`
- baked geometry is frame-local but already in world coordinates
- `material_label` is explicit
- alignment metadata records the export-time correction policy

Illustrative compact shape:

```json
{
  "frame_id": 0,
  "source_sample_index": 0,
  "exported_actors": [
    {
      "id": "actor__actor_walking__frame_000",
      "source": "actor",
      "actor_name": "actor_walking",
      "exported_mesh_path": "rt_out/dynamic_scene/frame_000/actor_meshes/actor__actor_walking__frame_000.ply",
      "material_label": "human_skin",
      "baked_world_geometry": true,
      "alignment_policy": "bounds_center_xy_to_root",
      "z_alignment_policy": "bounds_min_z_to_floor"
    }
  ]
}
```

### Composed Frame Manifest

`rt_out/composed_scene/frame_XXX/composed_frame_XXX_manifest.json` is produced by
`33`. It is the contract consumed by `34`.

Important expectations:

- static entries come from the merged static baseline
- dynamic entries come from the rigid dynamic frame manifest
- actor entries are present only when `--actor-frame-manifest` is supplied
- `static_count`, `dynamic_count`, `actor_count`, and `total_count` match entries
- mesh paths exist and are suitable for Sionna XML emission

Illustrative compact shape:

```json
{
  "frame_id": 0,
  "source_sample_index": 0,
  "static_count": 11,
  "dynamic_count": 21,
  "actor_count": 1,
  "total_count": 33,
  "entries": [
    {
      "id": "metal",
      "source": "static",
      "mesh_path": "rt_out/static_scene/export/merged_by_material/metal.ply",
      "material_label": "metal"
    },
    {
      "id": "Panda__panda_link0__panda_link0_visual",
      "source": "dynamic",
      "mesh_path": "rt_out/dynamic_scene/frame_000/dynamic_meshes/...",
      "material_label": "metal"
    },
    {
      "id": "actor__actor_walking__frame_000",
      "source": "actor",
      "mesh_path": "rt_out/dynamic_scene/frame_000/actor_meshes/actor__actor_walking__frame_000.ply",
      "material_label": "human_skin"
    }
  ]
}
```

### Sionna XML Assumptions

Sionna XML files emitted by `23` and `34` assume:

- radio materials are defined from `rt_material_mapping.json`
- geometry mesh paths are valid from the repository root
- runtime TX/RX placement is handled by sanity or experiment scripts, not by XML
- `scene.frequency` is set by the runner after load

## Extending Static Scene Support

To add static assets:

1. Add or update model assets under `models/`.
2. Ensure `myworld_rt.sdf` includes the intended static content.
3. Update `rt_out/materials/material_map.json` so static objects map to semantic labels.
4. Provide converted mesh assets when the static registry expects them.
5. Rerun static extraction, validation, registry, merge, and XML generation.

Static merge assumptions:

- geometry is grouped by semantic material
- missing or unsupported meshes should fail early
- asset-specific correction hooks should remain narrow and documented
- the merged static manifest is the stable downstream input

## Extending Rigid Dynamic Model Support

`dynamic_prototype_config.json` controls the rigid dynamic branch. Extending it
to another rigid model requires more than adding a name:

- pose logs must exist and use a parseable sample structure
- expected link sets and renderable visual counts must be known
- model SDF links and visuals must map cleanly to pose-log link names
- `31` must be able to join each sampled link pose to renderable visuals
- `32` must be able to import and export the source meshes through Blender
- `33`/`34` must preserve counts and material assignment expectations

For a new robot family, prefer adding explicit config and validation rather than
making the Panda/UR5 path silently permissive.

## Extending Actor Support

Actor support is intentionally separate from rigid dynamic support because
Gazebo actors are skinned animated meshes. The current branch is:

1. `40_extract_actor_manifest.py`: read world-level actor metadata and resolve assets.
2. `41_build_actor_frame_samples.py`: pick actor samples for the three prototype frames.
3. `42_export_actor_frame_meshes.py`: ask Blender to evaluate the actor and write baked PLYs.
4. `33`/`34`: compose actor entries and emit Sionna XML.

Do not merge actor logic into the Panda/UR5 pose parser unless the underlying
representation changes. Actor timing, skinning, and floor alignment are different
problems from rigid link poses.

The current export policies are:

- `bounds_center_xy_to_root`: shift baked vertices in XY so bounds center matches the sampled root pose.
- `bounds_min_z_to_floor`: shift baked vertices in Z so actor bounds minimum sits on the chosen floor plane.
- `floor_z = 0.1`: current floor plane used by the validated prototype.

These are explicit export-time corrections. They are useful for RT geometry
alignment, but they are not a claim that the baked mesh perfectly matches
Gazebo-runtime actor animation phase.

## Extending Experiment Wrappers

The current `semantic_ablation_rigid_200f` experiment is the rigid baseline.
Its wrappers call lower-level scripts in this order:

1. sample experiment frames
2. build rigid frame records
3. join rigid visuals
4. batch export rigid meshes
5. batch compose frame manifests
6. batch build Sionna XML
7. batch run multi-RX RT
8. build labels
9. build feature tables
10. run ablations

## Extending Experiment Branches With Actors

Actor sampling stays separate from rigid frame sampling because Gazebo actors are
skinned animated meshes, not rigid pose-log link trees. The actor-aware
`semantic_ablation_actor_200f` branch therefore adds one experiment-local stage
instead of duplicating the whole rigid pipeline:

1. `exp_build_actor_frame_samples.py` builds experiment-local actor frame
   samples for arbitrary sampled-frame lists.
2. `exp_export_dynamic_meshes_batch.py --include-actors` reuses
   `dynamic_actor/42_export_actor_frame_meshes.py` for batch actor export.
3. `exp_compose_frame_manifests_batch.py --include-actors` reuses
   `33 --actor-frame-manifest`.
4. `exp_build_sionna_xml_batch.py` reuses `34` unchanged because actor entries
   are already in the composed manifests.

`exp_build_actor_frame_samples.py` exists because `41` is prototype-oriented:
it assumes the fixed three-frame branch, while experiment wrappers need the same
actor-sample schema for arbitrary sampled-frame lists, `--max-frames` debug
runs, and frame-ID subsets.

Feature consequences:

- raw occupancy features naturally include actor meshes once the composed
  manifests include actor mesh paths
- object-aware features need explicit `source == "actor"` handling so actor
  entries are not silently dropped
- `human_skin` should be present in `materials_of_interest` when actor material
  features are expected

Generated-output hygiene for the actor-aware 200f branch:

- keep actor experiment outputs under
  `rt_out/experiments/semantic_ablation_actor_200f/`
- do not write experiment actor meshes/manifests into the global
  `rt_out/dynamic_scene/` or `rt_out/composed_scene/` branches
- do not commit large generated meshes, XML batches, RT CSVs, or `.blend`
  timelines unless they are intentional fixtures

To add actors later, the experiment would need explicit changes to:

- experiment config schema
- actor sample generation across 200 frames
- actor mesh export batch stage
- composition wrapper inputs
- XML batch validation
- label provenance
- feature builders, if actor-aware features are desired
- regression tests and paper-facing interpretation

Do not extend the existing 200-frame branch by assuming the three-frame actor
samples generalize.

## Testing Expectations

Before considering a pipeline change healthy, run:

```bash
python3 -m py_compile rt_out/scripts/**/*.py
python3 rt_out/scripts/dynamic_rigid/35_run_prototype_three_frame_rt_sanity.py
python3 rt_out/scripts/dynamic_rigid/35_run_prototype_three_frame_rt_sanity.py --include-actors
python3 rt_out/scripts/dynamic_rigid/36_run_three_frame_three_rx_rt_sanity.py --include-actors
```

If your shell does not expand `**`, use:

```bash
find rt_out/scripts -name '*.py' -print0 | xargs -0 python3 -m py_compile
```

For actor visual inspection:

```bash
BLENDER=blender \
python3 rt_out/scripts/validation/56_build_composed_frame_blender_scene.py \
  --composed-manifest rt_out/composed_scene/frame_000/composed_frame_000_manifest.json \
  --output-root rt_out/composed_scene/frame_000/blender_inspection_after_reorg
```
