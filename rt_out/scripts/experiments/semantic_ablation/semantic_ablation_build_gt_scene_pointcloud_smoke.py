#!/usr/bin/env python3
"""Build canonical mesh-derived GT clouds for an existing smoke experiment.

This is deliberately an experiment-local smoke-test builder, not an RT or
camera pipeline.  It samples the preserved object-level static export, the
cached local rigid meshes with their per-frame transforms, and the baked actor
meshes.  It never reads merged-by-material static meshes.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import struct
from collections import Counter
from pathlib import Path
from typing import Any
import numpy as np
ROOT = Path(__file__).resolve().parents[4]
DEFAULT_EXP = ROOT / 'rt_out/experiments/semantic_ablation_actor_2446f_10hz/run_20260710_172015_smoke10'
EXP = DEFAULT_EXP
OUT = EXP / 'gt_scene_pointclouds'
SEED = 20260712
TARGET_POINTS = 100000
MIN_INSTANCE_POINTS = 256
FINE_TAXONOMY_PATH = EXP / 'config/fine_panoptic_taxonomy.json'
FINE_TO_COARSE_PATH = EXP / 'config/fine_to_coarse_mapping.json'
SOURCE_TYPE_IDS = {'static': 1, 'dynamic_rigid': 2, 'actor': 3}
OBJECT_TYPE_IDS = {'static_object': 1, 'panda': 2, 'ur5': 3, 'actor': 4}
EXPECTED_FINE_CLASS_NAMES = ('floor', 'ceiling', 'wall', 'door', 'window', 'coffee_table', 'desk', 'table', 'chair', 'shelving', 'sofa', 'trash_bin', 'computer_workstation', 'lamp_fixture', 'quadruped_robot', 'humanoid_robot', 'aerial_robot', 'industrial_robot', 'human', 'mechanical_part', 'misc_object')
EXPECTED_FINE_STUFF_NAMES = {'floor', 'ceiling', 'wall', 'window'}
STATIC_MODEL_FINE_CLASS = {'CoffeeTable': 'coffee_table', 'Desk': 'desk', 'Desk_0': 'desk', 'Desk_1': 'desk', 'Reflective table': 'table', 'Reflective table_1': 'table', 'Reflective table_1_1': 'table', 'Reflective table_1_2': 'table', 'OfficeChairBlack': 'chair', 'OfficeChairBlue': 'chair', 'OfficeChairGrey': 'chair', 'Picking_Shelves': 'shelving', 'Sofa': 'sofa', 'TrashBin': 'trash_bin', 'TrashBin_0': 'trash_bin', 'TrashBin_1': 'trash_bin', 'MonitorAndKeyboard': 'computer_workstation', 'lamp_fixture_01': 'lamp_fixture', 'lamp_fixture_02': 'lamp_fixture', 'lamp_fixture_03': 'lamp_fixture', 'lamp_fixture_04': 'lamp_fixture', 'cerberus_anymal_c_sensor_config_1': 'quadruped_robot', 'naoH25V40': 'humanoid_robot', 'x500': 'aerial_robot', 'person_standing': 'human', 'factory_door': 'door', 'arm_part': 'mechanical_part', 'cross_joint_part': 'mechanical_part', 'disk_part': 'mechanical_part', 'gasket_part': 'mechanical_part', 'gear_part': 'mechanical_part', 'piston_rod_part': 'mechanical_part', 't_brace_part': 'mechanical_part'}
UNRESOLVED_STATIC_MODELS = {'aws_robomaker_warehouse_ClutteringC_01': 'asset name/geometry does not establish a finer category'}
FACTORY_SHELL_EXPLICIT_MISC_VISUALS: dict[str, tuple[int, str]] = {}
PLY_PROPERTIES = ['property float x', 'property float y', 'property float z', 'property ushort class_label', 'property int instance_id', 'property ushort material_id', 'property ushort object_type_id', 'property ushort source_type_id']

class GtError(RuntimeError):
    pass

def configure_experiment(experiment_root: Path) -> None:
    global EXP, OUT, FINE_TAXONOMY_PATH, FINE_TO_COARSE_PATH
    EXP = experiment_root.expanduser().resolve()
    OUT = EXP / 'gt_scene_pointclouds'
    FINE_TAXONOMY_PATH = EXP / 'config/fine_panoptic_taxonomy.json'
    FINE_TO_COARSE_PATH = EXP / 'config/fine_to_coarse_mapping.json'

def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception as exc:
        raise GtError(f'Cannot read JSON {path}: {exc}') from exc

def project_rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda : handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()

def native_json(value: Any) -> Any:
    """Recursively convert NumPy metadata scalars before serializing JSON."""
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, dict):
        return {str(key): native_json(item) for (key, item) in value.items()}
    if isinstance(value, (list, tuple)):
        return [native_json(item) for item in value]
    return value

def json_text(payload: Any) -> str:
    return json.dumps(native_json(payload), indent=2) + '\n'

def stable_rng(key: str) -> np.random.Generator:
    value = int.from_bytes(hashlib.sha256(f'{SEED}:{key}'.encode()).digest()[:8], 'little')
    return np.random.default_rng(value)
_PLY_DTYPES = {'char': 'i1', 'int8': 'i1', 'uchar': 'u1', 'uint8': 'u1', 'short': 'i2', 'int16': 'i2', 'ushort': 'u2', 'uint16': 'u2', 'int': 'i4', 'int32': 'i4', 'uint': 'u4', 'uint32': 'u4', 'float': 'f4', 'float32': 'f4', 'double': 'f8', 'float64': 'f8'}
_PLY_STRUCT = {'char': 'b', 'int8': 'b', 'uchar': 'B', 'uint8': 'B', 'short': 'h', 'int16': 'h', 'ushort': 'H', 'uint16': 'H', 'int': 'i', 'int32': 'i', 'uint': 'I', 'uint32': 'I'}

def read_mesh(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Read the vertex xyz and polygon indices needed from Blender PLY output."""
    with path.open('rb') as h:
        header: list[str] = []
        while True:
            raw = h.readline()
            if not raw:
                raise GtError(f'Incomplete PLY header: {path}')
            line = raw.decode('ascii').strip()
            header.append(line)
            if line == 'end_header':
                break
        if not header or header[0] != 'ply':
            raise GtError(f'Not a PLY mesh: {path}')
        fmt = next((x for x in header if x.startswith('format ')), '')
        if fmt not in {'format ascii 1.0', 'format binary_little_endian 1.0'}:
            raise GtError(f'Unsupported PLY format in {path}: {fmt}')
        elements: list[tuple[str, int, list[list[str]]]] = []
        name = None
        count = 0
        props: list[list[str]] = []
        for line in header[2:-1]:
            bits = line.split()
            if bits[:1] == ['element']:
                if name is not None:
                    elements.append((name, count, props))
                (name, count, props) = (bits[1], int(bits[2]), [])
            elif bits[:1] == ['property'] and name is not None:
                props.append(bits[1:])
        if name is not None:
            elements.append((name, count, props))
        vertex = next((e for e in elements if e[0] == 'vertex'), None)
        face = next((e for e in elements if e[0] == 'face'), None)
        if vertex is None or face is None:
            raise GtError(f'PLY needs vertex and face elements: {path}')
        vprops = vertex[2]
        names = [p[-1] for p in vprops]
        if not {'x', 'y', 'z'}.issubset(names):
            raise GtError(f'PLY lacks xyz: {path}')
        if fmt == 'format ascii 1.0':
            vertices = np.array([[float(x) for x in h.readline().split()[:len(vprops)]] for _ in range(vertex[1])], dtype=np.float64)
            rows = [h.readline().split() for _ in range(face[1])]
            polygons = [list(map(int, row[1:])) for row in rows]
        else:
            fields = []
            for p in vprops:
                if p[0] == 'list' or p[0] not in _PLY_DTYPES:
                    raise GtError(f'Unsupported vertex property in {path}')
                fields.append((p[1], '<' + _PLY_DTYPES[p[0]]))
            arr = np.fromfile(h, dtype=np.dtype(fields), count=vertex[1])
            vertices = np.column_stack([arr[axis] for axis in ('x', 'y', 'z')]).astype(np.float64)
            fp = face[2]
            if len(fp) != 1 or fp[0][0] != 'list':
                raise GtError(f'Unsupported face list in {path}')
            if fp[0][1] not in _PLY_STRUCT or fp[0][2] not in _PLY_STRUCT:
                raise GtError(f'Unsupported face index type in {path}')
            count_fmt = '<' + _PLY_STRUCT[fp[0][1]]
            index_fmt = '<' + _PLY_STRUCT[fp[0][2]]
            (csize, isize) = (struct.calcsize(count_fmt), struct.calcsize(index_fmt))
            polygons = []
            for _ in range(face[1]):
                n = struct.unpack(count_fmt, h.read(csize))[0]
                polygons.append(list(struct.unpack('<' + str(n) + index_fmt[-1], h.read(n * isize))))
    xyz = vertices[:, [names.index('x'), names.index('y'), names.index('z')]] if fmt == 'format ascii 1.0' else vertices
    triangles = []
    for poly in polygons:
        if len(poly) < 3:
            continue
        for index in range(1, len(poly) - 1):
            triangles.append((poly[0], poly[index], poly[index + 1]))
    faces = np.asarray(triangles, dtype=np.int64)
    if not len(xyz) or not len(faces) or (not np.isfinite(xyz).all()):
        raise GtError(f'Empty/non-finite mesh: {path}')
    return (xyz, faces)

def triangle_areas(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    areas = np.linalg.norm(np.cross(vertices[faces[:, 1]] - vertices[faces[:, 0]], vertices[faces[:, 2]] - vertices[faces[:, 0]]), axis=1) * 0.5
    if not np.isfinite(areas).all() or float(areas.sum()) <= 0:
        raise GtError('Mesh has no positive triangle area')
    return areas

def selections(vertices: np.ndarray, faces: np.ndarray, count: int, key: str) -> tuple[np.ndarray, np.ndarray]:
    areas = triangle_areas(vertices, faces)
    rng = stable_rng(key)
    picked = rng.choice(len(faces), size=count, replace=True, p=areas / areas.sum())
    bary = rng.dirichlet((1.0, 1.0, 1.0), size=count)
    return (picked.astype(np.int64), bary.astype(np.float64))

def sample(vertices: np.ndarray, faces: np.ndarray, picked: np.ndarray, bary: np.ndarray) -> np.ndarray:
    return (vertices[faces[picked]] * bary[:, :, None]).sum(axis=1)

def canonical_triangles(faces: np.ndarray) -> np.ndarray:
    ordered = np.sort(faces.astype(np.int64, copy=False), axis=1)
    return ordered[np.lexsort((ordered[:, 2], ordered[:, 1], ordered[:, 0]))]

def canonical_edges(faces: np.ndarray) -> np.ndarray:
    edges = np.concatenate((faces[:, (0, 1)], faces[:, (1, 2)], faces[:, (2, 0)]))
    edges.sort(axis=1)
    edges = np.unique(edges, axis=0)
    return edges[np.lexsort((edges[:, 1], edges[:, 0]))]

def array_hash(values: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(values.astype('<i8', copy=False)).tobytes()).hexdigest()

def connectivity_signature(vertex_count: int, faces: np.ndarray) -> tuple[str, int]:
    neighbours = [set() for _ in range(vertex_count)]
    incident = [[] for _ in range(vertex_count)]
    for tri in canonical_triangles(faces):
        tri_tuple = tuple(map(int, tri))
        for (index, vertex) in enumerate(tri_tuple):
            neighbours[vertex].update(tri_tuple[:index] + tri_tuple[index + 1:])
            incident[vertex].append(tri_tuple)
    payload = [[vertex, sorted(neighbours[vertex]), incident[vertex]] for vertex in range(vertex_count)]
    parent = list(range(vertex_count))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for (a, b) in canonical_edges(faces):
        (ra, rb) = (find(int(a)), find(int(b)))
        if ra != rb:
            parent[rb] = ra
    return (hashlib.sha256(json.dumps(payload, separators=(',', ':')).encode()).hexdigest(), len({find(i) for i in range(vertex_count)}))

def topology_record(vertices: np.ndarray, faces: np.ndarray) -> dict[str, Any]:
    canonical = canonical_triangles(faces)
    edges = canonical_edges(faces)
    duplicate_count = int(len(canonical) - len(np.unique(canonical, axis=0)))
    areas = triangle_areas(vertices, faces)
    degenerate_count = int(np.count_nonzero(np.any(np.diff(np.sort(faces, axis=1), axis=1) == 0, axis=1) | (areas <= 1e-12)))
    (signature, components) = connectivity_signature(len(vertices), faces)
    return {'vertex_count': len(vertices), 'triangle_count': len(faces), 'raw_face_array_sha256': array_hash(faces), 'canonical_triangle_set_sha256': array_hash(canonical), 'canonical_edge_set_sha256': array_hash(edges), 'edge_count': len(edges), 'duplicate_triangles': duplicate_count, 'degenerate_triangles': degenerate_count, 'connected_components': components, 'euler_characteristic': int(len(vertices) - len(edges) + len(faces)), 'per_vertex_connectivity_sha256': signature}

def actor_mesh_path(frame_id: int) -> Path:
    manifest = read_json(EXP / f'frames/actor_meshes/frame_{frame_id:03d}/actor_frame_{frame_id:03d}_manifest.json')
    actors = manifest.get('exported_actors', [])
    if len(actors) != 1 or actors[0].get('actor_name') != 'actor_walking':
        raise GtError(f'Actor records not exactly one for frame {frame_id}')
    return Path(actors[0]['exported_mesh_path'])

def classify_actor_meshes(frames: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], np.ndarray, np.ndarray]:
    records = []
    reference = None
    reference_vertices = None
    canonical_faces = None
    for frame in frames:
        fid = int(frame['frame_id'])
        (vertices, faces) = read_mesh(actor_mesh_path(fid))
        current = topology_record(vertices, faces)
        if reference is None:
            classification = 'A exact face ordering'
            reference = current
            reference_vertices = vertices
            canonical_faces = canonical_triangles(faces)
        elif current['raw_face_array_sha256'] == reference['raw_face_array_sha256'] and current['vertex_count'] == reference['vertex_count']:
            classification = 'A exact face ordering'
        elif current['canonical_triangle_set_sha256'] == reference['canonical_triangle_set_sha256']:
            classification = 'B same indexed topology, different face order/winding'
        elif all((current[key] == reference[key] for key in ('vertex_count', 'triangle_count', 'edge_count', 'connected_components', 'euler_characteristic', 'duplicate_triangles', 'degenerate_triangles'))):
            classification = 'C different indexed topology'
        else:
            classification = 'D actual topology change'
        current['frame_id'] = fid
        current['classification'] = classification
        records.append(current)
        if fid != int(frames[0]['frame_id']):
            del vertices, faces
    if reference_vertices is None or canonical_faces is None:
        raise GtError('Actor topology check received no frames')
    return (records, reference_vertices, canonical_faces)

def allocate(weights: list[float], total: int, minimum: int) -> list[int]:
    if len(weights) * minimum > total:
        raise GtError('Target point budget cannot satisfy per-instance minimum')
    remain = total - len(weights) * minimum
    weights_np = np.maximum(np.asarray(weights, dtype=np.float64), 0)
    raw = remain * weights_np / weights_np.sum()
    extra = np.floor(raw).astype(int)
    for i in np.argsort(-(raw - extra))[:remain - int(extra.sum())]:
        extra[i] += 1
    return [int(value) for value in extra + minimum]

def allocate_members(weights: list[float], total: int) -> list[int]:
    raw = total * np.asarray(weights) / sum(weights)
    out = np.floor(raw).astype(int)
    out = np.maximum(out, 1)
    while int(out.sum()) > total:
        out[np.argmax(out)] -= 1
    for i in np.argsort(-(raw - np.floor(raw)))[:total - int(out.sum())]:
        out[i] += 1
    return [int(value) for value in out]

def material_ids(static_entries: list[dict[str, Any]]) -> dict[str, int]:
    labels = {str(e['material_class']) for e in static_entries}
    labels.update({'human_skin', 'robot_metal'})
    return {name: index + 1 for (index, name) in enumerate(sorted(labels))}

def load_fine_schema() -> tuple[dict[str, int], dict[str, Any], dict[str, Any]]:
    taxonomy = read_json(FINE_TAXONOMY_PATH)
    mapping = read_json(FINE_TO_COARSE_PATH)
    classes = taxonomy.get('classes')
    if not isinstance(classes, dict):
        raise GtError('Fine taxonomy must contain a classes object')
    parsed: list[tuple[int, str, str]] = []
    for (raw_id, value) in classes.items():
        if not isinstance(value, dict):
            raise GtError(f'Fine taxonomy class {raw_id} must be an object')
        try:
            class_id = int(raw_id)
        except ValueError as exc:
            raise GtError(f'Fine taxonomy class ID is invalid: {raw_id!r}') from exc
        (name, panoptic_type) = (value.get('name'), value.get('panoptic_type'))
        if not isinstance(name, str) or not isinstance(panoptic_type, str):
            raise GtError(f'Fine taxonomy class {raw_id} lacks name/panoptic_type')
        parsed.append((class_id, name, panoptic_type))
    parsed.sort()
    expected = [(index + 1, name, 'stuff' if name in EXPECTED_FINE_STUFF_NAMES else 'thing') for (index, name) in enumerate(EXPECTED_FINE_CLASS_NAMES)]
    if parsed != expected:
        raise GtError('Fine taxonomy class IDs, names, or panoptic_type values differ from the canonical schema')
    class_ids = {name: class_id for (class_id, name, _) in parsed}
    raw_mapping = mapping.get('fine_to_coarse')
    if not isinstance(raw_mapping, dict) or {int(key) for key in raw_mapping} != set(class_ids.values()):
        raise GtError('Fine-to-coarse mapping does not cover every fine class')
    return (class_ids, taxonomy, mapping)

def static_entry_semantic(entry: dict[str, Any], model_instance: dict[str, Any], class_ids: dict[str, int]) -> tuple[int, str, str, int, str]:
    """Reuse the perception world's explicit factory-shell visual taxonomy."""
    if str(entry['model_name']) != 'factory_shell':
        model_name = str(entry['model_name'])
        if model_name in STATIC_MODEL_FINE_CLASS:
            fine_name = STATIC_MODEL_FINE_CLASS[model_name]
        elif model_name in UNRESOLVED_STATIC_MODELS:
            fine_name = 'misc_object'
        else:
            raise GtError(f'Static model has no explicit fine semantic rule or unresolved allowlist entry: {model_name}')
        semantic_id = class_ids[fine_name]
        return (semantic_id, fine_name, 'deterministic_model_asset_rule', int(model_instance['instance_id']), str(model_instance['instance_name']))
    visual = str(entry['visual_name'])
    if visual in {'floor_visual', 'floor_surface_visual'}:
        (fine_name, logical_id, logical_name) = ('floor', 4000, 'factory_shell_floor')
    elif visual in {'ceiling_visual', 'ceiling_surface_visual'}:
        (fine_name, logical_id, logical_name) = ('ceiling', 4001, 'factory_shell_ceiling')
    elif visual.startswith('north_window_left_'):
        (fine_name, logical_id, logical_name) = ('window', 4100, 'factory_shell_north_window_left')
    elif visual.startswith('north_window_right_'):
        (fine_name, logical_id, logical_name) = ('window', 4101, 'factory_shell_north_window_right')
    elif visual.startswith('north_wall_'):
        (fine_name, logical_id, logical_name) = ('wall', 4002, 'factory_shell_north_wall')
    elif visual.startswith('south_wall_'):
        (fine_name, logical_id, logical_name) = ('wall', 4003, 'factory_shell_south_wall')
    elif visual.startswith('east_wall_'):
        (fine_name, logical_id, logical_name) = ('wall', 4004, 'factory_shell_east_wall')
    elif visual.startswith('west_wall_'):
        (fine_name, logical_id, logical_name) = ('wall', 4005, 'factory_shell_west_wall')
    elif visual in FACTORY_SHELL_EXPLICIT_MISC_VISUALS:
        (logical_id, logical_name) = FACTORY_SHELL_EXPLICIT_MISC_VISUALS[visual]
        fine_name = 'misc_object'
    else:
        raise GtError(f"factory_shell visual lacks an explicit logical semantic/instance mapping: {entry['id']}")
    return (class_ids[fine_name], fine_name, 'perception_classify_factory_shell_visual', logical_id, logical_name)

def build_sources() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    static_registry = read_json(ROOT / 'rt_out/experiments/factory_panda_ur5/legacy_run_20260522_133045/manifests/static_registry.json')['entries']
    pilot_registry = read_json(ROOT / 'rt_out/experiments/perception_rt_small_v0/run_20260522_133045/frames/instance_registry.json')['instances']
    semantic_map = read_json(ROOT / 'rt_out/experiments/perception_rt_small_v0/run_20260522_133045/config/semantic_label_map.json')
    (fine_class_ids, fine_taxonomy, fine_to_coarse) = load_fine_schema()
    if not {int(value) for value in fine_to_coarse['fine_to_coarse'].values()}.issubset({int(key) for key in semantic_map}):
        raise GtError('Fine-to-coarse mapping contains an unknown coarse class')
    static_ids = {str(item['model']): item for item in pilot_registry if item.get('source') == 'static'}
    by_model: dict[str, list[dict[str, Any]]] = {}
    for entry in static_registry:
        if entry.get('status') != 'ready':
            raise GtError(f"Static registry entry not ready: {entry.get('id')}")
        path = ROOT / 'rt_out/experiments/factory_panda_ur5/legacy_run_20260522_133045/static_scene/export/transformed_individual' / f"{entry['id']}.ply"
        if not path.is_file():
            raise GtError(f'Missing object-preserving static mesh: {path}')
        entry = dict(entry)
        entry['mesh_path'] = path
        by_model.setdefault(str(entry['model_name']), []).append(entry)
    statics = []
    for (model, entries) in sorted(by_model.items()):
        known = static_ids.get(model)
        if known is None:
            raise GtError(f'No established semantic instance for static model {model}')
        logical_groups: dict[int, list[dict[str, Any]]] = {}
        for entry in entries:
            (semantic_id, semantic_name, semantic_source, logical_id, logical_name) = static_entry_semantic(entry, known, fine_class_ids)
            entry['class_label'] = semantic_id
            entry['semantic_name'] = semantic_name
            entry['semantic_source'] = semantic_source
            entry['logical_instance_id'] = logical_id
            entry['logical_instance_name'] = logical_name
            logical_groups.setdefault(logical_id, []).append(entry)
        for (logical_id, logical_entries) in sorted(logical_groups.items()):
            statics.append({'key': f"static:{logical_entries[0]['logical_instance_name']}", 'name': logical_entries[0]['logical_instance_name'], 'model_name': model, 'entries': logical_entries, 'instance_id': logical_id, 'class_label': logical_entries[0]['class_label'], 'object_type_id': 1, 'source_type_id': 1})
    frames = read_json(EXP / 'frames/sampled_frames.json')['frames']
    instance_class_sets: dict[int, set[int]] = {}
    for obj in statics:
        instance_class_sets.setdefault(obj['instance_id'], set()).update((entry['class_label'] for entry in obj['entries']))
    if any((len(labels) != 1 for labels in instance_class_sets.values())):
        raise GtError('A static instance_id contains multiple fine semantic classes')
    return (statics, frames, static_registry, {'semantic_map': semantic_map, 'fine_taxonomy': fine_taxonomy, 'fine_to_coarse': fine_to_coarse, 'fine_class_ids': fine_class_ids, 'pilot_registry': pilot_registry})

def write_ply(path: Path, points: np.ndarray, attrs: np.ndarray) -> None:
    with path.open('w', encoding='ascii', newline='\n') as h:
        h.write('ply\nformat ascii 1.0\n')
        h.write(f'element vertex {len(points)}\n')
        h.write('\n'.join(PLY_PROPERTIES) + '\nend_header\n')
        for (xyz, fields) in zip(points, attrs, strict=True):
            h.write(f'{xyz[0]:.9f} {xyz[1]:.9f} {xyz[2]:.9f} {fields[0]} {fields[1]} {fields[2]} {fields[3]} {fields[4]}\n')

def write_text_atomic(path: Path, text: str) -> None:
    temporary = path.with_name(path.name + '.new')
    temporary.write_text(text, encoding='utf-8')
    os.replace(temporary, path)

def static_ply_digest(points: np.ndarray, attrs: np.ndarray) -> str:
    """Digest the exact static ASCII rows, so staged PLYs can be checked on resume."""
    digest = hashlib.sha256()
    for (xyz, fields) in zip(points, attrs, strict=True):
        digest.update(f'{xyz[0]:.9f} {xyz[1]:.9f} {xyz[2]:.9f} {fields[0]} {fields[1]} {fields[2]} {fields[3]} {fields[4]}\n'.encode('ascii'))
    return digest.hexdigest()

def validate_staged_ply(path: Path, frame_id: int, static_count: int, expected_static_ply_digest: str, valid_semantics: set[int], registry_ids: set[int], valid_material_ids: set[int], valid_object_ids: set[int], valid_source_ids: set[int], instance_classes: dict[int, set[int]]) -> dict[str, Any]:
    """Stream-validate one completed staged PLY without retaining its cloud."""
    try:
        with path.open('rb') as handle:
            header = []
            while True:
                raw = handle.readline()
                if not raw:
                    raise GtError(f'staged frame {frame_id}: incomplete PLY header')
                header.append(raw)
                if raw.strip() == b'end_header':
                    break
            if header[:2] != [b'ply\n', b'format ascii 1.0\n'] or f'element vertex {TARGET_POINTS}\n'.encode() not in header:
                raise GtError(f'staged frame {frame_id}: unexpected PLY header or point count')
            static_digest = hashlib.sha256()
            semantic = Counter()
            materials = Counter()
            instance_semantics: dict[int, set[int]] = {}
            minima = np.full(3, np.inf)
            maxima = np.full(3, -np.inf)
            row_count = 0
            for (index, raw) in enumerate(handle):
                fields = raw.split()
                if len(fields) != 8:
                    raise GtError(f'staged frame {frame_id}: malformed PLY row {index}')
                xyz = np.asarray([float(value) for value in fields[:3]], dtype=np.float64)
                ids = tuple(map(int, fields[3:]))
                if not np.isfinite(xyz).all() or min(ids) <= 0:
                    raise GtError(f'staged frame {frame_id}: non-finite coordinate or zero ID')
                (class_id, instance_id, material_id, object_id, source_id) = ids
                if class_id not in valid_semantics or instance_id not in registry_ids or material_id not in valid_material_ids or (object_id not in valid_object_ids) or (source_id not in valid_source_ids):
                    raise GtError(f'staged frame {frame_id}: unknown point ID')
                if class_id not in instance_classes[instance_id]:
                    raise GtError(f'staged frame {frame_id}: semantic class does not match label registry')
                if index < static_count:
                    if source_id != SOURCE_TYPE_IDS['static']:
                        raise GtError(f'staged frame {frame_id}: static block source mismatch')
                    static_digest.update(raw)
                elif source_id == SOURCE_TYPE_IDS['static']:
                    raise GtError(f'staged frame {frame_id}: static source appears outside initial static block')
                instance_semantics.setdefault(instance_id, set()).add(class_id)
                semantic[class_id] += 1
                materials[material_id] += 1
                minima = np.minimum(minima, xyz)
                maxima = np.maximum(maxima, xyz)
                row_count += 1
            if row_count != TARGET_POINTS:
                raise GtError(f'staged frame {frame_id}: wrong PLY row count')
    except OSError as exc:
        raise GtError(f'staged frame {frame_id}: cannot read {path}: {exc}') from exc
    if static_digest.hexdigest() != expected_static_ply_digest:
        raise GtError(f'staged frame {frame_id}: static block digest mismatch')
    if any((len(classes) != 1 for classes in instance_semantics.values())):
        raise GtError(f'staged frame {frame_id}: instance contains multiple semantic classes')
    return {'point_count': TARGET_POINTS, 'semantic_histogram': dict(sorted(semantic.items())), 'instance_count': len(instance_semantics), 'material_histogram': dict(sorted(materials.items())), 'bounding_box': {'min': minima.round(9).tolist(), 'max': maxima.round(9).tolist()}, 'ply_sha256': sha256(path)}

def validate_frame_arrays(frame_id: int, points: np.ndarray, attrs: np.ndarray, static_count: int, static_digest: str, valid_semantics: set[int], registry_ids: set[int], valid_material_ids: set[int], valid_object_ids: set[int], valid_source_ids: set[int], instance_classes: dict[int, set[int]]) -> list[str]:
    errors: list[str] = []
    if len(points) != TARGET_POINTS:
        errors.append(f'frame {frame_id}: point count')
    if not np.isfinite(points).all():
        errors.append(f'frame {frame_id}: non-finite coordinates')
    if np.any(attrs <= 0):
        errors.append(f'frame {frame_id}: zero/negative point ID')
    if not set(map(int, attrs[:, 0])).issubset(valid_semantics):
        errors.append(f'frame {frame_id}: unknown class ID')
    if not set(map(int, attrs[:, 1])).issubset(registry_ids):
        errors.append(f'frame {frame_id}: unknown instance ID')
    if not set(map(int, attrs[:, 2])).issubset(valid_material_ids):
        errors.append(f'frame {frame_id}: unknown material ID')
    if not set(map(int, attrs[:, 3])).issubset(valid_object_ids):
        errors.append(f'frame {frame_id}: unknown object type ID')
    if not set(map(int, attrs[:, 4])).issubset(valid_source_ids):
        errors.append(f'frame {frame_id}: unknown source type ID')
    if not np.all(attrs[:static_count, 4] == SOURCE_TYPE_IDS['static']):
        errors.append(f'frame {frame_id}: static block source mismatch')
    if np.any(attrs[static_count:, 4] == SOURCE_TYPE_IDS['static']):
        errors.append(f'frame {frame_id}: static source outside initial static block')
    for instance_id in set(map(int, attrs[:, 1])):
        classes = set(map(int, attrs[attrs[:, 1] == instance_id, 0]))
        if len(classes) != 1:
            errors.append(f'frame {frame_id}: instance contains multiple semantic classes')
        elif not classes.issubset(instance_classes.get(instance_id, set())):
            errors.append(f'frame {frame_id}: semantic class does not match label registry')
    digest = hashlib.sha256(points[:static_count].astype('<f8').tobytes() + attrs[:static_count].astype('<i8').tobytes()).hexdigest()
    if digest != static_digest:
        errors.append(f'frame {frame_id}: static block digest changed')
    return errors

def main(generate: bool, expected_frame_count: int) -> None:
    if generate and OUT.exists():
        raise GtError(f'Refusing to overwrite existing output: {OUT}')
    (statics, frames, static_entries, context) = build_sources()
    if len(frames) != expected_frame_count:
        raise GtError(f'Expected exactly {expected_frame_count} frames, got {len(frames)}')
    material_id = material_ids(static_entries)
    for obj in statics:
        for entry in obj['entries']:
            (v, f) = read_mesh(entry['mesh_path'])
            (entry['vertices'], entry['faces'], entry['area']) = (v, f, float(triangle_areas(v, f).sum()))
        obj['area'] = sum((e['area'] for e in obj['entries']))
    first_dynamic = read_json(EXP / 'frames/dynamic_meshes/frame_000/dynamic_frame_000_manifest.json')['exported_visuals']
    rigid = []
    for (token, iid, otype) in (('Panda', 2000, 2), ('ur5_rg2', 2001, 3)):
        entries = [dict(e) for e in first_dynamic if e['model_name'] == token]
        if not entries:
            raise GtError(f'Missing rigid model {token}')
        for entry in entries:
            (v, f) = read_mesh(Path(entry['cached_source_mesh_path']))
            (entry['vertices'], entry['faces'], entry['area']) = (v, f, float(triangle_areas(v, f).sum()))
        rigid.append({'key': f'rigid:{token}', 'name': token, 'entries': entries, 'instance_id': iid, 'class_label': context['fine_class_ids']['industrial_robot'], 'material': 'robot_metal', 'object_type_id': otype, 'source_type_id': 2, 'area': sum((e['area'] for e in entries))})
    (topology, ref_v, canonical_actor_faces) = classify_actor_meshes(frames)
    if not generate:
        reusable = all((record['classification'].startswith(('A', 'B')) for record in topology))
        print(json.dumps({'topology_classification': topology, 'connectivity_verdict': 'PASS: all frames are A or B; canonical indexed triples are reusable' if reusable else 'FAIL: C/D correspondence exists; canonical frame-0 vertex triples are unsafe'}, indent=2))
        return
    if any((record['classification'].startswith(('C', 'D')) for record in topology)):
        raise GtError('Actor correspondence is not reusable: ' + '; '.join((f"frame {r['frame_id']}={r['classification']}" for r in topology if r['classification'].startswith(('C', 'D')))))
    actor = {'key': 'actor:actor_walking', 'name': 'actor_walking', 'instance_id': 3000, 'class_label': context['fine_class_ids']['human'], 'material': 'human_skin', 'object_type_id': 4, 'source_type_id': 3, 'area': float(triangle_areas(ref_v, canonical_actor_faces).sum())}
    objects = statics + rigid + [actor]
    all_instance_classes: dict[int, set[int]] = {}
    for obj in objects:
        all_instance_classes.setdefault(obj['instance_id'], set()).add(obj['class_label'])
    if any((len(labels) != 1 for labels in all_instance_classes.values())):
        raise GtError('An instance_id contains multiple fine semantic classes')
    allocations = allocate([x['area'] for x in objects], TARGET_POINTS, MIN_INSTANCE_POINTS)
    for (obj, count) in zip(objects, allocations, strict=True):
        obj['allocation'] = count
    static_blocks = []
    for obj in statics:
        counts = allocate_members([e['area'] for e in obj['entries']], obj['allocation'])
        blocks = []
        attr_blocks = []
        for (entry, count) in zip(obj['entries'], counts, strict=True):
            (picked, bary) = selections(entry['vertices'], entry['faces'], count, f"{obj['key']}:{entry['id']}")
            block = sample(entry['vertices'], entry['faces'], picked, bary)
            blocks.append(block)
            attr_blocks.append(np.tile(np.array([entry['class_label'], obj['instance_id'], material_id[entry['material_class']], 1, 1], dtype=np.int64), (len(block), 1)))
        static_blocks.append((np.vstack(blocks), np.vstack(attr_blocks)))
    (static_points, static_attrs) = (np.vstack([x[0] for x in static_blocks]), np.vstack([x[1] for x in static_blocks]))
    rigid_plans = {}
    for obj in rigid:
        counts = allocate_members([e['area'] for e in obj['entries']], obj['allocation'])
        rigid_plans[obj['name']] = [(e, *selections(e['vertices'], e['faces'], count, f"{obj['key']}:{e['id']}")) for (e, count) in zip(obj['entries'], counts, strict=True)]
    (actor_pick, actor_bary) = selections(ref_v, canonical_actor_faces, actor['allocation'], actor['key'])
    actor_vertex_count = len(ref_v)
    del ref_v
    index_rows = []
    validation_frames = []
    static_digest = hashlib.sha256(static_points.astype('<f8').tobytes() + static_attrs.astype('<i8').tobytes()).hexdigest()
    staged_static_ply_digest = static_ply_digest(static_points, static_attrs)
    static_visual_labels = [{'entry_id': entry['id'], 'model_name': obj['model_name'], 'link_name': entry['link_name'], 'visual_name': entry['visual_name'], 'material_class': entry['material_class'], 'instance_id': obj['instance_id'], 'class_label': entry['class_label'], 'semantic_name': entry['semantic_name'], 'semantic_source': entry['semantic_source']} for obj in statics for entry in obj['entries']]
    registry = {'semantic_taxonomy': context['fine_taxonomy']['classes'], 'fine_to_coarse_mapping': context['fine_to_coarse']['fine_to_coarse'], 'coarse_semantic_taxonomy': context['semantic_map'], 'materials': {str(v): k for (k, v) in material_id.items()}, 'object_types': {str(v): k for (k, v) in OBJECT_TYPE_IDS.items()}, 'source_types': {str(v): k for (k, v) in SOURCE_TYPE_IDS.items()}, 'instances': [{**{k: x[k] for k in ('key', 'name', 'instance_id', 'class_label', 'object_type_id', 'source_type_id', 'allocation')}, 'class_labels': sorted({entry['class_label'] for entry in x['entries']}) if x['source_type_id'] == 1 else [x['class_label']]} for x in objects], 'static_visual_labels': static_visual_labels, 'convention_source': 'fine panoptic taxonomy plus separate experiment mapping; factory_shell per-visual semantics reuse perception classify_factory_shell_visual; material labels remain separate'}
    manifest = {'seed': SEED, 'target_points': TARGET_POINTS, 'minimum_points_per_instance': MIN_INSTANCE_POINTS, 'sampling': 'area-weighted triangle face selection + uniform Dirichlet barycentric coordinates', 'static_source': 'transformed_individual object-preserving meshes; merged_by_material rejected', 'rigid_source': 'cached_source_mesh_path + per-frame final_transform', 'actor_topology': {'stable': True, 'vertex_count': actor_vertex_count, 'face_count': len(canonical_actor_faces), 'classification': topology, 'sampling_faces': 'canonical sorted vertex triples'}, 'allocation': {x['key']: x['allocation'] for x in objects}}
    registry_ids = {x['instance_id'] for x in registry['instances']}
    errors = []
    instance_classes = {int(x['instance_id']): set(map(int, x.get('class_labels', [x['class_label']]))) for x in registry['instances']}
    valid_material_ids = set(material_id.values())
    valid_object_ids = set(OBJECT_TYPE_IDS.values())
    valid_source_ids = set(SOURCE_TYPE_IDS.values())
    if any((x['class_label'] == 0 or x['instance_id'] == 0 for x in registry['instances'])):
        errors.append('zero registry ID')
    if {2000, 2001, 3000} - registry_ids:
        errors.append('missing stable dynamic identities')
    if errors:
        raise GtError('Validation failed: ' + '; '.join(errors))
    registry_text = json_text(registry)
    manifest_text = json_text(manifest)
    temporary_out = OUT.with_name(OUT.name + '.tmp')
    progress_path = temporary_out / 'progress_manifest.json'
    try:
        dynamic_visual_frames = read_json(EXP / 'frames/dynamic_visual_frames.json')['frames']
        dynamic_by_id = {int(item['frame_id']): item for item in dynamic_visual_frames}
        frame_metadata = {}
        for frame in frames:
            fid = int(frame['frame_id'])
            dynamic_frame = dynamic_by_id.get(fid)
            if dynamic_frame is None or dynamic_frame.get('source_sample_index') != fid:
                raise GtError(f'frame {fid}: dynamic visual manifest source_sample_index is not {fid}')
            timestamp = dynamic_frame.get('timestamp', {}).get('seconds')
            if not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool):
                raise GtError(f'frame {fid}: dynamic visual manifest timestamp is invalid')
            if 'source_sample_index' in frame and frame['source_sample_index'] != fid:
                raise GtError(f'frame {fid}: sampled_frames source_sample_index is not {fid}')
            sampled_timestamp = frame.get('timestamp')
            if isinstance(sampled_timestamp, dict) and 'seconds' in sampled_timestamp and (float(sampled_timestamp['seconds']) != float(timestamp)):
                raise GtError(f'frame {fid}: sampled_frames timestamp disagrees with dynamic visual manifest')
            frame_metadata[fid] = {'frame_id': fid, 'source_sample_index': fid, 'timestamp': float(timestamp)}
        metadata_sha = hashlib.sha256(json.dumps(frame_metadata, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        initial_progress = {'schema_version': 1, 'expected_frame_count': expected_frame_count, 'target_points': TARGET_POINTS, 'static_ply_sha256': staged_static_ply_digest, 'frame_metadata_sha256': metadata_sha, 'completed_frames': {}}
        if not temporary_out.exists():
            temporary_out.mkdir(parents=True)
            write_text_atomic(progress_path, json_text(initial_progress))
        if not progress_path.is_file():
            raise GtError(f'Staging directory is missing progress manifest: {temporary_out}')
        progress = read_json(progress_path)
        for (key, value) in initial_progress.items():
            if key != 'completed_frames' and progress.get(key) != value:
                raise GtError(f'Staging progress manifest mismatch for {key}: {temporary_out}')
        completed = progress.get('completed_frames')
        if not isinstance(completed, dict):
            raise GtError(f'Invalid completed_frames in {progress_path}')
        expected_paths = {temporary_out / f'frame_{fid:03d}_gt_scene.ply' for fid in frame_metadata}
        actual_paths = set(temporary_out.glob('frame_*_gt_scene.ply'))
        expected_temporary = {path.with_name(path.name + '.tmp'): path for path in expected_paths}
        temporary_paths = set(temporary_out.glob('*.ply.tmp'))
        if temporary_paths - set(expected_temporary):
            raise GtError(f'Staging directory has unexpected temporary PLY filename: {sorted(temporary_paths - set(expected_temporary))[0]}')
        stale_after_final_validation: dict[Path, Path] = {}
        for temporary_path in temporary_paths:
            final_path = expected_temporary[temporary_path]
            if final_path.exists():
                stale_after_final_validation[final_path] = temporary_path
            else:
                temporary_path.unlink()
        if actual_paths - expected_paths:
            raise GtError('Staging directory has unexpected PLY files')
        valid_semantics = {int(key) for key in context['fine_taxonomy']['classes']}
        for path in sorted(actual_paths):
            fid = int(path.name.split('_')[1])
            report = validate_staged_ply(path, fid, len(static_points), staged_static_ply_digest, valid_semantics, registry_ids, valid_material_ids, valid_object_ids, valid_source_ids, instance_classes)
            existing = completed.get(str(fid))
            if existing is not None and (not isinstance(existing, dict) or existing.get('frame_id') != fid or existing.get('source_sample_index') != fid or (float(existing.get('timestamp', float('nan'))) != frame_metadata[fid]['timestamp']) or (existing.get('ply_sha256') != report['ply_sha256'])):
                raise GtError(f'Staging progress record disagrees with completed PLY for frame {fid}')
            completed[str(fid)] = {**frame_metadata[fid], **report}
            stale_temporary = stale_after_final_validation.get(path)
            if stale_temporary is not None:
                stale_temporary.unlink()
        if set(completed) - {str(fid) for fid in frame_metadata}:
            raise GtError('Staging progress manifest contains unexpected frame IDs')
        if set(completed) != {str(int(path.name.split('_')[1])) for path in actual_paths}:
            raise GtError('Staging progress manifest and PLY set disagree')
        write_text_atomic(progress_path, json_text({**initial_progress, 'completed_frames': completed}))
        resumed_frames = len(completed)
        newly_generated_frames = 0
        for frame in frames:
            fid = int(frame['frame_id'])
            if str(fid) in completed:
                report = completed[str(fid)]
                validation_frames.append({key: report[key] for key in ('frame_id', 'timestamp', 'point_count', 'semantic_histogram', 'instance_count', 'material_histogram', 'bounding_box', 'ply_sha256')})
                index_rows.append({'frame_id': fid, 'timestamp': report['timestamp'], 'ply_path': project_rel(OUT / f'frame_{fid:03d}_gt_scene.ply'), 'point_count': report['point_count'], 'ply_sha256': report['ply_sha256']})
                continue
            dv = read_json(EXP / f'frames/dynamic_meshes/frame_{fid:03d}/dynamic_frame_{fid:03d}_manifest.json')['exported_visuals']
            transforms = {entry['id']: np.asarray(entry['final_transform'], dtype=np.float64) for entry in dv}
            point_blocks = [static_points]
            attr_blocks = [static_attrs]
            for obj in rigid:
                blocks = []
                for (entry, picked, bary) in rigid_plans[obj['name']]:
                    local = sample(entry['vertices'], entry['faces'], picked, bary)
                    matrix = transforms.get(entry['id'])
                    if matrix is None or matrix.shape != (4, 4):
                        raise GtError(f"Missing transform {entry['id']} frame {fid}")
                    blocks.append(local @ matrix[:3, :3].T + matrix[:3, 3])
                merged = np.vstack(blocks)
                point_blocks.append(merged)
                attr_blocks.append(np.tile(np.array([obj['class_label'], obj['instance_id'], material_id['robot_metal'], obj['object_type_id'], 2], dtype=np.int64), (len(merged), 1)))
            (actor_vertices, _) = read_mesh(actor_mesh_path(fid))
            actor_points = sample(actor_vertices, canonical_actor_faces, actor_pick, actor_bary)
            del actor_vertices
            point_blocks.append(actor_points)
            attr_blocks.append(np.tile(np.array([actor['class_label'], 3000, material_id['human_skin'], 4, 3], dtype=np.int64), (len(actor_points), 1)))
            (points, attrs) = (np.vstack(point_blocks), np.vstack(attr_blocks))
            errors = validate_frame_arrays(fid, points, attrs, len(static_points), static_digest, {int(key) for key in context['fine_taxonomy']['classes']}, registry_ids, valid_material_ids, valid_object_ids, valid_source_ids, instance_classes)
            if errors:
                raise GtError('Validation failed: ' + '; '.join(errors))
            (semantic, materials) = (Counter(map(int, attrs[:, 0])), Counter(map(int, attrs[:, 2])))
            report = {'frame_id': fid, 'timestamp': frame_metadata[fid]['timestamp'], 'point_count': len(points), 'semantic_histogram': dict(sorted(semantic.items())), 'instance_count': len(set(map(int, attrs[:, 1]))), 'material_histogram': dict(sorted(materials.items())), 'bounding_box': {'min': points.min(axis=0).round(9).tolist(), 'max': points.max(axis=0).round(9).tolist()}}
            path = temporary_out / f'frame_{fid:03d}_gt_scene.ply'
            path_tmp = path.with_name(path.name + '.tmp')
            write_ply(path_tmp, points, attrs)
            os.replace(path_tmp, path)
            report['ply_sha256'] = sha256(path)
            validation_frames.append(report)
            completed[str(fid)] = {**frame_metadata[fid], **report}
            write_text_atomic(progress_path, json_text({**initial_progress, 'completed_frames': completed}))
            index_rows.append({'frame_id': fid, 'timestamp': frame_metadata[fid]['timestamp'], 'ply_path': project_rel(OUT / path.name), 'point_count': len(points), 'ply_sha256': report['ply_sha256']})
            newly_generated_frames += 1
            del points, attrs, actor_points, point_blocks, attr_blocks
        if len(index_rows) != expected_frame_count:
            raise GtError(f'not exactly {expected_frame_count} written PLY files')
        summary = {'passed': True, 'errors': [], 'frame_reports': validation_frames, 'checks': {'expected_ply_count': expected_frame_count, 'exact_ply_count': True, 'equal_point_counts': len({x['point_count'] for x in validation_frames}) == 1, 'static_sample_digest': static_digest, 'static_points_byte_identical_across_frames': True, 'actor_human_human_skin': True, 'no_material_merged_static_source': True, 'finite_coordinates_and_attributes': True, 'stable_instances': {'Panda': 2000, 'UR5': 2001, 'actor': 3000}}, 'resume': {'resumed_frames': resumed_frames, 'newly_generated_frames': newly_generated_frames}}
        summary_text = json_text(summary)
        (temporary_out / 'label_registry.json').write_text(registry_text, encoding='utf-8')
        (temporary_out / 'sampling_manifest.json').write_text(manifest_text, encoding='utf-8')
        with (temporary_out / 'pointcloud_index.csv').open('w', newline='', encoding='utf-8') as h:
            writer = csv.DictWriter(h, fieldnames=list(index_rows[0]))
            writer.writeheader()
            writer.writerows(index_rows)
        (temporary_out / 'validation_summary.json').write_text(summary_text, encoding='utf-8')
        os.replace(temporary_out, OUT)
    except Exception:
        raise
    print(json.dumps({'result': 'PASS', 'output': project_rel(OUT), 'actor_topology': manifest['actor_topology'], 'point_count': TARGET_POINTS, 'instances': len(objects), 'resumed_frames': resumed_frames, 'newly_generated_frames': newly_generated_frames}, indent=2))
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generate', action='store_true', help='Build PLY outputs after the topology-only gate passes.')
    parser.add_argument('--experiment-root', type=Path, default=DEFAULT_EXP)
    parser.add_argument('--expected-frame-count', type=int, default=10)
    args = parser.parse_args()
    try:
        if args.expected_frame_count <= 0:
            raise GtError('--expected-frame-count must be positive')
        configure_experiment(args.experiment_root)
        main(args.generate, args.expected_frame_count)
    except GtError as exc:
        print(f'FAIL: {exc}')
        raise SystemExit(1)
