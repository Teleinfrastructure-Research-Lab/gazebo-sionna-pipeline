#!/usr/bin/env python3
"""Coordinate-aware PyTorch smoke checks for canonical sparse voxel views.

This is intentionally *not* a substitute for a sparse-convolution training
backend: the available PyTorch environment has no MinkowskiEngine, spconv, or
TorchSparse.  It is a bounded coordinate-aware fallback that validates data
flow, spatial dependence, batching, and optimization before long training.
"""
from __future__ import annotations
import argparse, importlib.util, json, random, resource, sys, time
from collections import Counter
from pathlib import Path
import numpy as np
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    'voxds', HERE.parent / 'datasets' / 'canonical_segmentation_voxel_dataset.py'
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
VIEWS = mod.VIEWS
TARGETS = mod.TARGETS
Dataset = mod.CanonicalVoxelDataset
SEED = 20260716
HIDDEN = 32
LINK_HIDDEN = 16


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--mode', choices=('geometry', 'step'), required=True)
    parser.add_argument('--target', choices=TARGETS, default=TARGETS[0])
    return parser


# Keep CLI discovery usable in lightweight environments. The actual training
# implementation still checks its optional PyTorch/sparse-convolution stack.
if any(argument in {'-h', '--help'} for argument in sys.argv[1:]):
    build_parser().print_help()
    raise SystemExit(0)

try:
    import torch
    from torch import nn
    import torch.nn.functional as F
except ImportError as exc:
    raise SystemExit('ERROR: use the collabpaper PyTorch environment; final sparse-convolution training additionally requires MinkowskiEngine, spconv, or TorchSparse') from exc

class SmokeError(RuntimeError):
    pass

def neighbour_index_arrays(coords: torch.Tensor):
    """Build coordinate graph indices outside autograd, once per sparse scene."""
    keys = {tuple((int(v) for v in xyz)): i for (i, xyz) in enumerate(coords.detach().cpu().tolist())}
    destination = []
    source = []
    offsets = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))
    for (i, xyz) in enumerate(coords.detach().cpu().tolist()):
        for d in offsets:
            j = keys.get((int(xyz[0]) + d[0], int(xyz[1]) + d[1], int(xyz[2]) + d[2]))
            if j is not None:
                destination.append(i)
                source.append(j)
    return (torch.as_tensor(source, dtype=torch.long, device=coords.device), torch.as_tensor(destination, dtype=torch.long, device=coords.device))

def seed_everything():
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(SEED)

def sparse_backend():
    import importlib.util
    found = [name for name in ('MinkowskiEngine', 'spconv', 'torchsparse') if importlib.util.find_spec(name)]
    return found[0] if found else None

class CoordinateAwareSmokeEncoder(nn.Module):
    """Shared coordinate-aware scene encoder; only ``input_projection`` varies.

 The six-neighbour aggregation consumes integer voxel coordinates as a sparse
 spatial graph.  Feature channels remain separate from coordinates throughout.
 """

    def __init__(self, feature_dim: int):
        super().__init__()
        self.feature_dim = feature_dim
        self.input_projection = nn.Linear(feature_dim, HIDDEN)
        self.coordinate_projection = nn.Linear(3, HIDDEN)
        self.local_projection = nn.Linear(HIDDEN, HIDDEN)
        self.neighbour_projection = nn.Linear(HIDDEN, HIDDEN, bias=False)
        self.scene_projection = nn.Sequential(nn.Linear(HIDDEN, HIDDEN), nn.ReLU(), nn.Linear(HIDDEN, HIDDEN))

    def forward_scene(self, coords: torch.Tensor, features: torch.Tensor) -> torch.Tensor:
        if coords.ndim != 2 or coords.shape[1] != 3 or features.shape[0] != coords.shape[0]:
            raise SmokeError('invalid sparse scene tensors')
        c = coords.to(dtype=features.dtype) / 128.0
        h = F.relu(self.input_projection(features) + self.coordinate_projection(c))
        (source, destination) = neighbour_index_arrays(coords)
        nsum = torch.zeros_like(h)
        degree = torch.zeros((len(coords), 1), dtype=h.dtype, device=h.device)
        if len(source):
            nsum.index_add_(0, destination, h.index_select(0, source))
            degree.index_add_(0, destination, torch.ones((len(destination), 1), dtype=h.dtype, device=h.device))
        self.last_graph_stats = {'edge_count': int(len(source)), 'mean_neighbour_degree': float(len(source) / max(len(coords), 1))}
        h = F.relu(self.local_projection(h) + self.neighbour_projection(nsum / degree.clamp_min(1.0)))
        return self.scene_projection(h.mean(0))

    def forward(self, coords: torch.Tensor, features: torch.Tensor) -> torch.Tensor:
        return self.forward_scene(coords, features)

class CommonSparseModel(nn.Module):
    """One spatial encoder per view; links fuse only after scene pooling."""

    def __init__(self, feature_dim: int):
        super().__init__()
        self.scene_encoder = CoordinateAwareSmokeEncoder(feature_dim)
        self.link_encoder = nn.Sequential(nn.Linear(16, LINK_HIDDEN), nn.ReLU())
        self.fusion = nn.Sequential(nn.Linear(HIDDEN + LINK_HIDDEN, HIDDEN), nn.ReLU())
        self.classifier = nn.Linear(HIDDEN, 1)
        self.scene_encode_calls = 0

    def forward(self, batch: dict):
        unique = Dataset.unique_scene_batch(batch)
        embeddings = []
        edge_count = 0
        for (coords, features) in zip(unique['coords'], unique['features']):
            self.scene_encode_calls += 1
            embeddings.append(self.scene_encoder(torch.as_tensor(coords, dtype=torch.int64), torch.as_tensor(features, dtype=torch.float32)))
            edge_count += self.scene_encoder.last_graph_stats['edge_count']
        scene = torch.stack(embeddings)
        rows = scene[torch.as_tensor(unique['row_to_scene'], dtype=torch.long)]
        link = self.link_encoder(torch.as_tensor(batch['link_context'], dtype=torch.float32))
        logits = self.classifier(self.fusion(torch.cat((rows, link), dim=1))).squeeze(1)
        return (logits, {'scene_embeddings': scene, 'scene_rows': rows, 'unique': unique, 'edge_count': edge_count, 'mean_neighbour_degree': float(edge_count / max(len(unique['sparse_coords']), 1))})

def blocked_temporal_cv_interfaces():
    folds = ({'fold': 1, 'train_source_frames': [0, 555], 'purge_source_frames': [556, 565], 'validation_source_frames': [566, 1130]}, {'fold': 2, 'train_source_frames': [0, 1120], 'purge_source_frames': [1121, 1130], 'validation_source_frames': [1131, 1694]})
    for fold in folds:
        if fold['train_source_frames'][1] + 10 >= fold['validation_source_frames'][0]:
            raise SmokeError('train target reaches validation source')
    return folds

def six_rx_batch(ds, frame: int):
    indices = [i for (i, r) in enumerate(ds.rows) if r['split'] == 'train' and int(r['source_frame_id']) == frame]
    if len(indices) != 6:
        raise SmokeError('expected exactly six train receiver rows')
    return ds.collate([ds[i] for i in indices])

def optimization_batch(ds):
    per_frame = {}
    for r in ds.rows:
        if r['split'] == 'train':
            per_frame.setdefault(int(r['source_frame_id']), Counter())[int(r[ds.target])] += 1
    frames = sorted(per_frame)
    selected = None
    for (i, left) in enumerate(frames):
        for right in frames[i + 1:]:
            if set(per_frame[left]) | set(per_frame[right]) == {0, 1}:
                selected = (left, right)
                break
        if selected is not None:
            break
    if selected is None:
        raise SmokeError('no pair of distinct train source frames contains both target classes')
    frames = selected
    indices = [i for (i, r) in enumerate(ds.rows) if r['split'] == 'train' and int(r['source_frame_id']) in frames]
    batch = ds.collate([ds[i] for i in indices])
    if len(set(batch['source_frame_id'])) != 2 or set(batch['label']) != {0, 1}:
        raise SmokeError('optimization batch must have two frames and both label classes')
    return (batch, frames, {str(f): {str(k): int(v) for (k, v) in sorted(per_frame[f].items())} for f in frames}, {str(k): int(v) for (k, v) in sorted(Counter(map(int, batch['label'])).items())})

def geometry_tests(model: CommonSparseModel):
    model.eval()
    feat = np.ones((4, model.scene_encoder.feature_dim), np.float32)
    a = np.asarray(((0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)), np.int32)
    b = np.asarray(((8, 0, 0), (9, 0, 0), (8, 1, 0), (9, 1, 0)), np.int32)
    with torch.no_grad():
        ea = model.scene_encoder(torch.as_tensor(a), torch.as_tensor(feat))
        eb = model.scene_encoder(torch.as_tensor(b), torch.as_tensor(feat))
        ea_same = model.scene_encoder(torch.as_tensor(a), torch.as_tensor(feat.copy()))
        perm = np.asarray((2, 0, 3, 1))
        ea_permuted = model.scene_encoder(torch.as_tensor(a[perm]), torch.as_tensor(feat[perm]))
    different = not torch.allclose(ea, eb, atol=1e-06, rtol=1e-06)
    identical = torch.equal(ea, ea_same)
    permutation = torch.allclose(ea, ea_permuted, atol=1e-06, rtol=1e-06)
    if not (different and identical and permutation):
        raise SmokeError('coordinate geometry invariance test failed')
    return {'different_coordinates_different_embedding': different, 'identical_input_identical_embedding': identical, 'row_permutation_invariant': permutation}

def parameter_report(dim: int):
    m = CommonSparseModel(dim)
    total = sum((p.numel() for p in m.parameters()))
    input_params = sum((p.numel() for p in m.scene_encoder.input_projection.parameters()))
    return (total, input_params)

def main():
    a = build_parser().parse_args()
    seed_everything()
    backend = sparse_backend()
    out = {}
    base_total = None
    base_dim = None
    for view in VIEWS:
        ds = Dataset(a.root, view, a.target, cache_frames=8)
        model = CommonSparseModel(ds.dimension)
        six = six_rx_batch(ds, 0)
        model.scene_encode_calls = 0
        (logits, state) = model(six)
        if logits.shape != (6,) or state['scene_embeddings'].shape != (1, HIDDEN) or state['scene_rows'].shape != (6, HIDDEN) or (model.scene_encode_calls != 1):
            raise SmokeError('six receiver scene reuse failure')
        sparse = state['unique']['sparse_coords']
        mapping = state['unique']['row_to_scene']
        if sparse.ndim != 2 or sparse.shape[1] != 4 or len(mapping) != 6 or (len(sparse) and (int(sparse[:, 0].min()) < 0 or int(sparse[:, 0].max()) >= 1)):
            raise SmokeError('invalid explicit sparse batch indices')
        (total, input_params) = parameter_report(ds.dimension)
        item = {'feature_dimension': ds.dimension, 'parameters': total, 'input_projection_parameters': input_params, 'six_rx_output_shape': list(logits.shape), 'scene_embedding_shape': list(state['scene_embeddings'].shape), 'unique_scene_encodings': model.scene_encode_calls, 'sparse_coords_shape': list(sparse.shape), 'row_to_scene_shape': list(mapping.shape), 'edge_count': state['edge_count'], 'mean_neighbour_degree': state['mean_neighbour_degree']}
        if a.mode == 'geometry':
            item['geometry_tests'] = geometry_tests(model)
        else:
            (batch, frames, frame_counts, total_counts) = optimization_batch(ds)
            model.train()
            opt = torch.optim.Adam(model.parameters(), lr=0.001)
            before = [x.detach().clone() for x in model.parameters()]
            started = time.perf_counter()
            (logits, step_state) = model(batch)
            y = torch.as_tensor(batch['label'], dtype=torch.float32)
            pos = y.sum().item()
            neg = len(y) - pos
            loss = F.binary_cross_entropy_with_logits(logits, y, pos_weight=torch.tensor(neg / max(pos, 1.0)))
            opt.zero_grad()
            loss.backward()
            finite = all((p.grad is None or torch.isfinite(p.grad).all().item() for p in model.parameters()))
            required = ('scene_encoder.input_projection', 'scene_encoder.coordinate_projection', 'scene_encoder.neighbour_projection', 'link_encoder.0', 'fusion.0', 'classifier')
            gradient_modules = {name: any((p.grad is not None and torch.isfinite(p.grad).all().item() and bool(torch.count_nonzero(p.grad).item()) for p in dict(model.named_modules())[name].parameters())) for name in required}
            opt.step()
            elapsed = time.perf_counter() - started
            changed = any((not torch.equal(x, b) for (x, b) in zip(model.parameters(), before)))
            peak_rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
            if not (torch.isfinite(loss).item() and finite and changed and all(gradient_modules.values())):
                raise SmokeError('optimization smoke failed')
            item.update({'optimization_source_frames': list(frames), 'optimization_rows': len(batch['label']), 'per_frame_class_counts': frame_counts, 'total_class_counts': total_counts, 'loss': float(loss.item()), 'finite_gradients': finite, 'gradient_modules': gradient_modules, 'parameter_update': changed, 'optimization_elapsed_seconds': elapsed, 'optimization_peak_rss_bytes': peak_rss, 'optimization_edge_count': step_state['edge_count'], 'optimization_mean_neighbour_degree': step_state['mean_neighbour_degree']})
        out[view] = item
        base_total = total if base_total is None else base_total
        base_dim = ds.dimension if base_dim is None else base_dim
    expected = all((v['parameters'] - base_total == (v['feature_dimension'] - base_dim) * HIDDEN for v in out.values()))
    if not expected:
        raise SmokeError('parameter differences are not limited to feature input projections')
    print(json.dumps({'passed': True, 'backend': backend or 'pytorch_coordinate_aware_smoke_fallback', 'backend_note': None if backend else 'Production sparse-convolution training requires MinkowskiEngine, spconv, or TorchSparse; this fallback is coordinate-aware and smoke-only.', 'encoder': {'hidden': HIDDEN, 'spatial_processing': 'coordinate-indexed 6-neighbour aggregation plus coordinate projection', 'coordinates': 'explicit sparse integer indices, separate from features', 'link_fusion': 'after scene pooling'}, 'blocked_temporal_cv_interfaces': blocked_temporal_cv_interfaces(), 'target': a.target, 'views': out, 'parameter_differences_only_input_projection': expected}, sort_keys=True))
if __name__ == '__main__':
    try:
        main()
    except (SmokeError, mod.DatasetError) as e:
        raise SystemExit(f'ERROR: {e}')
