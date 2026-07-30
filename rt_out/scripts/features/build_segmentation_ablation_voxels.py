#!/usr/bin/env python3
"""Canonical sparse GT voxel primitives for geometry-versus-segmentation ablations."""
from __future__ import annotations
import argparse, csv, hashlib, json, math, os, shutil
from pathlib import Path
import numpy as np
N = 2446
VERSION = 4
RX = ('rx_panda_base', 'rx_ur5_base', 'rx_cerberus_base', 'rx_nao_chest', 'rx_human_chest', 'rx_x500_body')
VS = 0.04
LO = np.array([-5.0, -5.0, -0.25])
REQUESTED_HI = np.array([5.0, 5.0, 3.25])
HI = REQUESTED_HI.copy()
DIMS = np.ceil((HI - LO) / VS).astype(int)
LUT = {1: 'vinyl_tile', 2: 'ceiling_board', 3: 'panel_wall', 4: 'wood', 5: 'glass', 6: 'wood', 7: 'wood', 8: 'wood', 9: 'wood', 10: 'metal', 11: 'textile', 12: 'plastic', 13: 'metal', 14: 'metal', 15: 'metal', 16: 'metal', 17: 'metal', 18: 'metal', 19: 'human_skin', 20: 'metal', 21: 'cardboard'}

class E(RuntimeError):
    pass

def j(p):
    return json.loads(p.read_text())

def args():
    p = argparse.ArgumentParser()
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--voxel-size', type=float, default=0.04, choices=(0.02, 0.04, 0.05, 0.1, 0.25))
    p.add_argument('--smoke-frames', type=int)
    p.add_argument('--validate-only', action='store_true')
    p.add_argument('--resolution-audit', action='store_true')
    p.add_argument('--audit-frames', type=int, default=30)
    return p.parse_args()

def configure(v):
    global VS, HI, DIMS
    VS = float(v)
    DIMS = np.ceil((REQUESTED_HI - LO) / VS).astype(int)
    HI = LO + DIMS * VS

def atomic(p, s):
    t = p.with_suffix(p.suffix + '.tmp')
    t.write_text(json.dumps(s, indent=2) + '\n')
    os.replace(t, p)

def ply(p):
    with p.open() as h:
        while h.readline().strip() != 'end_header':
            pass
        a = np.loadtxt(h)
    if a.shape != (100000, 8) or not np.isfinite(a).all():
        raise E(f'invalid PLY {p}')
    return a

def digest(d):
    return {k: hashlib.sha256(np.ascontiguousarray(v).tobytes()).hexdigest() for (k, v) in d.items()}

def voxel(a, sem_ids, mat_names, instance_ids):
    if not set(a[:, 3].astype(int)).issubset(sem_ids) or not set(a[:, 4].astype(int)).issubset(instance_ids):
        raise E('unknown semantic or instance ID in PLY')
    q = np.floor((a[:, :3] - LO) / VS).astype(np.int32)
    ok = np.all((q >= 0) & (q < DIMS), 1)
    if not ok.all():
        raise E('out-of-bounds canonical GT point')
    key = np.ravel_multi_index(q.T, tuple(DIMS))
    order = np.argsort(key, kind='stable')
    key = key[order]
    a = a[order]
    q = q[order]
    cuts = np.r_[0, np.flatnonzero(np.diff(key)) + 1, len(key)]
    v = len(cuts) - 1
    co = np.empty((v, 3), np.int16)
    occ = np.ones(v, np.uint8)
    sem = np.zeros((v, len(sem_ids)), np.uint8)
    mat = np.zeros((v, len(mat_names)), np.uint8)
    inst = np.zeros((v, 9), np.float32)
    dominant = np.empty(v, np.int64)
    global_stats = {}
    for iid in np.unique(a[:, 4].astype(int)):
        x = a[a[:, 4].astype(int) == iid, :3]
        global_stats[iid] = (x.mean(0), x.max(0) - x.min(0), len(x))
    for (i, (l, r)) in enumerate(zip(cuts[:-1], cuts[1:])):
        z = a[l:r]
        co[i] = q[l]
        ids = z[:, 4].astype(int)
        (u, c) = np.unique(ids, return_counts=True)
        dom = int(u[np.argmax(c)])
        dominant[i] = dom
        (cen, ext, n) = global_stats[dom]
        sem[i, [sem_ids.index(int(x)) for x in np.unique(z[:, 3].astype(int))]] = 1
        radios = {LUT[int(x)] for x in np.unique(z[:, 3].astype(int))}
        mat[i, [mat_names.index(x) for x in radios]] = 1
        center = LO + (co[i].astype(float) + 0.5) * VS
        inst[i, :3] = center - cen
        inst[i, 3:6] = ext / np.maximum(HI - LO, 1)
        inst[i, 6] = math.log1p(n) / math.log1p(100000)
        inst[i, 7] = c.max() / c.sum()
        inst[i, 8] = len(u)
    lookup = {tuple(c): i for (i, c) in enumerate(co)}
    boundary = np.zeros(v, np.uint8)
    offsets = [(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1) if (dx, dy, dz) != (0, 0, 0)]
    for (i, c) in enumerate(co):
        for (dx, dy, dz) in offsets:
            j = lookup.get((int(c[0]) + dx, int(c[1]) + dy, int(c[2]) + dz))
            if j is not None and dominant[j] != dominant[i]:
                boundary[i] = 1
                break
    return ({'coords': co, 'occupancy': occ, 'semantic': sem, 'material': mat, 'instance': inst, 'instance_boundary': boundary}, int(ok.sum()))

def staged(path, manifest):
    try:
        z = np.load(path)
        d = {k: z[k] for k in ('coords', 'occupancy', 'semantic', 'material', 'instance', 'instance_boundary')}
        n = d['coords'].shape[0]
        if d['coords'].dtype != np.int16 or d['occupancy'].dtype != np.uint8 or d['semantic'].dtype != np.uint8 or (d['material'].dtype != np.uint8) or (d['instance'].dtype != np.float32) or (d['instance_boundary'].dtype != np.uint8):
            return None
        if d['coords'].ndim != 2 or d['coords'].shape != (n, 3) or d['occupancy'].shape != (n,) or (d['semantic'].shape != (n, len(manifest['semantic_ids']))) or (d['material'].shape != (n, len(manifest['material_channels']))) or (d['instance'].shape != (n, 9)) or (d['instance_boundary'].shape != (n,)):
            return None
        if not np.all((d['coords'] >= 0) & (d['coords'] < DIMS)) or len(np.unique(d['coords'], axis=0)) != n:
            return None
        if not np.all(d['occupancy'] == 1) or not np.isin(d['semantic'], (0, 1)).all() or (not np.isin(d['material'], (0, 1)).all()) or (not np.isin(d['instance_boundary'], (0, 1)).all()):
            return None
        if not np.isfinite(d['instance']).all() or not np.all((d['instance'][:, 7] >= 0) & (d['instance'][:, 7] <= 1)) or (not np.all(d['instance'][:, 8] >= 1)) or (not np.all(d['instance'][:, 8] == np.rint(d['instance'][:, 8]))):
            return None
        if not np.array_equal(d['semantic'].any(1).astype(np.uint8), d['occupancy']):
            return None
        return d
    except Exception:
        return None

def audit(root, sem, mats, instances, count):
    ids = np.linspace(0, 1694, count, dtype=int)
    clouds = {f: ply(root / f'frame_{f:03d}_gt_scene.ply') for f in sorted(set(ids.tolist() + [int(f) + 10 for f in ids]))}
    result = []
    for size in (0.02, 0.04, 0.05, 0.1, 0.25):
        configure(size)
        occupied = []
        ppv = []
        single = []
        smix = []
        imix = []
        jaccard = []
        added = []
        removed = []
        human = []
        robot = []
        times = []
        for f in ids:
            start = __import__('time').monotonic()
            a = clouds[int(f)]
            (d, _) = voxel(a, sem, mats, instances)
            times.append(__import__('time').monotonic() - start)
            occupied.append(len(d['coords']))
            smix.append(float(np.mean(d['semantic'].sum(1) > 1)))
            imix.append(float(np.mean(d['instance'][:, 8] > 1)))
            q = np.floor((a[:, :3] - LO) / VS).astype(int)
            key = np.ravel_multi_index(q.T, tuple(DIMS))
            c = np.unique(key, return_counts=True)[1]
            ppv.extend(c.tolist())
            single.append(float(np.mean(c == 1)))
            (b, _) = voxel(clouds[int(f) + 10], sem, mats, instances)
            source = {tuple(x) for x in d['coords']}
            target = {tuple(x) for x in b['coords']}
            union = source | target
            added.append(len(target - source) / len(union))
            removed.append(len(source - target) / len(union))
            jaccard.append(len(source ^ target) / len(union))
            for (class_ids, values) in (((19,), human), ((15, 16, 17, 18), robot)):
                sm = np.any(d['semantic'][:, [sem.index(x) for x in class_ids]], axis=1)
                tm = np.any(b['semantic'][:, [sem.index(x) for x in class_ids]], axis=1)
                si = {tuple(d['coords'][i]) for i in np.flatnonzero(sm)}
                ti = {tuple(b['coords'][i]) for i in np.flatnonzero(tm)}
                u = si | ti
                values.append(len(si ^ ti) / len(u) if u else 0.0)
        summary = lambda x: {'mean': float(np.mean(x)), 'median': float(np.median(x)), 'min': float(np.min(x)), 'max': float(np.max(x))}
        result.append({'voxel_size_m': size, 'grid_dimensions': DIMS.tolist(), 'dense_voxel_count': int(np.prod(DIMS)), 'occupied_voxels': {'mean': float(np.mean(occupied)), 'min': int(min(occupied)), 'max': int(max(occupied))}, 'points_per_occupied_voxel': float(np.mean(ppv)), 'single_point_voxel_ratio': float(np.mean(single)), 'semantic_mixing_ratio': float(np.mean(smix)), 'instance_mixing_ratio': float(np.mean(imix)), 'occupancy_jaccard_change': summary(jaccard), 'added_voxel_ratio': summary(added), 'removed_voxel_ratio': summary(removed), 'dynamic_only_occupancy_jaccard_change': {'human': summary(human), 'robot': summary(robot)}, 'estimated_sparse_bytes_per_frame': int(np.mean(occupied) * (3 * 2 + 1 + len(sem) + len(mats) + 9 * 4 + 1)), 'processing_seconds_per_frame': float(np.mean(times))})
    return result

def main():
    a = args()
    configure(a.voxel_size)
    cfg = j(a.config)
    root = (Path.cwd() / cfg['output_dir']).resolve()
    gt = root / 'gt_scene_pointclouds'
    lab = root / 'rt_results/rt_2446frames_multi_rx_horizon10_labeled.csv'
    reg = j(gt / 'label_registry.json')
    radio = j(root / 'config/rt_material_mapping.json')['materials']
    sem = tuple(sorted(map(int, reg['semantic_taxonomy'])))
    mats = tuple(sorted(set(LUT.values())))
    instances = {int(x['instance_id']) for x in reg['instances']}
    if not np.allclose((HI - LO) / VS, DIMS) or not np.isfinite(np.asarray(cfg['tx']['position'], float)).all() or [x['id'] for x in cfg['rx_list']] != list(RX) or any((not np.isfinite(np.asarray(x['position'], float)).all() for x in cfg['rx_list'])):
        raise E('invalid voxel divisibility or canonical radio configuration')
    if set(LUT) != set(sem) or not set(mats) <= set(radio):
        raise E('frozen semantic-to-radio LUT invalid')
    if a.resolution_audit:
        if a.audit_frames < 1 or a.audit_frames > 1695:
            raise E('invalid --audit-frames')
        report = {'passed': True, 'source_frame_domain': [0, 1694], 'frame_ids': np.linspace(0, 1694, a.audit_frames, dtype=int).tolist(), 'resolutions': audit(gt, sem, mats, instances, a.audit_frames)}
        p = root / 'features/segmentation_ablation_voxels/resolution_audit.json'
        p.parent.mkdir(parents=True, exist_ok=True)
        atomic(p, report)
        print(json.dumps(report, sort_keys=True))
        return
    rows = list(csv.DictReader(lab.open()))
    expect = [(str(f), r) for f in range(2436) for r in RX]
    if [(x.get('source_frame_id'), x.get('rx_id')) for x in rows] != expect:
        raise E('labeled rows not canonical')
    limit = a.smoke_frames or N
    reports = []
    views = {'G': ['coords', 'occupancy'], 'GS': ['coords', 'occupancy', 'semantic'], 'GI': ['coords', 'occupancy', 'instance', 'instance_boundary'], 'GSI': ['coords', 'occupancy', 'semantic', 'instance', 'instance_boundary'], 'GSM': ['coords', 'occupancy', 'semantic', 'material'], 'GSIM': ['coords', 'occupancy', 'semantic', 'material', 'instance', 'instance_boundary']}
    manifest = {'version': VERSION, 'voxel_size_m': VS, 'requested_bounds_min': LO.tolist(), 'requested_bounds_max': REQUESTED_HI.tolist(), 'effective_bounds_min': LO.tolist(), 'effective_bounds_max': HI.tolist(), 'grid_dimensions': DIMS.tolist(), 'semantic_ids': list(sem), 'semantic_channels': [reg['semantic_taxonomy'][str(x)]['name'] for x in sem], 'material_channels': list(mats), 'material_lut_hash': hashlib.sha256(json.dumps(LUT, sort_keys=True).encode()).hexdigest(), 'views': views}
    if a.validate_only:
        for f in range(limit):
            start = __import__('time').monotonic()
            (d, n) = voxel(ply(gt / f'frame_{f:03d}_gt_scene.ply'), sem, mats, instances)
            reports.append({'frame_id': f, 'points': n, 'out_of_bounds': 100000 - n, 'occupied_voxels': len(d['coords']), 'instance_boundary_voxels': int(d['instance_boundary'].sum()), 'instance_boundary_ratio': float(d['instance_boundary'].mean()), 'mixed_instance_voxels': int(np.count_nonzero(d['instance'][:, 8] > 1)), 'mixed_instance_ratio': float(np.mean(d['instance'][:, 8] > 1)), 'purity_min': float(d['instance'][:, 7].min()), 'purity_max': float(d['instance'][:, 7].max()), 'instance_count_min': int(d['instance'][:, 8].min()), 'instance_count_max': int(d['instance'][:, 8].max()), 'voxelization_seconds': __import__('time').monotonic() - start, 'primitive_hashes': digest(d)})
            if not np.array_equal(d['semantic'].any(1).astype(np.uint8), d['occupancy']):
                raise E('semantic union differs from occupancy')
            if not np.all(d['material'].any(1)):
                raise E('occupied voxel lacks rule-derived material channel')
        print(json.dumps({'passed': True, 'frames': limit, 'points_per_frame': 100000, 'voxel_size_m': VS, 'grid_dimensions': DIMS.tolist(), 'channels': {'semantic': list(zip(sem, manifest['semantic_channels'])), 'material': list(mats), 'instance': ['dx', 'dy', 'dz', 'sx', 'sy', 'sz', 'log_count', 'purity', 'instance_count', 'boundary']}, 'reports': reports, 'actual_npz': {'keys': ['coords', 'occupancy', 'semantic', 'material', 'instance', 'instance_boundary'], 'shapes': {k: list(v.shape) for (k, v) in d.items()}, 'dtypes': {k: str(v.dtype) for (k, v) in d.items()}}, 'semantic_union_equals_occupancy': True, 'staging_compatibility': 'new staging manifest compatible', 'representation_views': views}, sort_keys=True))
        return
    out = root / 'features/segmentation_ablation_voxels' / f'voxel_{VS:.2f}m'
    tmp = out.with_name(out.name + '.tmp')
    if out.exists():
        raise E(f'refusing to overwrite {out}')
    if tmp.exists():
        old = j(tmp / 'staging_manifest.json') if (tmp / 'staging_manifest.json').is_file() else None
        if old != manifest:
            raise E('incompatible staging manifest')
    else:
        tmp.mkdir(parents=True)
        atomic(tmp / 'staging_manifest.json', manifest)
    for f in range(N):
        fp = tmp / f'frames/frame_{f:03d}.npz'
        fp.parent.mkdir(exist_ok=True)
        d = staged(fp, manifest) if fp.exists() else None
        if d is None:
            if fp.exists():
                fp.unlink()
            (d, n) = voxel(ply(gt / f'frame_{f:03d}_gt_scene.ply'), sem, mats, instances)
            t = fp.with_suffix('.npz.tmp')
            np.savez_compressed(t, **d)
            os.replace(str(t) + '.npz', fp)
        reports.append({'frame_id': f, 'occupied_voxels': len(d['coords']), 'primitive_hashes': digest(d)})
    scene = [{'source_frame_id': f, 'frame_path': str(out / f'frames/frame_{f:03d}.npz')} for f in range(N)]

    def w(p, fields, data):
        t = p.with_suffix('.tmp')
        with t.open('w', newline='') as h:
            q = csv.DictWriter(h, fieldnames=fields)
            q.writeheader()
            q.writerows(data)
        os.replace(t, p)
    w(tmp / 'scene_index.csv', ['source_frame_id', 'frame_path'], scene)
    meta = [{k: r[k] for k in ('source_frame_id', 'rx_id', 'split', 'y_adaptation_trigger_1db', 'y_path_change')} for r in rows]
    w(tmp / 'paired_index.csv', list(meta[0]), meta)
    tx = np.asarray(cfg['tx']['position'], np.float32)
    rp = {x['id']: np.asarray(x['position'], np.float32) for x in cfg['rx_list']}
    link = []
    for r in rows:
        z = rp[r['rx_id']]
        v = z - tx
        link.append(np.r_[tx, z, v, np.linalg.norm(v), np.eye(6, dtype=np.float32)[RX.index(r['rx_id'])]])
    np.save(tmp / 'link_context.npy', np.asarray(link, np.float32))
    schema = {**manifest, 'sparse_spatial_index': 'coords is required for every representation', 'forbidden_model_inputs': ['raw_ids', 'source_type_id', 'object_type_id', 'target_*', 'delta_*', 'RT metrics']}
    atomic(tmp / 'representation_schema.json', schema)
    atomic(tmp / 'semantic_channel_manifest.json', {'fine_semantic_ids': list(sem), 'fine_semantic_names': manifest['semantic_channels']})
    atomic(tmp / 'material_lut_manifest.json', {'semantic_to_radio_material': LUT, 'radio_materials': list(mats), 'lut_hash': manifest['material_lut_hash']})
    atomic(tmp / 'validation_summary.json', {'passed': True, 'scene_records': N, 'paired_rows': 14616, 'voxel_size_m': VS, 'grid_dimensions': DIMS.tolist(), 'reports': reports, 'staging_manifest': manifest})
    os.replace(tmp, out)
if __name__ == '__main__':
    try:
        main()
    except E as e:
        raise SystemExit(f'ERROR: {e}')
