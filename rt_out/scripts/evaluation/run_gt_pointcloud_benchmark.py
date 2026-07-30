#!/usr/bin/env python3
"""Prepare, preflight, or run a restart-safe canonical GT point-cloud batch."""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'rt_out/experiments/semantic_ablation_actor_2446f_10hz/run_20260710_172015'
DEFAULT_ROOT = ROOT / 'rt_out/experiments/semantic_ablation_actor_2446f_10hz/run_20260710_172015_gt100'
SMOKE_CONFIGS = ROOT / 'rt_out/experiments/semantic_ablation_actor_2446f_10hz/run_20260710_172015_smoke10/config'
FRAME_COUNT = 100
SUMMARY_SCHEMA_VERSION = 1
PRODUCER_VERSION = 'benchmark-summary-v1'

class BenchmarkError(RuntimeError):
    pass

def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception as exc:
        raise BenchmarkError(f'Cannot read {path}: {exc}') from exc

def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--frame-count', type=int, default=FRAME_COUNT, help='Canonical consecutive frame count (default: 100).')
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--preflight', action='store_true', help='Validate an existing root without creating or changing files.')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--write-summary', action='store_true', help='Write reports/benchmark_summary.json from existing raw telemetry without rerunning stages.')
    parser.add_argument('--install-fine-mapping', action='store_true', help='Install missing final fine taxonomy files; never overwrites them.')
    return parser.parse_args()

def expected_frames() -> list[int]:
    return list(range(FRAME_COUNT))

def frame_ids(payload: dict[str, Any], label: str) -> list[int]:
    frames = payload.get('frames')
    if not isinstance(frames, list):
        raise BenchmarkError(f'{label} lacks frames list')
    ids = []
    for frame in frames:
        if not isinstance(frame, dict) or isinstance(frame.get('frame_id'), bool):
            raise BenchmarkError(f'{label} has malformed frame record')
        ids.append(int(frame['frame_id']))
    if ids != expected_frames():
        raise BenchmarkError(f'{label} frame IDs are not exactly 0..{FRAME_COUNT - 1}')
    return ids

def ensure_fine_mapping(root: Path, install: bool) -> None:
    """Require the final mapping, optionally copying only missing authoritative files."""
    for name in ('fine_panoptic_taxonomy.json', 'fine_to_coarse_mapping.json'):
        target = root / 'config' / name
        if target.is_file():
            read_json(target)
            continue
        if not install:
            raise BenchmarkError(f'Missing final fine taxonomy/mapping: {target}; rerun with --install-fine-mapping')
        source = SMOKE_CONFIGS / name
        if not source.is_file():
            raise BenchmarkError(f'Missing authoritative final fine taxonomy/mapping: {source}')
        read_json(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

def prepare(root: Path, install_fine_mapping: bool=False) -> None:
    config_path = root / 'config/experiment_config.json'
    selection_path = root / 'frames/sampled_frames.json'
    if root.exists() and (not config_path.exists()):
        raise BenchmarkError(f'Refusing to use non-benchmark or partial root: {root}')
    source_selection = read_json(SOURCE / 'frames/sampled_frames.json')
    selected = [item for item in source_selection.get('frames', []) if 0 <= int(item['frame_id']) < FRAME_COUNT]
    if [int(item['frame_id']) for item in selected] != expected_frames():
        raise BenchmarkError('Canonical 10 Hz timeline does not contain source frames 0..99')
    if config_path.exists() or selection_path.exists():
        if not (config_path.is_file() and selection_path.is_file()):
            raise BenchmarkError('Benchmark preparation is partial; refuse to overwrite')
        existing = read_json(selection_path)
        frame_ids(existing, 'existing sampled_frames')
        ensure_fine_mapping(root, install_fine_mapping)
        return
    config = read_json(SOURCE / 'config/experiment_config.json')
    config.update({'experiment_name': root.name, 'num_frames': FRAME_COUNT, 'output_dir': str(root.relative_to(ROOT))})
    selection = dict(source_selection)
    selection.update({'generated_by': Path(__file__).name, 'experiment_name': root.name, 'frames': selected})
    write_json_atomic(config_path, config)
    write_json_atomic(selection_path, selection)
    ensure_fine_mapping(root, True)

def state_path(root: Path) -> Path:
    return root / 'benchmark_metrics.json'

def summary_path(root: Path) -> Path:
    return root / 'reports' / 'benchmark_summary.json'

def load_state(root: Path) -> dict[str, Any]:
    return read_json(state_path(root)) if state_path(root).is_file() else {'stages': {}, 'calendar_started_unix': time.time()}

def write_compact_summary(root: Path, state: dict[str, Any] | None=None) -> None:
    """Publish portable run facts without copying raw benchmark telemetry."""
    state = load_state(root) if state is None else state
    if not state_path(root).is_file():
        raise BenchmarkError(f'Missing raw benchmark telemetry: {state_path(root)}')
    config = read_json(root / 'config/experiment_config.json')
    sampled = read_json(root / 'frames/sampled_frames.json')
    validation = state.get('validation')
    if not isinstance(validation, dict) or validation.get('ply_count') is None:
        raise BenchmarkError('Raw benchmark telemetry lacks completed GT validation')
    stages = state.get('stages', {})
    if not isinstance(stages, dict):
        raise BenchmarkError('Raw benchmark telemetry has malformed stage data')
    status_counts: dict[str, int] = {}
    completed_stages = []
    for name, stage in stages.items():
        status = stage.get('status') if isinstance(stage, dict) else None
        if not isinstance(status, str):
            continue
        status_counts[status] = status_counts.get(status, 0) + 1
        if status in {'completed', 'reused'} and not re.search(r'_\d{3,}$', name):
            completed_stages.append(name)
    try:
        run_root = root.relative_to(ROOT).as_posix()
    except ValueError as exc:
        raise BenchmarkError(f'Benchmark root must be inside the repository: {root}') from exc
    frame_count = int(config.get('num_frames', validation['ply_count']))
    frames = sampled.get('frames', [])
    summary = {
        'schema_version': SUMMARY_SCHEMA_VERSION,
        'producer': {
            'script': 'rt_out/scripts/evaluation/run_gt_pointcloud_benchmark.py',
            'version': PRODUCER_VERSION,
        },
        'experiment': {
            'name': config.get('experiment_name', root.parent.name),
            'run_id': root.name,
            'run_root': run_root,
        },
        'workload': {
            'frame_count': frame_count,
            'sample_count': len(frames) if isinstance(frames, list) else None,
            'point_count_per_frame': int(validation['point_count_per_frame']),
            'receiver_count': len(config.get('rx_list', [])) if isinstance(config.get('rx_list', []), list) else None,
            'frequency_ghz': config.get('frequency_ghz'),
        },
        'completed_stages': sorted(completed_stages),
        'completed_stage_count': sum((count for status, count in status_counts.items() if status in {'completed', 'reused'})),
        'stage_status_counts': dict(sorted(status_counts.items())),
        'validation': {
            'status': 'passed',
            'frame_count': int(validation['ply_count']),
            'point_count_per_frame': int(validation['point_count_per_frame']),
            'static_block_sha256': validation.get('static_block_sha256'),
            'gt_ply_size_bytes': int(validation['gt_ply_size_bytes']),
        },
        'aggregate_sizes_bytes': {
            key: int(value) for key, value in state.get('size_bytes', {}).items()
            if key in {'gt_ply', 'dynamic_mesh', 'actor_mesh', 'metadata_manifests', 'benchmark_root'}
            and isinstance(value, (int, float))
        },
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
    }
    write_json_atomic(summary_path(root), summary)

def parse_time_v(path: Path) -> int:
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line.startswith('Maximum resident set size (kbytes):'):
            return int(line.rsplit(':', 1)[1].strip())
    raise BenchmarkError(f'/usr/bin/time did not report peak RSS: {path}')

def run_command(root: Path, name: str, command: list[str], complete: bool) -> str:
    state = load_state(root)
    if complete:
        state['stages'].setdefault(name, {'status': 'reused'})
        write_json_atomic(state_path(root), state)
        return ''
    with tempfile.NamedTemporaryFile(prefix='benchmark_time_', suffix='.txt', dir=root, delete=False) as handle:
        time_path = Path(handle.name)
    started = time.monotonic()
    try:
        result = subprocess.run(['/usr/bin/time', '-v', '-o', str(time_path), *command], cwd=ROOT, text=True, capture_output=True, check=False)
        if result.returncode:
            raise BenchmarkError(f'Stage {name} failed ({result.returncode}):\n{result.stdout}\n{result.stderr}')
        wall = time.monotonic() - started
        state['stages'][name] = {'status': 'completed', 'wall_seconds': wall, 'peak_rss_kib': parse_time_v(time_path), 'command': command}
        write_json_atomic(state_path(root), state)
        return result.stdout
    finally:
        time_path.unlink(missing_ok=True)

def stage_json(stdout: str, stage: str) -> dict[str, Any]:
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise BenchmarkError(f'Stage {stage} did not produce its expected JSON summary') from exc
    if not isinstance(value, dict):
        raise BenchmarkError(f'Stage {stage} JSON summary is not an object')
    return value

def valid_dynamic_frames(path: Path) -> bool:
    try:
        payload = read_json(path)
        frame_ids(payload, 'dynamic_frames')
        for frame in payload['frames']:
            if frame.get('source_sample_index') != frame.get('frame_id') or not isinstance(frame.get('timestamp'), dict):
                return False
        return True
    except BenchmarkError:
        return False

def valid_dynamic_visual_frames(path: Path) -> bool:
    try:
        payload = read_json(path)
        frame_ids(payload, 'dynamic_visual_frames')
        if payload.get('frame_count') != FRAME_COUNT:
            return False
        return all((frame.get('source_sample_index') == frame.get('frame_id') and isinstance(frame.get('renderable_visuals'), list) and frame['renderable_visuals'] for frame in payload['frames']))
    except BenchmarkError:
        return False

def valid_actor_samples(path: Path) -> bool:
    try:
        payload = read_json(path)
        frame_ids(payload, 'actor_frame_samples')
        return all((frame.get('source_sample_index') == frame.get('frame_id') and isinstance(frame.get('actors'), list) and (len(frame['actors']) == 1) for frame in payload['frames']))
    except BenchmarkError:
        return False

def valid_mesh_manifest(path: Path, frame_id: int, actor: bool) -> bool:
    try:
        payload = read_json(path)
        if payload.get('frame_id') != frame_id or payload.get('source_sample_index') != frame_id:
            return False
        entries = payload.get('exported_actors' if actor else 'exported_visuals')
        key = 'exported_mesh_path'
        if not isinstance(entries, list) or not entries:
            return False
        for entry in entries:
            mesh = Path(entry.get(key, ''))
            if not mesh.is_file() or mesh.stat().st_size <= 0:
                return False
        return True
    except (BenchmarkError, OSError):
        return False

def dynamic_manifest(root: Path, frame_id: int) -> Path:
    return root / 'frames/dynamic_meshes' / f'frame_{frame_id:03d}' / f'dynamic_frame_{frame_id:03d}_manifest.json'

def actor_manifest(root: Path, frame_id: int) -> Path:
    return root / 'frames/actor_meshes' / f'frame_{frame_id:03d}' / f'actor_frame_{frame_id:03d}_manifest.json'

def mesh_stage_summary(root: Path, actor: bool) -> dict[str, int]:
    manifest_for = actor_manifest if actor else dynamic_manifest
    expected = {manifest_for(root, frame_id) for frame_id in expected_frames()}
    directory = root / 'frames' / ('actor_meshes' if actor else 'dynamic_meshes')
    actual = set(directory.glob('frame_*/' + ('actor_frame_*_manifest.json' if actor else 'dynamic_frame_*_manifest.json'))) if directory.exists() else set()
    valid = [frame_id for frame_id in expected_frames() if valid_mesh_manifest(manifest_for(root, frame_id), frame_id, actor)]
    invalid = [frame_id for frame_id in expected_frames() if manifest_for(root, frame_id).exists() and frame_id not in valid]
    orphan_dirs = 0
    if directory.exists():
        for child in directory.glob('frame_*'):
            if child.is_dir() and (not any(child.iterdir())):
                continue
            if child.is_dir() and (not any((path.parent == child for path in actual))):
                orphan_dirs += 1
    return {'valid': len(valid), 'missing': FRAME_COUNT - len(valid) - len(invalid), 'invalid': len(invalid) + orphan_dirs, 'extra': len(actual - expected)}

def validate_mesh_stage(root: Path, actor: bool, allow_missing: bool=False) -> dict[str, int]:
    summary = mesh_stage_summary(root, actor)
    stage = 'actor' if actor else 'dynamic'
    if summary['invalid'] or summary['extra'] or (summary['missing'] and (not allow_missing)):
        raise BenchmarkError(f"{stage} mesh outputs invalid={summary['invalid']} missing={summary['missing']} extra={summary['extra']}")
    return summary

def preflight(root: Path) -> None:
    """Read-only validation for an existing canonical experiment root."""
    config = root / 'config/experiment_config.json'
    sampled = root / 'frames/sampled_frames.json'
    if not config.is_file() or not sampled.is_file():
        raise BenchmarkError(f'Missing experiment config or canonical frame selection under {root}')
    config_payload = read_json(config)
    if int(config_payload.get('num_frames', -1)) != FRAME_COUNT:
        raise BenchmarkError(f'experiment_config num_frames is not {FRAME_COUNT}')
    frame_ids(read_json(sampled), 'sampled_frames')
    for name in ('fine_panoptic_taxonomy.json', 'fine_to_coarse_mapping.json'):
        (target, source) = (root / 'config' / name, SMOKE_CONFIGS / name)
        if target.is_file():
            read_json(target)
        elif not source.is_file():
            raise BenchmarkError(f'Missing final fine taxonomy/mapping: {target} and {source}')
    dynamic = root / 'frames/dynamic_frames.json'
    visual = root / 'frames/dynamic_visual_frames.json'
    samples = root / 'frames/actor_frame_samples.json'
    if dynamic.exists() and (not valid_dynamic_frames(dynamic)):
        raise BenchmarkError('dynamic_frames is partial or inconsistent')
    if visual.exists() and (not valid_dynamic_visual_frames(visual)):
        raise BenchmarkError('dynamic_visual_frames is partial or inconsistent')
    if samples.exists() and (not valid_actor_samples(samples)):
        raise BenchmarkError('actor_frame_samples is partial or inconsistent')
    dynamic_summary = validate_mesh_stage(root, False, allow_missing=True)
    actor_summary = validate_mesh_stage(root, True, allow_missing=True)
    require_no_partial_gt(root)
    print(json.dumps({'preflight': 'PASS', 'frame_count': FRAME_COUNT, 'dynamic_meshes': dynamic_summary, 'actor_meshes': actor_summary, 'gt_staging': 'present' if (root / 'gt_scene_pointclouds.tmp').exists() else 'absent'}, sort_keys=True))

def tree_size(path: Path) -> int:
    return sum((item.stat().st_size for item in path.rglob('*') if item.is_file())) if path.exists() else 0

def validate_gt(root: Path) -> dict[str, Any]:
    output = root / 'gt_scene_pointclouds'
    summary = read_json(output / 'validation_summary.json')
    if summary.get('passed') is not True:
        raise BenchmarkError('GT validation_summary.json is not passed')
    index_path = output / 'pointcloud_index.csv'
    with index_path.open('r', encoding='utf-8', newline='') as handle:
        index = list(csv.DictReader(handle))
    if len(index) != FRAME_COUNT or sorted((int(row['frame_id']) for row in index)) != expected_frames():
        raise BenchmarkError('GT index does not contain exactly frames 0..99')
    ply_paths = [output / f'frame_{fid:03d}_gt_scene.ply' for fid in expected_frames()]
    actual = set(output.glob('frame_*_gt_scene.ply'))
    if set(ply_paths) != actual:
        raise BenchmarkError('GT PLY file set is partial or inconsistent')
    registry = read_json(output / 'label_registry.json')
    instances = {int(item['instance_id']): set(map(int, item.get('class_labels', [item['class_label']]))) for item in registry['instances']}
    allowed = {'class_label': {int(key) for key in registry['semantic_taxonomy']}, 'material_id': {int(key) for key in registry['materials']}, 'object_type_id': {int(key) for key in registry['object_types']}, 'source_type_id': {int(key) for key in registry['source_types']}}
    static_digest = None
    for path in ply_paths:
        with path.open('rb') as handle:
            header = []
            while True:
                line = handle.readline()
                if not line:
                    raise BenchmarkError(f'Incomplete PLY header: {path}')
                header.append(line)
                if line.strip() == b'end_header':
                    break
            if b'element vertex 100000\n' not in header:
                raise BenchmarkError(f'Wrong point count header: {path}')
            (digest, count, saw_dynamic, per_instance) = (hashlib.sha256(), 0, False, {})
            for raw in handle:
                fields = raw.split()
                if len(fields) != 8:
                    raise BenchmarkError(f'Malformed PLY row: {path}')
                xyz = [float(value) for value in fields[:3]]
                if not all((math.isfinite(value) for value in xyz)):
                    raise BenchmarkError(f'NaN/Inf: {path}')
                (semantic, instance, material, object_type, source_type) = map(int, fields[3:])
                if min(semantic, instance, material, object_type, source_type) <= 0:
                    raise BenchmarkError(f'Zero ID: {path}')
                if semantic not in allowed['class_label'] or material not in allowed['material_id'] or object_type not in allowed['object_type_id'] or (source_type not in allowed['source_type_id']) or (instance not in instances):
                    raise BenchmarkError(f'Unknown ID: {path}')
                per_instance.setdefault(instance, set()).add(semantic)
                if per_instance[instance] != {semantic} or semantic not in instances[instance]:
                    raise BenchmarkError(f'Invalid instance semantic: {path}')
                if source_type == 1:
                    if saw_dynamic:
                        raise BenchmarkError(f'Static block is not contiguous: {path}')
                    digest.update(raw)
                else:
                    saw_dynamic = True
                count += 1
            if count != 100000:
                raise BenchmarkError(f'Wrong point row count: {path}')
            if static_digest is None:
                static_digest = digest.hexdigest()
            elif static_digest != digest.hexdigest():
                raise BenchmarkError(f'Static block differs: {path}')
    return {'ply_count': FRAME_COUNT, 'point_count_per_frame': 100000, 'static_block_sha256': static_digest, 'gt_ply_size_bytes': sum((path.stat().st_size for path in ply_paths)), 'average_gt_ply_size_bytes': sum((path.stat().st_size for path in ply_paths)) / FRAME_COUNT}

def gt_complete(root: Path) -> bool:
    try:
        validate_gt(root)
        return True
    except (BenchmarkError, OSError):
        return False

def require_no_partial_gt(root: Path) -> None:
    output = root / 'gt_scene_pointclouds'
    if output.exists() and (not gt_complete(root)):
        raise BenchmarkError(f'Partial or inconsistent final GT output; refuse to overwrite: {output}')

def run(root: Path, install_fine_mapping: bool=False) -> None:
    prepare(root, install_fine_mapping)
    require_no_partial_gt(root)
    py = sys.executable
    frames = root / 'frames/sampled_frames.json'
    dynamic = root / 'frames/dynamic_frames.json'
    visual = root / 'frames/dynamic_visual_frames.json'
    config = root / 'config/experiment_config.json'
    run_command(root, 'dynamic_frames', [py, 'rt_out/scripts/dynamic_rigid/build_dynamic_pose_frames.py', '--frames-json', str(frames), '--output', str(dynamic)], valid_dynamic_frames(dynamic))
    run_command(root, 'dynamic_visual_frames', [py, 'rt_out/scripts/dynamic_rigid/resolve_dynamic_visual_frames.py', '--frames-json', str(frames), '--dynamic-frames', str(dynamic), '--output', str(visual)], valid_dynamic_visual_frames(visual))
    actor_samples = root / 'frames/actor_frame_samples.json'
    run_command(root, 'actor_samples', [py, 'rt_out/scripts/dynamic_actor/build_experiment_actor_frame_samples.py', '--config', str(config)], valid_actor_samples(actor_samples))
    validate_mesh_stage(root, False, allow_missing=True)
    validate_mesh_stage(root, True, allow_missing=True)
    for frame_id in expected_frames():
        (dynamic_path, actor_path) = (dynamic_manifest(root, frame_id), actor_manifest(root, frame_id))
        if dynamic_path.exists() and (not valid_mesh_manifest(dynamic_path, frame_id, False)):
            raise BenchmarkError(f'Partial dynamic output; refuse to overwrite: {dynamic_path}')
        if actor_path.exists() and (not valid_mesh_manifest(actor_path, frame_id, True)):
            raise BenchmarkError(f'Partial actor output; refuse to overwrite: {actor_path}')
        run_command(root, f'dynamic_mesh_{frame_id:03d}', [py, 'rt_out/scripts/dynamic_rigid/export_dynamic_frame_meshes.py', '--frame-id', str(frame_id), '--visual-frames-json', str(visual), '--output-root', str(root / 'frames/dynamic_meshes')], valid_mesh_manifest(dynamic_path, frame_id, False))
        run_command(root, f'actor_mesh_{frame_id:03d}', [py, 'rt_out/scripts/dynamic_actor/export_actor_frame_meshes.py', '--frame-id', str(frame_id), '--actor-samples', str(actor_samples), '--actor-manifest', 'rt_out/experiments/factory_panda_ur5/legacy_run_20260522_133045/manifests/actor_manifest.json', '--output-root', str(root / 'frames/actor_meshes'), '--alignment-policy', 'bounds_center_xy_to_root', '--z-alignment-policy', 'bounds_min_z_to_floor', '--floor-z', '0.1'], valid_mesh_manifest(actor_path, frame_id, True))
    validate_mesh_stage(root, False)
    validate_mesh_stage(root, True)
    topology_stdout = run_command(root, 'actor_topology_gate', [py, 'rt_out/scripts/experiments/semantic_ablation/semantic_ablation_build_gt_scene_pointcloud_smoke.py', '--experiment-root', str(root), '--expected-frame-count', str(FRAME_COUNT)], False)
    if '"connectivity_verdict": "PASS:' not in topology_stdout:
        raise BenchmarkError('Actor topology gate did not pass')
    complete = gt_complete(root)
    gt_stdout = run_command(root, 'gt_pointclouds', [py, 'rt_out/scripts/experiments/semantic_ablation/semantic_ablation_build_gt_scene_pointcloud_smoke.py', '--experiment-root', str(root), '--expected-frame-count', str(FRAME_COUNT), '--generate'], complete)
    validation = validate_gt(root)
    state = load_state(root)
    state['validation'] = validation
    gt_stage = state['stages'].get('gt_pointclouds', {})
    if complete:
        state['gt_resume'] = {'resumed_frames': FRAME_COUNT, 'newly_generated_frames': 0, 'status': 'reused_final_output'}
    else:
        gt_result = stage_json(gt_stdout, 'gt_pointclouds')
        resumed = gt_result.get('resumed_frames')
        generated = gt_result.get('newly_generated_frames')
        if not isinstance(resumed, int) or not isinstance(generated, int) or resumed < 0 or (generated < 0) or (resumed + generated != FRAME_COUNT):
            raise BenchmarkError('GT stage returned invalid resume counts')
        state['gt_resume'] = {'resumed_frames': resumed, 'newly_generated_frames': generated, 'status': 'completed'}
    if gt_stage.get('status') == 'completed':
        peak_rss = gt_stage.get('peak_rss_kib')
        if not isinstance(peak_rss, int) or peak_rss <= 0:
            raise BenchmarkError('GT stage completed without a valid per-command peak RSS measurement')
        state['peak_memory_validation'] = {'gt_peak_rss_kib': peak_rss, 'measurement': '/usr/bin/time -v', 'bounded_memory_generation': True}
    else:
        state['peak_memory_validation'] = {'gt_peak_rss_kib': None, 'measurement': 'not remeasured because valid GT output was reused', 'bounded_memory_generation': True}
    state['size_bytes'] = {'gt_ply': validation['gt_ply_size_bytes'], 'dynamic_mesh': tree_size(root / 'frames/dynamic_meshes'), 'actor_mesh': tree_size(root / 'frames/actor_meshes'), 'metadata_manifests': tree_size(root) - validation['gt_ply_size_bytes'] - tree_size(root / 'frames/dynamic_meshes') - tree_size(root / 'frames/actor_meshes'), 'benchmark_root': tree_size(root)}
    state['active_total_wall_seconds'] = sum((float(stage['wall_seconds']) for stage in state['stages'].values() if stage.get('status') == 'completed'))
    state['calendar_elapsed_seconds'] = time.time() - state['calendar_started_unix']
    state['taxonomy_sha256'] = hashlib.sha256((root / 'config/fine_panoptic_taxonomy.json').read_bytes()).hexdigest()
    state['fine_to_coarse_mapping_sha256'] = hashlib.sha256((root / 'config/fine_to_coarse_mapping.json').read_bytes()).hexdigest()
    write_json_atomic(state_path(root), state)
    write_compact_summary(root, state)

def main() -> None:
    global FRAME_COUNT
    args = parse_args()
    if args.frame_count <= 0:
        raise BenchmarkError('--frame-count must be positive')
    FRAME_COUNT = args.frame_count
    actions = (args.prepare, args.preflight, args.run, args.write_summary)
    if sum((bool(value) for value in actions)) != 1:
        raise BenchmarkError('Specify exactly one of --prepare, --preflight, --run, or --write-summary')
    if args.install_fine_mapping and (not args.run):
        raise BenchmarkError('--install-fine-mapping is only valid with --run')
    root = args.root.expanduser().resolve()
    if args.prepare:
        prepare(root)
    elif args.preflight:
        preflight(root)
    elif args.write_summary:
        write_compact_summary(root)
    else:
        run(root, args.install_fine_mapping)
if __name__ == '__main__':
    try:
        main()
    except BenchmarkError as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        raise SystemExit(1)
