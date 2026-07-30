#!/usr/bin/env python3
"""Read-only validator and Open3D visualizer for canonical GT scene point clouds."""
from __future__ import annotations
import argparse
import colorsys
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any
import numpy as np
ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ROOT = ROOT / 'rt_out/experiments/semantic_ablation_actor_2446f_10hz/run_20260710_172015_smoke10/gt_scene_pointclouds'
FIELDS = ('x', 'y', 'z', 'class_label', 'instance_id', 'material_id', 'object_type_id', 'source_type_id')
LABEL_FIELDS = ('class_label', 'instance_id', 'material_id', 'object_type_id', 'source_type_id')
REGISTRY_SECTIONS = {'class_label': 'semantic_taxonomy', 'material_id': 'materials', 'object_type_id': 'object_types', 'source_type_id': 'source_types'}

class GtViewError(RuntimeError):
    pass

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--frame', type=int, required=True, help='First sparse frame ID, e.g. 0.')
    parser.add_argument('--compare-frame', type=int, default=None, help='Second frame ID for ordered comparison.')
    parser.add_argument('--mode', choices=('semantic', 'instance', 'material', 'object_type', 'source_type', 'motion'), default='semantic')
    parser.add_argument('--lines-every', type=int, default=0, help='Motion-only: draw every Nth non-static displacement line.')
    parser.add_argument('--no-view', action='store_true', help='Validate/report without opening Open3D.')
    return parser.parse_args()

def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except Exception as exc:
        raise GtViewError(f'Cannot read JSON {path}: {exc}') from exc
    if not isinstance(value, dict):
        raise GtViewError(f'Expected JSON object: {path}')
    return value

def cloud_path(root: Path, frame_id: int) -> Path:
    path = root / f'frame_{frame_id:03d}_gt_scene.ply'
    if not path.is_file():
        raise GtViewError(f'Missing GT PLY for frame {frame_id}: {path}')
    return path

def read_ply(path: Path) -> dict[str, np.ndarray]:
    with path.open('r', encoding='ascii') as handle:
        if handle.readline().strip() != 'ply' or handle.readline().strip() != 'format ascii 1.0':
            raise GtViewError(f'Only ASCII PLY is supported: {path}')
        count = None
        properties: list[str] = []
        in_vertex = False
        while True:
            line = handle.readline()
            if not line:
                raise GtViewError(f'Incomplete PLY header: {path}')
            words = line.split()
            if words == ['end_header']:
                break
            if words[:2] == ['element', 'vertex']:
                count = int(words[2])
                in_vertex = True
            elif words[:1] == ['element']:
                in_vertex = False
            elif in_vertex and words[:1] == ['property']:
                properties.append(words[-1])
        if count is None or properties != list(FIELDS):
            raise GtViewError(f'Unexpected GT PLY schema in {path}: {properties}')
        rows = np.loadtxt(handle, dtype=np.float64, max_rows=count)
    if rows.ndim == 1:
        rows = rows.reshape(1, -1)
    if rows.shape != (count, len(FIELDS)):
        raise GtViewError(f'PLY row count/schema mismatch in {path}: {rows.shape}, expected {(count, len(FIELDS))}')
    return {name: rows[:, index] if index < 3 else rows[:, index].astype(np.int64) for (index, name) in enumerate(FIELDS)}

def registry_sets(registry: dict[str, Any]) -> tuple[dict[str, set[int]], dict[int, dict[str, int]]]:
    allowed = {field: {int(key) for key in registry[section]} for (field, section) in REGISTRY_SECTIONS.items()}
    instances: dict[int, dict[str, Any]] = {}
    for item in registry.get('instances', []):
        iid = int(item['instance_id'])
        instances[iid] = {'class_labels': {int(value) for value in item.get('class_labels', [item['class_label']])}, 'object_type_id': int(item['object_type_id']), 'source_type_id': int(item['source_type_id'])}
    if not instances:
        raise GtViewError('label_registry.json contains no instances')
    return (allowed, instances)

def validate_cloud(cloud: dict[str, np.ndarray], registry: dict[str, Any], label: str) -> None:
    points = np.column_stack([cloud['x'], cloud['y'], cloud['z']])
    if not np.isfinite(points).all():
        raise GtViewError(f'{label}: NaN/Inf coordinate')
    (allowed, instances) = registry_sets(registry)
    for field in LABEL_FIELDS:
        values = cloud[field]
        if np.any(values <= 0):
            raise GtViewError(f'{label}: zero/non-positive {field}')
        if field == 'instance_id':
            if not set(map(int, values)).issubset(instances):
                raise GtViewError(f'{label}: unknown instance_id')
        elif not set(map(int, values)).issubset(allowed[field]):
            raise GtViewError(f'{label}: unknown {field}')
    for (iid, expected) in instances.items():
        mask = cloud['instance_id'] == iid
        if np.any(mask):
            if not set(map(int, cloud['class_label'][mask])).issubset(expected['class_labels']):
                raise GtViewError(f'{label}: instance {iid} has unregistered class_label')
            for field in ('object_type_id', 'source_type_id'):
                value = expected[field]
                if not np.all(cloud[field][mask] == value):
                    raise GtViewError(f'{label}: instance {iid} has inconsistent {field}')

def deterministic_color(value: int) -> tuple[float, float, float]:
    hue = int(value) * 0.618033988749895 % 1.0
    return colorsys.hsv_to_rgb(hue, 0.65, 0.95)

def print_legend(registry: dict[str, Any], mode: str) -> None:
    if mode == 'motion':
        print('Color legend: static=(0.50,0.50,0.50), Panda=(0.90,0.20,0.20), UR5=(0.20,0.45,0.95), actor=(0.20,0.80,0.30)')
        return
    section = {'semantic': 'semantic_taxonomy', 'material': 'materials', 'object_type': 'object_types', 'source_type': 'source_types'}.get(mode)
    if mode == 'instance':
        entries = {str(item['instance_id']): item['name'] for item in registry['instances']}
    else:
        entries = registry[section]
    print(f'{mode} color legend:')
    displayed: dict[tuple[float, float, float], list[str]] = {}
    for (key, name) in sorted(entries.items(), key=lambda item: int(item[0])):
        color = deterministic_color(int(key))
        displayed.setdefault(tuple((round(value, 3) for value in color)), []).append(str(key))
        display_name = name.get('name', name) if isinstance(name, dict) else name
        print(f'  {key}: {display_name} -> ({color[0]:.3f},{color[1]:.3f},{color[2]:.3f})')
    collisions = [keys for keys in displayed.values() if len(keys) > 1]
    if collisions:
        print(f'WARNING: displayed-color collisions={collisions}; numeric label validation remains independent')

def histogram(values: np.ndarray) -> dict[int, int]:
    return dict(sorted(((int(key), int(count)) for (key, count) in Counter(map(int, values)).items())))

def print_report(cloud: dict[str, np.ndarray], registry: dict[str, Any], label: str) -> None:
    points = np.column_stack([cloud['x'], cloud['y'], cloud['z']])
    print(f'{label}: point_count={len(points)}')
    for field in LABEL_FIELDS:
        print(f'  {field}_histogram={histogram(cloud[field])}')
    names = {int(item['instance_id']): str(item['name']) for item in registry['instances']}
    for iid in sorted(set(map(int, cloud['instance_id']))):
        mask = cloud['instance_id'] == iid
        subset = points[mask]
        print(f"  instance={iid} name={names.get(iid, '?')} points={len(subset)} bbox_min={subset.min(axis=0).tolist()} bbox_max={subset.max(axis=0).tolist()}")

def compare_clouds(first: dict[str, np.ndarray], second: dict[str, np.ndarray], registry: dict[str, Any]) -> np.ndarray:
    if len(first['x']) != len(second['x']):
        raise GtViewError('Compared frames have unequal point counts')
    for field in LABEL_FIELDS:
        if not np.array_equal(first[field], second[field]):
            raise GtViewError(f'Compared frames do not have identical point ordering/labels: {field}')
    p0 = np.column_stack([first['x'], first['y'], first['z']])
    p1 = np.column_stack([second['x'], second['y'], second['z']])
    displacement = np.linalg.norm(p1 - p0, axis=1)
    static = first['source_type_id'] == 1
    if static.any() and float(displacement[static].max()) > 1e-08:
        raise GtViewError(f'Static displacement exceeds 1e-8: {float(displacement[static].max())}')
    print('displacement by instance:')
    for iid in sorted(set(map(int, first['instance_id']))):
        values = displacement[first['instance_id'] == iid]
        print(f'  instance={iid} mean={float(values.mean()):.9f} max={float(values.max()):.9f}')
    print('displacement by source type:')
    for sid in sorted(set(map(int, first['source_type_id']))):
        values = displacement[first['source_type_id'] == sid]
        print(f'  source_type={sid} mean={float(values.mean()):.9f} max={float(values.max()):.9f}')
    return displacement

def colors_for(cloud: dict[str, np.ndarray], mode: str) -> np.ndarray:
    if mode == 'motion':
        colors = np.full((len(cloud['x']), 3), 0.5, dtype=np.float64)
        colors[cloud['object_type_id'] == 2] = (0.9, 0.2, 0.2)
        colors[cloud['object_type_id'] == 3] = (0.2, 0.45, 0.95)
        colors[cloud['object_type_id'] == 4] = (0.2, 0.8, 0.3)
        return colors
    field = {'semantic': 'class_label', 'instance': 'instance_id', 'material': 'material_id', 'object_type': 'object_type_id', 'source_type': 'source_type_id'}[mode]
    return np.asarray([deterministic_color(int(value)) for value in cloud[field]], dtype=np.float64)

def visualize(cloud: dict[str, np.ndarray], mode: str, second: dict[str, np.ndarray] | None, lines_every: int) -> None:
    try:
        import open3d as o3d
    except ImportError as exc:
        raise GtViewError('Open3D is required for interactive visualization; install open3d or use --no-view') from exc
    points = np.column_stack([cloud['x'], cloud['y'], cloud['z']])
    point_cloud = o3d.geometry.PointCloud()
    point_cloud.points = o3d.utility.Vector3dVector(points)
    point_cloud.colors = o3d.utility.Vector3dVector(colors_for(cloud, mode))
    geometries: list[Any] = [point_cloud]
    if mode == 'motion' and second is not None and (lines_every > 0):
        target = np.column_stack([second['x'], second['y'], second['z']])
        indices = np.flatnonzero(cloud['source_type_id'] != 1)[::lines_every]
        line_points = np.vstack([points[indices], target[indices]])
        lines = [[index, index + len(indices)] for index in range(len(indices))]
        line_set = o3d.geometry.LineSet(o3d.utility.Vector3dVector(line_points), o3d.utility.Vector2iVector(lines))
        line_set.colors = o3d.utility.Vector3dVector(np.tile((1.0, 1.0, 1.0), (len(lines), 1)))
        geometries.append(line_set)
    o3d.visualization.draw_geometries(geometries, window_name=f'GT scene: {mode}')

def main() -> None:
    args = parse_args()
    if args.lines_every < 0:
        raise GtViewError('--lines-every must be non-negative')
    root = args.root.resolve()
    registry = load_json(root / 'label_registry.json')
    first = read_ply(cloud_path(root, args.frame))
    validate_cloud(first, registry, f'frame {args.frame}')
    second = None
    if args.compare_frame is not None:
        second = read_ply(cloud_path(root, args.compare_frame))
        validate_cloud(second, registry, f'frame {args.compare_frame}')
    if args.mode == 'motion' and second is None:
        raise GtViewError('--mode motion requires --compare-frame')
    print_legend(registry, args.mode)
    print_report(first, registry, f'frame {args.frame}')
    if second is not None:
        print_report(second, registry, f'frame {args.compare_frame}')
        compare_clouds(first, second, registry)
    if not args.no_view:
        visualize(first, args.mode, second, args.lines_every)
if __name__ == '__main__':
    try:
        main()
    except GtViewError as exc:
        print(f'ERROR: {exc}')
        raise SystemExit(1)
