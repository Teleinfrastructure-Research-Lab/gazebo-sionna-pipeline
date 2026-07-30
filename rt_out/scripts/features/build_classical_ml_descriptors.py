#!/usr/bin/env python3
"""Deterministic fixed-length source-scene descriptors for classical ML."""
from __future__ import annotations
import argparse, csv, hashlib, json, os, sys, time
from collections import Counter
from pathlib import Path
from typing import Any
import numpy as np
RX = ('rx_panda_base', 'rx_ur5_base', 'rx_cerberus_base', 'rx_nao_chest', 'rx_human_chest', 'rx_x500_body')
N_SOURCE = 2436
N_ROWS = N_SOURCE * 6
VIEWS = ('G', 'GS', 'GI', 'GSI')
VERSION = 'classical_ml_descriptor_v2'
GLOBAL_LEVELS = ((1, 1, 1), (2, 2, 2), (4, 4, 2))
GLOBAL_CELLS = 41
TUBE_CELLS = 24
CELLS = 65

class Error(RuntimeError):
    pass

def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda : f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()

def sha_array(a: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()

def atomic_json(p: Path, x: Any) -> None:
    t = p.with_suffix(p.suffix + '.tmp')
    t.write_text(json.dumps(x, indent=2, sort_keys=True) + '\n')
    os.replace(t, p)

def atomic_csv(p: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    t = p.with_suffix(p.suffix + '.tmp')
    with t.open('w', newline='') as h:
        w = csv.DictWriter(h, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    os.replace(t, p)

def atomic_npy(p: Path, a: np.ndarray) -> None:
    t = p.with_suffix(p.suffix + '.tmp')
    with t.open('wb') as h:
        np.save(h, a)
    os.replace(t, p)

def read_csv(p: Path) -> list[dict[str, str]]:
    with p.open(newline='') as h:
        return list(csv.DictReader(h))

def canonical_keys():
    return [(str(f), rx) for f in range(N_SOURCE) for rx in RX]

class Builder:

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.exp = self.root / 'rt_out/experiments/semantic_ablation_actor_2446f_10hz/run_20260710_172015'
        self.voxel = self.exp / 'features/segmentation_ablation_voxels/voxel_0.04m'
        self.beam = self.exp / 'beam_results/canonical_4x4_dft16'
        self.out = self.exp / 'features/classical_ml_descriptor_v2'
        self.stage = self.out / 'staging'
        self.paths = {'representation_schema': self.voxel / 'representation_schema.json', 'semantic_manifest': self.voxel / 'semantic_channel_manifest.json', 'material_manifest': self.voxel / 'material_lut_manifest.json', 'paired_index': self.voxel / 'paired_index.csv', 'voxel_link_context': self.voxel / 'link_context.npy', 'supervised_targets': self.beam / 'supervised_targets_horizon10.csv', 'beam_labels': self.beam / 'beam_labels_horizon10.csv', 'beam_scores': self.beam / 'beam_scores.csv'}
        if any((not p.is_file() for p in self.paths.values())):
            raise Error('missing canonical descriptor input')
        self.schema = json.loads(self.paths['representation_schema'].read_text())
        self.sem = json.loads(self.paths['semantic_manifest'].read_text())
        self.lo = np.asarray(self.schema['effective_bounds_min'], np.float64)
        self.hi = np.asarray(self.schema['effective_bounds_max'], np.float64)
        self.grid = np.asarray(self.schema['grid_dimensions'], np.int64)
        self.vs = float(self.schema['voxel_size_m'])
        self.sdim = len(self.sem['fine_semantic_ids'])
        if self.sdim != 21 or tuple(self.grid) != (250, 250, 88) or (not np.allclose(self.hi - self.lo, self.grid * self.vs)):
            raise Error('non-canonical voxel schema')
        self.dims = {'G': 65, 'GS': 1430, 'GI': 715, 'GSI': 2080}
        self.global_dims = {'G': 41, 'GS': 41 * (1 + self.sdim), 'GI': 41 * 11, 'GSI': 41 * (1 + self.sdim + 10)}
        self.link_dims = {k: self.dims[k] - self.global_dims[k] for k in VIEWS}
        self.rows = read_csv(self.paths['paired_index'])
        self.targets = read_csv(self.paths['supervised_targets'])
        self.labels = read_csv(self.paths['beam_labels'])
        self.scores = read_csv(self.paths['beam_scores'])
        self.link = np.load(self.paths['voxel_link_context'], mmap_mode='r')
        if [(r.get('source_frame_id'), r.get('rx_id')) for r in self.rows] != canonical_keys() or [(r.get('source_frame_id'), r.get('rx_id')) for r in self.targets] != canonical_keys() or [(r.get('source_frame_id'), r.get('rx_id')) for r in self.labels] != canonical_keys() or ([(r.get('frame_id'), r.get('rx_id')) for r in self.scores] != [(str(f), rx) for f in range(2446) for rx in RX]):
            raise Error('non-canonical row ordering')
        if self.link.shape != (N_ROWS, 16) or not np.isfinite(self.link).all():
            raise Error('invalid canonical link context')
        self.link_by_frame = np.asarray(self.link, dtype=np.float64).reshape(N_SOURCE, 6, 16)
        self.static_link_rows = self.validate_static_link_geometry()
        if Counter((r['split'] for r in self.rows)) != {'train': 10170, 'excluded': 120, 'test': 4326}:
            raise Error('invalid split rows')
        for (r, t, b) in zip(self.rows, self.targets, self.labels, strict=True):
            if r['split'] != t['split'] or r['split'] != b['split'] or t['target_frame_id'] != str(int(r['source_frame_id']) + 10) or (b['target_frame_id'] != str(int(r['source_frame_id']) + 10)):
                raise Error('target join mismatch')
        self.current = np.asarray([int(r['current_optimal_beam']) for r in self.labels], np.int16)
        if np.any((self.current < 0) | (self.current >= 16)):
            raise Error('current beam out of range')
        for (i, b) in enumerate(self.labels):
            f = int(b['source_frame_id'])
            ri = i % 6
            s = self.scores[f * 6 + ri]
            if int(b['current_optimal_beam']) != int(s['optimal_beam']) or b['rx_id'] != s['rx_id']:
                raise Error('current beam does not match source beam score')
        self.onehot = np.eye(16, dtype=np.float32)[self.current]
        self.tube_capacities = self.compute_tube_capacities()
        if self.tube_capacities.shape != (6, TUBE_CELLS) or np.any(self.tube_capacities <= 0):
            raise Error('non-positive fixed-grid tube capacity')
        self.schema_payload = self.configuration_payload()
        self.configuration_sha256 = hashlib.sha256(json.dumps(self.schema_payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.script_sha256 = sha(Path(__file__))

    def validate_static_link_geometry(self) -> np.ndarray:
        """Require frame-invariant source-time link geometry before sharing capacities."""
        first = self.link_by_frame[0].copy()
        expected = np.eye(6, dtype=np.float64)
        if not np.array_equal(first[:, 10:16], expected):
            raise Error('frame-0 RX one-hot context is not canonical')
        if not np.array_equal(self.link_by_frame[:, :, 10:16], np.broadcast_to(expected, (N_SOURCE, 6, 6))):
            raise Error('RX one-hot context changes across source frames')
        if not np.array_equal(self.link_by_frame[:, :, :10], np.broadcast_to(first[:, :10], (N_SOURCE, 6, 10))):
            raise Error('link geometry changes across source frames; static tube capacities are invalid')
        for ri in range(6):
            (tx, rx, vec, length) = (first[ri, :3], first[ri, 3:6], first[ri, 6:9], first[ri, 9])
            if not np.allclose(rx - tx, vec, atol=1e-06, rtol=0) or not np.isclose(np.linalg.norm(vec), length, atol=1e-06, rtol=0) or length <= 0:
                raise Error('invalid static TX/RX geometry')
        return first

    def compute_tube_capacities(self) -> np.ndarray:
        """Count every fixed-grid centre in each RX-specific tube, in bounded chunks."""
        cap = np.zeros((6, TUBE_CELLS), np.int64)
        (ny, nz) = (int(self.grid[1]), int(self.grid[2]))
        chunk = 250000
        total = int(np.prod(self.grid))
        for start in range(0, total, chunk):
            flat = np.arange(start, min(start + chunk, total), dtype=np.int64)
            q = np.column_stack((flat // (ny * nz), flat // nz % ny, flat % nz))
            xyz = self.lo + (q + 0.5) * self.vs
            for ri in range(6):
                ctx = self.static_link_rows[ri]
                (tx, rx) = (ctx[:3], ctx[3:6])
                axis = rx - tx
                l2 = float(axis @ axis)
                if l2 <= 0 or not np.allclose(axis, ctx[6:9]) or (not np.isclose(np.sqrt(l2), ctx[9])):
                    raise Error('invalid RX link for tube capacity')
                delta = xyz - tx
                t = delta @ axis / l2
                rad = np.linalg.norm(delta - np.outer(t, axis), axis=1)
                long = np.minimum((t * 8).astype(np.int64), 7)
                band = np.select((rad < 0.25, rad < 0.5, rad <= 1.0), (0, 1, 2), default=-1)
                keep = (t >= 0) & (t <= 1) & (band >= 0)
                cap[ri] += np.bincount(long[keep] * 3 + band[keep], minlength=TUBE_CELLS)
        return cap

    def configuration_payload(self) -> dict[str, Any]:
        return {'version': VERSION, 'rx_order': list(RX), 'canonical_link_context_rows': self.static_link_rows.tolist(), 'canonical_link_context_rows_sha256': sha_array(self.static_link_rows), 'complete_current_beam_vector_sha256': sha_array(self.current), 'input_hashes': {k: sha(v) for (k, v) in self.paths.items() if k in ('representation_schema', 'semantic_manifest', 'voxel_link_context', 'paired_index', 'beam_labels', 'beam_scores')}, 'voxel_bounds_min': self.lo.tolist(), 'voxel_bounds_max': self.hi.tolist(), 'voxel_size_m': self.vs, 'grid_dimensions': self.grid.tolist(), 'global_levels': [list(x) for x in GLOBAL_LEVELS], 'global_cell_flattening_order': 'level order 1x1x1,2x2x2,4x4x2; x-major,y-middle,z-minor', 'tube_longitudinal_bins': 8, 'tube_radial_bands_m': [[0, 0.25], [0.25, 0.5], [0.5, 1.0]], 'tube_cell_index_order': 'longitudinal_bin_major_then_radial_band', 'tube_capacity_matrix': self.tube_capacities.tolist(), 'representation_channels': {'G': ['occupancy_proportion'], 'GS': ['occupancy_proportion', 'semantic_mean[21]'], 'GI': ['occupancy_proportion', 'instance_mean[9]', 'instance_boundary_fraction'], 'GSI': ['occupancy_proportion', 'semantic_mean[21]', 'instance_mean[9]', 'instance_boundary_fraction']}, 'fine_semantic_channel_ids': list(self.sem['fine_semantic_ids']), 'instance_feature_definitions': ['dx', 'dy', 'dz', 'sx', 'sy', 'sz', 'log_count', 'purity', 'instance_count'], 'instance_boundary_definition': 'stored canonical instance_boundary voxel indicator; aggregate mean over occupied voxels', 'formulas': {'global_occupancy': 'occupied_voxel_count_in_cell / fixed_world_voxel_capacity_in_cell', 'tube_occupancy': 'occupied_voxel_count_in_tube_cell / RX_specific_fixed_grid_tube_cell_capacity', 'semantic_instance_boundary': 'means among occupied voxels; empty occupied cells are zero'}}

    def feature_schema(self) -> dict[str, Any]:
        return {'version': VERSION, 'descriptor_configuration_sha256': self.configuration_sha256, 'canonical_schema_payload': self.schema_payload, 'source_frames': [0, 2435], 'rows': N_ROWS, 'receiver_order': list(RX), 'static_link_geometry_validated': True, 'static_link_geometry_note': 'The canonical 6x16 link-context rows are identical across all 2436 source frames; RX-specific tube capacities are therefore valid for every source frame.', 'spatial_cells': {'global_cells': GLOBAL_CELLS, 'link_cells': TUBE_CELLS, 'total': CELLS, 'tube_capacity_matrix': self.tube_capacities.tolist()}, 'views': {v: {'dimension': self.dims[v], 'global_dimension': self.global_dims[v], 'link_dimension': self.link_dims[v]} for v in VIEWS}, 'context': {'link_context': 'separate float32 [14616,16], source-time static TX/RX geometry only', 'current_beam_onehot': 'separate float32 [14616,16], validated source-time optimum only'}, 'forbidden_features': ['target_*', 'future_*', 'delta_*', 'RT metrics', 'beam powers', 'beam margins', 'raw semantic IDs', 'instance IDs', 'material IDs', 'object types', 'source types']}

    def ensure_metadata(self) -> None:
        self.out.mkdir(parents=True, exist_ok=True)
        self.stage.mkdir(exist_ok=True)
        schema = self.feature_schema()
        sp = self.out / 'descriptor_schema.json'
        if sp.exists():
            if json.loads(sp.read_text()) != schema:
                raise Error('existing descriptor schema mismatch')
        else:
            atomic_json(sp, schema)
        ri = self.out / 'row_index.csv'
        data = [{'row_index': i, 'source_frame_id': i // 6, 'rx_id': RX[i % 6], 'split': r['split']} for (i, r) in enumerate(self.rows)]
        if ri.exists():
            if read_csv(ri) != [{k: str(v) for (k, v) in x.items()} for x in data]:
                raise Error('existing row index mismatch')
        else:
            atomic_csv(ri, ['row_index', 'source_frame_id', 'rx_id', 'split'], data)

    def load_frame(self, f: int) -> dict[str, np.ndarray]:
        p = self.voxel / 'frames' / f'frame_{f:03d}.npz'
        if not p.is_file():
            raise Error(f'missing voxel frame {f}')
        with np.load(p, allow_pickle=False) as z:
            d = {k: z[k] for k in ('coords', 'occupancy', 'semantic', 'instance', 'instance_boundary')}
        n = len(d['coords'])
        if d['coords'].shape != (n, 3) or d['semantic'].shape != (n, self.sdim) or d['instance'].shape != (n, 9) or (d['occupancy'].shape != (n,)) or (d['instance_boundary'].shape != (n,)):
            raise Error(f'bad voxel frame {f}')
        return self.sort_frame(d)

    def sort_frame(self, d: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        """Canonicalize supplied as well as disk-loaded rows before every reduction."""
        o = np.lexsort((d['coords'][:, 2], d['coords'][:, 1], d['coords'][:, 0]))
        return {k: np.asarray(v[o]) for (k, v) in d.items()}

    def aggregate(self, d: dict[str, np.ndarray], cells: np.ndarray, denom: np.ndarray | float, ncells: int) -> dict[str, np.ndarray]:
        n = len(cells)
        cnt = np.bincount(cells, minlength=ncells).astype(np.float64)
        occ = cnt / denom

        def mean(v):
            out = np.zeros((ncells, v.shape[1]), np.float64)
            for j in range(v.shape[1]):
                out[:, j] = np.bincount(cells, weights=v[:, j], minlength=ncells)
            return np.divide(out, cnt[:, None], out=np.zeros_like(out), where=cnt[:, None] > 0)
        boundary = np.divide(np.bincount(cells, weights=d['instance_boundary'], minlength=ncells), cnt, out=np.zeros(ncells), where=cnt > 0)
        return {'occ': occ, 'semantic': mean(d['semantic'].astype(np.float64)), 'instance': mean(d['instance'].astype(np.float64)), 'boundary': boundary}

    def global_aggregation(self, d: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        q = d['coords'].astype(np.int64)
        pieces = {k: [] for k in ('occ', 'semantic', 'instance', 'boundary')}
        for bins in GLOBAL_LEVELS:
            bins = np.asarray(bins, np.int64)
            ix = np.minimum(q * bins // self.grid, bins - 1)
            cell = (ix[:, 0] * bins[1] + ix[:, 1]) * bins[2] + ix[:, 2]
            sizes = [np.bincount(np.minimum(np.arange(g) * b // g, b - 1), minlength=b) for (g, b) in zip(self.grid, bins, strict=True)]
            cap = np.einsum('i,j,k->ijk', *sizes).reshape(-1)
            a = self.aggregate(d, cell, cap, int(np.prod(bins)))
            for k in pieces:
                pieces[k].append(a[k])
        return {k: np.concatenate(v, axis=0) for (k, v) in pieces.items()}

    def tube_aggregation(self, d: dict[str, np.ndarray], row: int) -> dict[str, np.ndarray]:
        xyz = self.lo + (d['coords'].astype(np.float64) + 0.5) * self.vs
        ctx = np.asarray(self.link[row], np.float64)
        (tx, rx) = (ctx[:3], ctx[3:6])
        axis = rx - tx
        length = np.linalg.norm(axis)
        if not np.isfinite(length) or length <= 0 or (not np.allclose(axis, ctx[6:9])) or (not np.isclose(length, ctx[9])):
            raise Error('invalid source-time link context')
        delta = xyz - tx
        t = delta @ axis / (length * length)
        rad = np.linalg.norm(delta - np.outer(t, axis), axis=1)
        long = np.minimum((np.clip(t, 0, 1) * 8).astype(np.int64), 7)
        band = np.select((rad < 0.25, rad < 0.5, rad <= 1.0), (0, 1, 2), default=-1)
        keep = (t >= 0) & (t <= 1) & (band >= 0)
        empty = {k: np.zeros((TUBE_CELLS,) + shape, np.float64) for (k, shape) in (('occ', ()), ('semantic', (self.sdim,)), ('instance', (9,)), ('boundary', ()))}
        if not keep.any():
            return empty
        subset = {k: v[keep] for (k, v) in d.items()}
        cell = long[keep] * 3 + band[keep]
        capacity = self.tube_capacities[row % 6]
        if np.any(capacity <= 0):
            raise Error('used tube cell has non-positive capacity')
        return self.aggregate(subset, cell, capacity, TUBE_CELLS)

    def view(self, a: dict[str, np.ndarray], view: str) -> np.ndarray:
        x = [a['occ'][:, None]]
        if 'S' in view:
            x.append(a['semantic'])
        if 'I' in view:
            x.extend((a['instance'], a['boundary'][:, None]))
        return np.concatenate(x, axis=1).reshape(-1).astype(np.float32)

    def descriptor_frame(self, f: int, d: dict[str, np.ndarray] | None=None) -> dict[str, np.ndarray]:
        d = self.load_frame(f) if d is None else self.sort_frame(d)
        g = self.global_aggregation(d)
        result = {k: np.empty((6, self.dims[k]), np.float32) for k in VIEWS}
        for ri in range(6):
            a = self.tube_aggregation(d, f * 6 + ri)
            for view in VIEWS:
                result[view][ri] = np.r_[self.view(g, view), self.view(a, view)]
        return result

    def shard_path(self, f: int) -> Path:
        return self.stage / f'frame_{f:04d}.npz'

    def valid_shard(self, f: int) -> dict[str, np.ndarray] | None:
        p = self.shard_path(f)
        try:
            with np.load(p, allow_pickle=False) as z:
                d = {k: z[k] for k in (*VIEWS, 'link_context', 'current_beam_onehot')}
                scalar = lambda k: str(z[k].item())
                if scalar('descriptor_version') != VERSION or int(z['frame_id'].item()) != f or scalar('descriptor_configuration_sha256') != self.configuration_sha256 or (scalar('canonical_schema_payload_sha256') != self.configuration_sha256) or (scalar('source_voxel_frame_sha256') != sha(self.voxel / 'frames' / f'frame_{f:03d}.npz')) or (scalar('descriptor_script_sha256') != self.script_sha256) or (scalar('source_link_context_sha256') != sha_array(np.asarray(self.link[f * 6:f * 6 + 6], np.float32))) or (scalar('source_current_beam_sha256') != sha_array(self.current[f * 6:f * 6 + 6])):
                    return None
            if any((d[v].shape != (6, self.dims[v]) or d[v].dtype != np.float32 or (not np.isfinite(d[v]).all()) for v in VIEWS)):
                return None
            if d['link_context'].shape != (6, 16) or d['current_beam_onehot'].shape != (6, 16) or (not np.array_equal(d['link_context'], np.asarray(self.link[f * 6:f * 6 + 6], np.float32))) or (not np.array_equal(d['current_beam_onehot'], self.onehot[f * 6:f * 6 + 6])):
                return None
            return d
        except Exception:
            return None

    def write_shard(self, f: int) -> None:
        d = self.descriptor_frame(f)
        d['link_context'] = np.asarray(self.link[f * 6:f * 6 + 6], np.float32)
        d['current_beam_onehot'] = self.onehot[f * 6:f * 6 + 6]
        d.update({'descriptor_version': np.asarray(VERSION), 'frame_id': np.asarray(f, np.int32), 'descriptor_configuration_sha256': np.asarray(self.configuration_sha256), 'canonical_schema_payload_sha256': np.asarray(self.configuration_sha256), 'source_voxel_frame_sha256': np.asarray(sha(self.voxel / 'frames' / f'frame_{f:03d}.npz')), 'descriptor_script_sha256': np.asarray(self.script_sha256), 'source_link_context_sha256': np.asarray(sha_array(np.asarray(self.link[f * 6:f * 6 + 6], np.float32))), 'source_current_beam_sha256': np.asarray(sha_array(self.current[f * 6:f * 6 + 6]))})
        p = self.shard_path(f)
        t = p.with_suffix('.npz.tmp')
        np.savez_compressed(t, **d)
        os.replace(str(t) + '.npz', p)

    def validate_frame(self, f: int) -> dict[str, np.ndarray]:
        s = self.valid_shard(f)
        if s is None:
            raise Error(f'invalid/missing shard {f}')
        recompute = self.descriptor_frame(f)
        for view in VIEWS:
            if not np.array_equal(s[view], recompute[view]):
                raise Error(f'non-deterministic shard {f} {view}')
            if not np.all(s[view][:, :self.global_dims[view]] == s[view][0, :self.global_dims[view]][None, :]):
                raise Error(f'global descriptor differs across RX frame {f}')
        raw = self.load_frame(f)
        perm = {k: v[::-1] for (k, v) in raw.items()}
        permuted = self.descriptor_frame(f, perm)
        if any((not np.array_equal(recompute[v], permuted[v]) for v in VIEWS)):
            raise Error(f'row-permutation sensitivity frame {f}')
        if not np.all(s['current_beam_onehot'].sum(1) == 1) or not np.all(np.isin(s['current_beam_onehot'], (0, 1))):
            raise Error(f'invalid one-hot frame {f}')
        return s

    def publish(self) -> dict[str, Any]:
        if any((self.valid_shard(f) is None for f in range(N_SOURCE))):
            raise Error('cannot publish: incomplete staging')
        arrays = {k: np.concatenate([self.valid_shard(f)[k] for f in range(N_SOURCE)], axis=0) for k in (*VIEWS, 'link_context', 'current_beam_onehot')}
        audit_frames = (0, 1, 2, 1200, 2435)
        for f in audit_frames:
            self.validate_frame(f)
        if arrays['G'][0].shape != (65,) or np.array_equal(arrays['G'][0], arrays['G'][1200 * 6]):
            raise Error('G frame-change validation failed')
        link_diff = any((np.any(arrays['G'][f * 6:(f + 1) * 6, self.global_dims['G']:] != arrays['G'][f * 6, self.global_dims['G']:][None, :]) for f in audit_frames))
        if not link_diff:
            raise Error('no RX-specific link descriptor difference in audit frames')
        for (k, a) in arrays.items():
            atomic_npy(self.out / f'{k}.npy', a)
        return self.report(arrays, range(N_SOURCE), published=True, audit_frames=audit_frames, link_diff=link_diff)

    def report(self, arrays: dict[str, np.ndarray], frames: range, published: bool, audit_frames: tuple[int, ...]=(), link_diff: bool | None=None) -> dict[str, Any]:
        stats = {k: {'shape': list(a.shape), 'dtype': str(a.dtype), 'min': float(a.min()), 'max': float(a.max()), 'mean': float(a.mean()), 'zero_feature_fraction': float(np.mean(a == 0))} for (k, a) in arrays.items()}
        inputs = {k: sha(v) for (k, v) in self.paths.items()}
        inputs['descriptor_script'] = sha(Path(__file__))
        frame_ids = range(N_SOURCE) if published else frames
        inputs['voxel_frame_hashes'] = {f'frame_{f:04d}': sha(self.voxel / 'frames' / f'frame_{f:03d}.npz') for f in frame_ids}
        outputs = {k: sha(self.out / f'{k}.npy') for k in (*VIEWS, 'link_context', 'current_beam_onehot') if (self.out / f'{k}.npy').is_file()}
        outputs['row_index'] = sha(self.out / 'row_index.csv')
        outputs['schema'] = sha(self.out / 'descriptor_schema.json')
        return {'passed': True, 'published': published, 'frames': list(frames), 'rows': len(frames) * 6, 'descriptor_dimensions': self.dims, 'validation': {'canonical_frame_rx_order': True, 'finite_features': True, 'current_beam_onehot_validated': True, 'current_beam_matches_source_scores': True, 'no_target_future_or_rt_features': True, 'audited_frames': list(audit_frames), 'deterministic_recompute_equality': bool(audit_frames), 'voxel_row_permutation_invariant': bool(audit_frames), 'G_frame_0_differs_from_1200': published, 'global_components_identical_across_six_rx_rows': bool(audit_frames), 'link_centric_component_differs_across_rx': link_diff}, 'statistics': stats, 'file_sizes_bytes': {p.name: p.stat().st_size for p in self.out.iterdir() if p.is_file()}, 'input_hashes': inputs, 'output_hashes': outputs}

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, default=Path.cwd())
    p.add_argument('--start-frame', type=int, default=0)
    p.add_argument('--end-frame', type=int, default=N_SOURCE - 1)
    p.add_argument('--validate-only', action='store_true')
    a = p.parse_args()
    if not 0 <= a.start_frame <= a.end_frame < N_SOURCE:
        raise Error('invalid inclusive frame range')
    b = Builder(a.root)
    b.ensure_metadata()
    frames = range(a.start_frame, a.end_frame + 1)
    started = time.monotonic()
    if a.validate_only:
        shards = [b.validate_frame(f) for f in frames]
        arrays = {k: np.concatenate([s[k] for s in shards]) for k in (*VIEWS, 'link_context', 'current_beam_onehot')}
        report = b.report(arrays, frames, published=False, audit_frames=tuple(frames), link_diff=any((np.any(s['G'][:, b.global_dims['G']:] != s['G'][0, b.global_dims['G']:][None, :]) for s in shards)))
        print(json.dumps({'result': 'PASS', 'frames': [a.start_frame, a.end_frame], 'rows': len(frames) * 6, 'elapsed_seconds': time.monotonic() - started, 'validation': report['validation'], 'statistics': report['statistics']}, sort_keys=True))
        return
    for f in frames:
        if b.valid_shard(f) is None:
            if b.shard_path(f).exists():
                raise Error(f'existing shard {b.shard_path(f)} belongs to a previous descriptor configuration; remove it explicitly')
            b.write_shard(f)
        if b.valid_shard(f) is None:
            raise Error(f'failed to write valid shard {f}')
    if a.start_frame == 0 and a.end_frame == N_SOURCE - 1:
        report = b.publish()
        report['generation_seconds'] = time.monotonic() - started
        atomic_json(b.out / 'validation_summary.json', report)
        print(json.dumps({'result': 'PASS', 'published': True, 'rows': N_ROWS, 'elapsed_seconds': time.monotonic() - started}, sort_keys=True))
    else:
        print(json.dumps({'result': 'PASS', 'published': False, 'frames': [a.start_frame, a.end_frame], 'rows': len(frames) * 6, 'elapsed_seconds': time.monotonic() - started}, sort_keys=True))
if __name__ == '__main__':
    try:
        main()
    except Error as e:
        raise SystemExit(f'ERROR: {e}')
