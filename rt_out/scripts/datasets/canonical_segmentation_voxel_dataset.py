#!/usr/bin/env python3
"""Leakage-safe loader and validator for canonical sparse voxel ablations."""
from __future__ import annotations
import argparse, csv, json
from collections import OrderedDict, Counter
from pathlib import Path
from typing import Any
import numpy as np
RX = ('rx_panda_base', 'rx_ur5_base', 'rx_cerberus_base', 'rx_nao_chest', 'rx_human_chest', 'rx_x500_body')
VIEWS = {'G': ('occupancy',), 'GS': ('occupancy', 'semantic'), 'GI': ('occupancy', 'instance', 'instance_boundary'), 'GSI': ('occupancy', 'semantic', 'instance', 'instance_boundary'), 'GSM': ('occupancy', 'semantic', 'material'), 'GSIM': ('occupancy', 'semantic', 'material', 'instance', 'instance_boundary')}
TARGETS = ('y_adaptation_trigger_1db', 'y_path_change', 'beam_switch_1s', 'beam_reselection_05db_1s', 'beam_reselection_1db_1s', 'beam_reselection_3db_1s', 'future_optimal_beam_1s')
BINARY_TARGETS = frozenset(TARGETS[:-1])
MULTICLASS_TARGETS = frozenset(('future_optimal_beam_1s',))

class DatasetError(RuntimeError):
    pass

def read_json(p: Path) -> Any:
    return json.loads(p.read_text())

def feature_dimension(view: str, semantic: int, material: int) -> int:
    return sum(({'occupancy': 1, 'semantic': semantic, 'material': material, 'instance': 9, 'instance_boundary': 1}[x] for x in VIEWS[view]))

class CanonicalVoxelDataset:

    def __init__(self, root: Path, view: str, target: str, split: str | None=None, cache_frames: int=8, strict: bool=True):
        self.root = root.resolve()
        self.view = view
        self.target = target
        self.cache_frames = max(0, cache_frames)
        self.cache = OrderedDict()
        if view not in VIEWS or target not in TARGETS:
            raise DatasetError('unsupported representation or target')
        self.schema = read_json(self.root / 'representation_schema.json')
        self.semantic = read_json(self.root / 'semantic_channel_manifest.json')
        self.material = read_json(self.root / 'material_lut_manifest.json')
        self.sdim = len(self.semantic['fine_semantic_ids'])
        self.mdim = len(self.material['radio_materials'])
        self.dimension = feature_dimension(view, self.sdim, self.mdim)
        if tuple(self.schema['views'][view]) != ('coords',) + VIEWS[view]:
            raise DatasetError('representation schema does not match required sparse view')
        with (self.root / 'paired_index.csv').open(newline='') as h:
            self.rows = list(csv.DictReader(h))
        target_path = self.root.parents[2] / 'beam_results/canonical_4x4_dft16/supervised_targets_horizon10.csv'
        if not target_path.is_file():
            raise DatasetError(f'missing supervised targets: {target_path}')
        with target_path.open(newline='') as h:
            target_rows = list(csv.DictReader(h))
        key = lambda r: (r.get('source_frame_id'), r.get('rx_id'))
        if len(target_rows) != 14616 or len({key(r) for r in target_rows}) != 14616:
            raise DatasetError('supervised targets must contain unique canonical source-frame/RX rows')
        targets = {key(r): r for r in target_rows}
        if any((key(r) not in targets for r in self.rows)):
            raise DatasetError('paired index cannot be strictly joined to supervised targets')
        for r in self.rows:
            t = targets[key(r)]
            if t.get('split') != r.get('split') or t.get('target_frame_id') != str(int(r['source_frame_id']) + 10):
                raise DatasetError('supervised target split/temporal pairing mismatch')
            for name in TARGETS:
                if name not in t:
                    raise DatasetError(f'supervised targets lack {name}')
                r[name] = t[name]
        self.task_type = 'binary' if target in BINARY_TARGETS else 'multiclass'
        self.num_classes = 2 if self.task_type == 'binary' else 16
        self.link = np.load(self.root / 'link_context.npy', mmap_mode='r')
        if strict:
            self.validate_structure()
        if split is not None:
            if split not in ('train', 'excluded', 'test'):
                raise DatasetError('invalid chronological split')
            self.indices = [i for (i, r) in enumerate(self.rows) if r['split'] == split]
        else:
            self.indices = list(range(len(self.rows)))

    def validate_structure(self):
        if len(self.rows) != 14616 or self.link.shape != (14616, 16) or (not np.isfinite(self.link).all()):
            raise DatasetError('expected 14616 paired rows and finite 14616x16 link context')
        if [(r.get('source_frame_id'), r.get('rx_id')) for r in self.rows] != [(str(f), rx) for f in range(2436) for rx in RX]:
            raise DatasetError('paired index is not canonical source-frame/RX order')
        if Counter((r.get('split') for r in self.rows)) != {'train': 10170, 'excluded': 120, 'test': 4326}:
            raise DatasetError('chronological split counts invalid')
        for r in self.rows:
            if any((k.startswith(('target_', 'delta_', 'source_')) and k not in ('source_frame_id',) for k in r)):
                raise DatasetError('paired index contains forbidden feature leakage column')
            value = r.get(self.target)
            if self.task_type == 'binary' and value not in ('0', '1'):
                raise DatasetError('invalid binary target')
            if self.task_type == 'multiclass' and (value is None or not value.isdigit() or (not 0 <= int(value) < 16)):
                raise DatasetError('invalid 16-class target')
        scenes = list(csv.DictReader((self.root / 'scene_index.csv').open()))
        if len(scenes) != 2446 or [r.get('source_frame_id') for r in scenes] != [str(i) for i in range(2446)]:
            raise DatasetError('expected canonical 2446 scene records')

    def _frame(self, f: int):
        if f in self.cache:
            self.cache.move_to_end(f)
            return self.cache[f]
        p = self.root / 'frames' / f'frame_{f:03d}.npz'
        if not p.is_file():
            raise DatasetError(f'missing frame NPZ {p}')
        z = np.load(p)
        coords = z['coords']
        parts = []
        for key in VIEWS[self.view]:
            x = z[key]
            parts.append(x.reshape(len(coords), -1).astype(np.float32, copy=False))
        if coords.ndim != 2 or coords.shape[1] != 3 or any((len(x) != len(coords) for x in parts)):
            raise DatasetError(f'invalid sparse frame {f}')
        value = (coords.astype(np.int32, copy=False), np.concatenate(parts, axis=1))
        if value[1].shape[1] != self.dimension or not np.isfinite(value[1]).all():
            raise DatasetError(f'feature dimension/non-finite failure frame {f}')
        if self.cache_frames:
            self.cache[f] = value
            self.cache.move_to_end(f)
        while len(self.cache) > self.cache_frames:
            self.cache.popitem(last=False)
        return value

    def __len__(self):
        return len(self.indices)

    def __getitem__(self, index: int):
        row_index = self.indices[index]
        r = self.rows[row_index]
        f = int(r['source_frame_id'])
        (coords, features) = self._frame(f)
        return {'coords': coords, 'features': features, 'link_context': np.asarray(self.link[row_index], np.float32), 'label': np.int64(r[self.target]), 'task_type': self.task_type, 'source_frame_id': f, 'rx_id': r['rx_id'], 'split': r['split']}

    @staticmethod
    def collate(batch: list[dict[str, Any]]):
        return {'coords': [x['coords'] for x in batch], 'features': [x['features'] for x in batch], 'link_context': np.stack([x['link_context'] for x in batch]), 'label': np.asarray([x['label'] for x in batch]), 'source_frame_id': np.asarray([x['source_frame_id'] for x in batch]), 'rx_id': [x['rx_id'] for x in batch]}

    @staticmethod
    def unique_scene_batch(batch: dict[str, Any]):
        """Deduplicate source scenes and build explicit [batch,x,y,z] sparse indices.

  Coordinates remain spatial indices and are deliberately never concatenated to
  the representation feature channels.  ``row_to_scene`` permits one pooled
  scene embedding to serve its six receiver rows.
  """
        by_frame = {}
        scene_rows = []
        row_to_scene = []
        for (row, f) in enumerate(batch['source_frame_id']):
            f = int(f)
            if f not in by_frame:
                by_frame[f] = len(scene_rows)
                scene_rows.append(row)
            row_to_scene.append(by_frame[f])
        sparse = []
        for (scene_i, row) in enumerate(scene_rows):
            c = np.asarray(batch['coords'][row], np.int32)
            sparse.append(np.column_stack((np.full((len(c), 1), scene_i, np.int32), c)))
        sparse_coords = np.concatenate(sparse, axis=0) if sparse else np.empty((0, 4), np.int32)
        mapping = np.asarray(row_to_scene, np.int64)
        scene_rows = np.asarray(scene_rows, np.int64)
        if sparse_coords.ndim != 2 or sparse_coords.shape[1] != 4:
            raise DatasetError('sparse_coords must have shape [total_voxels, 4]')
        if len(mapping) != len(batch['source_frame_id']) or np.any(mapping < 0) or np.any(mapping >= len(scene_rows)):
            raise DatasetError('invalid row_to_scene mapping')
        if len(sparse_coords) and (np.any(sparse_coords[:, 0] < 0) or np.any(sparse_coords[:, 0] >= len(scene_rows))):
            raise DatasetError('sparse batch indices do not match unique scenes')
        for (row, scene_i) in enumerate(mapping):
            if int(batch['source_frame_id'][row]) != int(batch['source_frame_id'][scene_rows[scene_i]]):
                raise DatasetError('row_to_scene does not map link row to its source scene')
        return {'scene_rows': scene_rows, 'row_to_scene': mapping, 'sparse_coords': sparse_coords, 'coords': [batch['coords'][i] for i in scene_rows], 'features': [batch['features'][i] for i in scene_rows]}

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--view', choices=VIEWS, default='GSIM')
    p.add_argument('--target', choices=TARGETS, default='y_adaptation_trigger_1db')
    p.add_argument('--cache-frames', type=int, default=2)
    p.add_argument('--smoke', action='store_true')
    a = p.parse_args()
    ds = CanonicalVoxelDataset(a.root, a.view, a.target, cache_frames=a.cache_frames)
    counts = {split: Counter((int(r[a.target]) for r in ds.rows if r['split'] == split)) for split in ('train', 'excluded', 'test')}
    if a.smoke:
        picks = [next((i for (i, r) in enumerate(ds.rows) if r['split'] == s)) for s in ('train', 'excluded', 'test')]
        batch = ds.collate([ds[i] for i in picks])
        print(json.dumps({'passed': True, 'view': a.view, 'target': a.target, 'task_type': ds.task_type, 'num_classes': ds.num_classes, 'label_dtype': str(batch['label'].dtype), 'feature_dimension': ds.dimension, 'link_dimension': 16, 'smoke_splits': ['train', 'excluded', 'test'], 'variable_voxel_counts': [len(x) for x in batch['coords']], 'class_counts': {k: {str(c): n for (c, n) in v.items()} for (k, v) in counts.items()}}, sort_keys=True))
    else:
        print(json.dumps({'passed': True, 'view': a.view, 'target': a.target, 'task_type': ds.task_type, 'num_classes': ds.num_classes, 'class_counts': {k: {str(c): n for (c, n) in v.items()} for (k, v) in counts.items()}}, sort_keys=True))
if __name__ == '__main__':
    try:
        main()
    except DatasetError as e:
        raise SystemExit(f'ERROR: {e}')
