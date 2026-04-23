# Gazebo to Sionna Pipeline

Gazebo-to-Sionna RT pipeline for synthetic wireless and 3D-scene research. This repository converts a Gazebo-defined robotic lab world into ray-tracing-ready scene representations for Mitsuba and Sionna RT. It extracts static and dynamic scene manifests, prepares geometry for radio simulation, builds static and frame-specific XML scenes, and runs sanity evaluations for a prototype Panda/UR5 environment. :contentReference[oaicite:0]{index=0} :contentReference[oaicite:1]{index=1}

The project is organized around two connected sides. The **Gazebo side** contains the world files, model assets, plugins, and motion/logging helpers used to define and simulate the scene. The **RT side** lives under `rt_out/` and contains the preprocessing, mesh preparation, manifest generation, XML export, and evaluation pipeline used to translate that scene into Mitsuba/Sionna inputs. :contentReference[oaicite:2]{index=2} :contentReference[oaicite:3]{index=3}

The current validated pipeline supports:
- rigid non-actor Gazebo scene content
- static scene export to Mitsuba and Sionna RT
- dynamic prototype motion for **Panda** and **ur5_rg2**
- exactly **3 prototype frames**
- an explicit **28 GHz** RT baseline
- single-RX and 3-frame × 3-RX sanity evaluation flows :contentReference[oaicite:4]{index=4}

At a high level, the workflow is:
1. create or update the Gazebo world and models
2. launch the RT world and, when needed, record Panda/UR5 pose logs
3. extract static and dynamic manifests from `myworld_rt.sdf`
4. build geometry and static registries
5. merge the static scene by material
6. generate Mitsuba and Sionna XML scenes
7. build dynamic prototype frames and per-frame transformed meshes
8. compose static + dynamic frame scenes
9. run RT sanity checks and export CSV summaries :contentReference[oaicite:5]{index=5}

This repository is currently best understood as a **validated prototype pipeline**, not yet a fully generalized Gazebo-to-RT system. The active flow is still scoped to the current lab world, the configured Panda/UR5 dynamic prototype, prepared static converted meshes, and selected frame/sample definitions. Gazebo actors are present in the world files but are not yet integrated into the active RT path. :contentReference[oaicite:6]{index=6} :contentReference[oaicite:7]{index=7} :contentReference[oaicite:8]{index=8}

## Repository guide

Start here depending on what you need:

- **Project structure and pipeline overview:** `docs/project_roadmap.md`
- **Software requirements and required inputs:** `docs/requirements_and_inputs.md`
- **Step-by-step execution guide:** `docs/step_by_step_guide.md`
- **Configs and world-specific parts:** `docs/configs_and_world_specific_parts.md`
- **Script-by-script reference:** `docs/script_reference.md`
- **Miscellaneous and historical notes:** `docs/misc_and_legacy.md` :contentReference[oaicite:9]{index=9} :contentReference[oaicite:10]{index=10} :contentReference[oaicite:11]{index=11}
