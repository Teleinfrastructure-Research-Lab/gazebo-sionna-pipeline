#!/usr/bin/env python3
"""Resumable CTX-integrated best-beam-power regression; legacy outputs untouched."""
from __future__ import annotations
import argparse,hashlib,json,pickle,shutil,sys
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;sys.path[:0]=[str(HERE)]
from best_beam_power_regression import load_aligned,TARGET_NAME,regression_metrics,_write_csv,_write_json,RegressionInputError
MODES={'CTX':16,'G':81,'GS':1446,'GI':731,'GSI':2096}; METHODS=('per_rx_median','persistence','elastic_net','random_forest','rbf_svr')
GRIDS={'elastic_net':[{'alpha':a,'l1_ratio':r} for a in(.001,.01,.05,.1) for r in(.2,.5,.8)],'random_forest':[{'max_depth':d,'min_samples_leaf':l} for d in(8,20) for l in(1,4)],'rbf_svr':[{'C':c,'epsilon':e} for c in(1.,10.) for e in(.05,.2)]}
def now():return datetime.now(timezone.utc).isoformat()
def split(rows):
 f=np.asarray([int(r['source_frame_id']) for r in rows]);return {'fit':f<=1355,'validation':(f>=1356)&(f<=1694),'gap':(f>=1695)&(f<=1714),'test':f>=1715}
def make(name,p):
 from sklearn.pipeline import Pipeline
 from sklearn.preprocessing import StandardScaler
 from sklearn.feature_selection import VarianceThreshold
 from sklearn.linear_model import ElasticNet
 from sklearn.ensemble import RandomForestRegressor
 from sklearn.svm import SVR
 if name=='elastic_net':return Pipeline([('variance',VarianceThreshold()),('scale',StandardScaler()),('model',ElasticNet(**p,max_iter=100000,tol=1e-4,random_state=42))])
 if name=='random_forest':return Pipeline([('variance',VarianceThreshold()),('model',RandomForestRegressor(**p,n_estimators=200,random_state=42,n_jobs=-1))])
 return Pipeline([('variance',VarianceThreshold()),('scale',StandardScaler()),('model',SVR(**p,gamma='scale',cache_size=500))])
def baseline(name,rows,y,idx,fit):
 med={rx:float(np.median(y[[i for i in fit if rows[i]['rx_id']==rx]])) for rx in {r['rx_id'] for r in rows}}
 if name=='per_rx_median':return np.asarray([med[rows[i]['rx_id']] for i in idx]),med
 lookup={(int(r['source_frame_id']),r['rx_id']):float(v) for r,v in zip(rows,y)};return np.asarray([lookup.get((int(rows[i]['source_frame_id'])-1,rows[i]['rx_id']),float(y[fit].mean())) for i in idx]),{}
def config(reps):return {'schema':'ctx_regression_checkpoint_v1','target':TARGET_NAME,'representations':list(reps),'methods':list(METHODS),'mode_dimensions':MODES,'grids':GRIDS,'seed':42,'partitions':{'fit':[0,1355],'validation':[1356,1694],'gap':[1695,1714],'test':[1715,2435]},'ctx_dimension':16,'forbidden_inputs':['current_beam_onehot','current/future beam powers']}
def manifest_hash(cfg):return hashlib.sha256(json.dumps(cfg,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def checkpoint_path(out,pair):return out/'checkpoints'/f'{pair[0]}_{pair[1]}.json'
def validate_pair_checkpoint(path,cfg_hash,pair):
 try:data=json.loads(path.read_text())
 except Exception as exc:raise RegressionInputError(f'malformed pair checkpoint: {path}') from exc
 if data.get('status')!='complete' or data.get('manifest_hash')!=cfg_hash or (data.get('representation'),data.get('method'))!=pair:raise RegressionInputError(f'invalid pair checkpoint identity: {path}')
 predictions=data.get('test_predictions'); result=data.get('result')
 if not isinstance(result,dict) or not isinstance(predictions,list) or data.get('expected_test_row_count')!=4326 or len(predictions)!=4326:raise RegressionInputError(f'incomplete pair checkpoint: {path}')
 keys=[]
 for row in predictions:
  try:key=(row['representation'],row['method'],int(row['source_frame_id']),row['rx_id']);float(row['target']);float(row['prediction'])
  except (KeyError,TypeError,ValueError) as exc:raise RegressionInputError(f'malformed checkpoint prediction: {path}') from exc
  if key[:2]!=pair:raise RegressionInputError(f'checkpoint prediction pair mismatch: {path}')
  keys.append(key)
 if len(keys)!=len(set(keys)):raise RegressionInputError(f'duplicate checkpoint prediction keys: {path}')
 return data
def discover_checkpoints(out,cfg_hash,jobs):
 directory=out/'checkpoints';directory.mkdir(parents=True,exist_ok=True); found=[]; names=set()
 for path in sorted(directory.glob('*.json')):
  stem=path.stem; matches=[pair for pair in jobs if f'{pair[0]}_{pair[1]}'==stem]
  if len(matches)!=1:raise RegressionInputError(f'unexpected checkpoint filename: {path.name}')
  pair=matches[0]
  if pair in names:raise RegressionInputError('duplicate pair checkpoint')
  found.append(validate_pair_checkpoint(path,cfg_hash,pair));names.add(pair)
 return found
def write_outputs(out,results,pred):
 _write_json(out/'results.json',results);_write_csv(out/'test_predictions.csv',['representation','method','source_frame_id','rx_id','target','prediction'],pred);_write_csv(out/'summary.csv',['representation','method','validation_mae','validation_rmse','test_mae','test_rmse','input_dimension','measurement_aided','scene_based'],[{'representation':r['representation'],'method':r['method'],'validation_mae':r['validation_metrics']['mae'],'validation_rmse':r['validation_metrics']['rmse'],'test_mae':r['test_metrics']['mae'],'test_rmse':r['test_metrics']['rmse'],'input_dimension':r['input_dimension'],'measurement_aided':r['measurement_aided'],'scene_based':r['scene_based']} for r in results])
def rebuild_aggregates(out,cfg_hash,jobs):
 checkpoints=discover_checkpoints(out,cfg_hash,jobs);results=[x['result'] for x in checkpoints];pred=[r for x in checkpoints for r in x['test_predictions']];write_outputs(out,results,pred);return checkpoints
def status(out,start,completed,current,pending,failure=None):_write_json(out/'progress.json',{'start_timestamp_utc':start,'update_timestamp_utc':now(),'completed_pairs':[list(x) for x in completed],'currently_running_pair':None if current is None else list(current),'pending_pairs':[list(x) for x in pending],'failure':failure})
def main(argv=None):
 p=argparse.ArgumentParser();p.add_argument('--experiment-root',type=Path,required=True);p.add_argument('--smoke',action='store_true');p.add_argument('--full',action='store_true');p.add_argument('--force',action='store_true');p.add_argument('--resume',action='store_true');a=p.parse_args(argv)
 if a.smoke==a.full or a.force and a.resume:p.error('choose one mode and do not combine --force with --resume')
 run=a.experiment_root.resolve();arrays,rows,alignment=load_aligned(run,['G','GS','GI','GSI']);ctx=np.load(run/'features/classical_ml_descriptor_v2/link_context.npy',mmap_mode='r');reps=('CTX','G') if a.smoke else tuple(MODES); cfg=config(reps)
 if ctx.shape!=(len(rows),16) or not np.isfinite(ctx).all() or {'CTX':16,**{k:16+v.shape[1] for k,v in arrays.items()}}!=MODES:raise RegressionInputError('canonical CTX feature contract failure')
 parts=split(rows);jobs=[(r,m) for r in reps for m in METHODS];mode='smoke' if a.smoke else 'full';out=run/'results/best_beam_power_regression_ctx'/mode;modelout=run/'models/best_beam_power_regression_ctx'/mode;report=run/'reports/best_beam_power_regression_ctx'/mode
 if a.force:
  for q in(out,modelout,report):
   if q.exists():shutil.rmtree(q)
 if out.exists() and not a.resume and not a.force:raise RegressionInputError('existing CTX output; use --resume or --force')
 for q in(out,modelout,report):q.mkdir(parents=True,exist_ok=True)
 manifest=out/'manifest.json';cfg_hash=manifest_hash(cfg);start=now();results=[];pred=[]
 if a.resume:
  if not manifest.is_file() or json.loads(manifest.read_text())!=cfg:raise RegressionInputError('resume manifest/configuration mismatch')
  old_progress=json.loads((out/'progress.json').read_text()) if (out/'progress.json').is_file() else {}
  start=old_progress.get('start_timestamp_utc',start)
 else:_write_json(manifest,cfg);_write_json(out/'alignment.json',alignment)
 checkpoints=rebuild_aggregates(out,cfg_hash,jobs);results=[x['result'] for x in checkpoints];pred=[r for x in checkpoints for r in x['test_predictions']];completed={(x['representation'],x['method']) for x in checkpoints}
 y=np.asarray([float(r[TARGET_NAME]) for r in rows]);fi=np.flatnonzero(parts['fit']);va=np.flatnonzero(parts['validation']);dev=np.flatnonzero(parts['fit']|parts['validation']);te=np.flatnonzero(parts['test'])
 try:
  for rep,name in jobs:
   if (rep,name) in completed:continue
   pending=[j for j in jobs if j not in completed and j!=(rep,name)];status(out,start,sorted(completed),(rep,name),pending);x=np.asarray(ctx,np.float32) if rep=='CTX' else np.concatenate((ctx,arrays[rep]),axis=1)
   if name in ('per_rx_median','persistence'):vp,_=baseline(name,rows,y,va,fi);tp,params=baseline(name,rows,y,te,dev);selected={}
   else:
    scored=[]
    for n,param in enumerate(GRIDS[name]):
     est=make(name,param);est.fit(x[fi],y[fi]);metric=regression_metrics(y[va],est.predict(x[va]));scored.append((metric['mae'],param));_write_json(out/f'grid_{rep}_{name}.json',{'representation':rep,'method':name,'completed_candidates':n+1,'candidates':[{'parameters':z[1],'validation_mae':z[0]} for z in scored]})
    _,selected=min(scored,key=lambda z:(z[0],json.dumps(z[1],sort_keys=True)));est=make(name,selected);est.fit(x[fi],y[fi]);vp=est.predict(x[va]);est=make(name,selected);est.fit(x[dev],y[dev]);tp=est.predict(x[te]);params={**selected,'retained_dimension':int(est.named_steps['variance'].get_support().sum())};tmp=modelout/f'{rep}_{name}.pkl.tmp';pickle.dump(est,tmp.open('wb'));tmp.replace(modelout/f'{rep}_{name}.pkl')
   vm=regression_metrics(y[va],vp);tm=regression_metrics(y[te],tp);rx={u:regression_metrics(y[te][np.asarray([rows[i]['rx_id']==u for i in te])],tp[np.asarray([rows[i]['rx_id']==u for i in te])]) for u in sorted({r['rx_id'] for r in rows})};record={'representation':rep,'method':name,'input_dimension':int(x.shape[1]),'validation_metrics':vm,'test_metrics':tm,'per_rx_test_metrics':rx,'selected_parameters':params,'measurement_aided':name=='persistence','scene_based':rep!='CTX' and name not in ('per_rx_median','persistence')};pair_predictions=[{'representation':rep,'method':name,'source_frame_id':rows[i]['source_frame_id'],'rx_id':rows[i]['rx_id'],'target':float(y[i]),'prediction':float(v)} for i,v in zip(te,tp)];checkpoint={'status':'complete','representation':rep,'method':name,'expected_test_row_count':4326,'manifest_hash':cfg_hash,'completion_timestamp_utc':now(),'result':record,'test_predictions':pair_predictions};_write_json(checkpoint_path(out,(rep,name)),checkpoint);checkpoints=rebuild_aggregates(out,cfg_hash,jobs);results=[x['result'] for x in checkpoints];pred=[r for x in checkpoints for r in x['test_predictions']];completed={(x['representation'],x['method']) for x in checkpoints};status(out,start,sorted(completed),None,[j for j in jobs if j not in completed]);del x
 except Exception as e:
  status(out,start,sorted(completed),None,[j for j in jobs if j not in completed],{'type':type(e).__name__,'message':str(e)});raise
 (report/'report.md').write_text('CTX is included in every scene mode; persistence is measurement-aided. Target is absolute simulated received power in dBm, not RSRP.\n');(out/'execution.log').write_text('\n'.join(f'{r["representation"]} {r["method"]}' for r in results)+'\n');print(out)
if __name__=='__main__':main()
