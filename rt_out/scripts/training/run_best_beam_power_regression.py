#!/usr/bin/env python3
"""Leakage-safe best-beam received-power regression CLI."""
from __future__ import annotations
import argparse, json, math, pickle, shutil, sys, tempfile, warnings
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent; sys.path[:0]=[str(HERE),str(HERE.parent)]
SEMANTIC_HELPERS=HERE.parent/'experiments'/'semantic_ablation'; sys.path.insert(0,str(SEMANTIC_HELPERS))
from best_beam_power_regression import (TARGET_NAME,TARGET_UNIT,RegressionInputError,_read_csv,_write_csv,_write_json,audit_target,build_targets,load_aligned,regression_metrics,source_paths,temporal_split)
from experiment_paths import resolve_experiment_root,run_output,experiment_log_path
from release_hardening import (atomic_promote_files, assess_compatibility, canonical_manifest_payload,
                               installed_versions, invocation_manifest_payload, new_invocation_id,
                               source_hashes, stable_source_hash, validate_run_invocation_binding,
                               write_canonical_manifest, write_invocation_manifest)

MODELS=('mean','per_rx_mean','persistence','ridge','elastic_net','random_forest','rbf_svr')
REGRESSION_IMPLEMENTATION_VERSION='best_beam_power_regression_v2'
METRIC_REL_TOL=1e-9
METRIC_ABS_TOL=1e-10
GRIDS={'ridge':[{'alpha':v} for v in (.1,1.,10.)], 'elastic_net':[{'alpha':a,'l1_ratio':r,'tol':1e-4,'max_iter':100000} for a in (.001,.01,.05,.1) for r in (.2,.5,.8)], 'random_forest':[{'max_depth':d,'min_samples_leaf':leaf,'n_estimators':200} for d in (8,20) for leaf in (1,4)], 'rbf_svr':[{'C':c,'epsilon':e,'cache_size':500} for c in (1.,10.) for e in (.05,.2)]}
_ACTIVE_INVOCATION=None

def parser():
 p=argparse.ArgumentParser(description=__doc__); p.add_argument('--experiment-root',type=Path,required=True)
 for flag in ('audit-target','build-targets','validate-inputs','validate-results','dry-run','smoke','full','summarize-results'): p.add_argument('--'+flag,action='store_true')
 p.add_argument('--result-mode',choices=('smoke','full'),default='full'); p.add_argument('--representation',action='append',choices=('G','GS','GI','GSI')); p.add_argument('--model',action='append',choices=MODELS); p.add_argument('--seed',type=int,default=42); p.add_argument('--force',action='store_true'); p.add_argument('--allow-legacy-summary',action='store_true'); return p

def temporal_metadata(rows):
 from best_beam_power_regression import temporal_split
 return temporal_split(rows)
def masks(rows):
 meta=temporal_metadata(rows); values={name:set(range(info['frame_range'][0],info['frame_range'][1]+1)) if info['frame_range'] else set() for name,info in meta['splits'].items()}; out={name:np.asarray([int(r['source_frame_id']) in frames for r in rows]) for name,frames in values.items()}
 if not all(out[x].any() for x in ('training','validation','test')): raise RegressionInputError('training, validation, and test masks must be non-empty')
 return out
def output_paths(run,mode): return tuple(run_output(run,root,'best_beam_power_regression',mode) for root in ('results','models','reports'))
def progress(log,message): print(message); log.write(message+'\n'); log.flush()
def regression_input_paths(run, representations):
 descriptor=run/'features/classical_ml_descriptor_v2'
 scores,manifest,target=source_paths(run)
 return (scores,manifest,target,descriptor/'row_index.csv',*[descriptor/f'{name}.npy' for name in representations])
def job_inventory(jobs):
 return [list(job) for job in sorted({(str(rep),str(model)) for rep,model in jobs})]
def normalize_cli_args(value):
 if isinstance(value,Path):
  try: return str(value.resolve().relative_to(Path(__file__).resolve().parents[3]))
  except ValueError: return '<external-path>'
 if isinstance(value,dict): return {str(key):normalize_cli_args(item) for key,item in value.items()}
 if isinstance(value,(list,tuple)): return [normalize_cli_args(item) for item in value]
 return value
def regression_dependency_versions():
 return installed_versions(('numpy','scikit-learn','scipy','joblib'))
def canonical_manifest_for(run,mode,jobs,input_hashes,seed):
 return canonical_manifest_payload(
  experiment_identity={'experiment_name':run.name,'model_family':'best_beam_power_regression','mode':mode},
  expected_jobs=jobs,input_hashes=input_hashes,
  scientific_configuration={'representations':['G','GS','GI','GSI'],'models':list(MODELS),'mode':mode,'selection_metric':'validation_mae','target_name':TARGET_NAME,'target_unit':TARGET_UNIT},
  implementation_version=REGRESSION_IMPLEMENTATION_VERSION,seed=seed)
def binding_metadata(invocation_id,mode,job,status,created_at_utc,canonical_manifest_sha256,input_hashes,source_fingerprints,dependency_versions):
 return {'invocation_id':invocation_id,'invocation_manifest':f'invocations/{invocation_id}.json','execution_source_hashes':dict(sorted(source_fingerprints.items())),'dependency_versions':dict(sorted(dependency_versions.items())),'created_at_utc':created_at_utc,'job_identity':list(job),'execution_status':status,'canonical_manifest_sha256':canonical_manifest_sha256,'input_hashes':dict(sorted(input_hashes.items()))}
def provenance(run,input_hashes,invocation,seed,binding):
 repo=Path(__file__).resolve().parents[3]
 try: experiment_identity=str(run.relative_to(repo))
 except ValueError: experiment_identity=run.name
 return {'schema_version':'best_beam_provenance_v2','experiment_root':experiment_identity,**binding,'invocation':invocation,'seed':seed,'python':sys.version}

def _record_failed_invocation():
 global _ACTIVE_INVOCATION
 if _ACTIVE_INVOCATION is None: return
 context=_ACTIVE_INVOCATION
 failed_jobs=context['failed_jobs'] or [job for job in context['jobs'] if job not in context['completed_jobs']]
 failed=invocation_manifest_payload(invocation_id=context['invocation_id'],requested_jobs=context['jobs'],normalized_cli_args=context['normalized_cli_args'],execution_source_hashes=context['source_fingerprints'],dependency_versions=context['dependency_versions'],command_mode=context['mode'],canonical_manifest_sha256=context['canonical_manifest_sha256'],input_hashes=context['input_hashes'],timestamp_utc=context['timestamp_utc'],status='failed',completed_jobs=context['completed_jobs'],resumed_jobs=context['resumed_jobs'],failed_jobs=failed_jobs)
 write_invocation_manifest(context['out']/'invocations',failed)
 _ACTIVE_INVOCATION=None

def regression_input_hashes(run,representations):
 return {str(path.relative_to(run)):stable_source_hash(path) for path in regression_input_paths(run,representations)}

def _source_fingerprints():
 repo=Path(__file__).resolve().parents[3]
 return source_hashes((Path(__file__).resolve(),HERE/'best_beam_power_regression.py',HERE.parent/'experiment_paths.py',SEMANTIC_HELPERS/'release_hardening.py'),project_root=repo)

def artifact_manifest_value(run,mode,extra_artifacts=None):
 out,modelout,reportout=output_paths(run,mode)
 candidates=[out/name for name in ('experiment_manifest.json','provenance_manifest.json','target_alignment_report.json','resolved_split.json','validation_summary.json','detailed_run_results.csv','held_out_predictions.csv')]
 candidates.extend(sorted((out/'invocations').glob('*.json')))
 candidates.extend(sorted(modelout.glob('*.pkl')))
 candidates.append(reportout/'best_beam_power_regression_report.json')
 optional=out/'best_model_summary.csv'
 if optional.is_file(): candidates.append(optional)
 files={}
 for path in candidates:
  if not path.is_file(): raise RegressionInputError(f'artifact manifest source is missing: {path}')
  relative=str(path.relative_to(run)); files[relative]={'path':relative,'sha256':stable_source_hash(path)}
 for relative,path in (extra_artifacts or {}).items():
  if not path.is_file(): raise RegressionInputError(f'artifact manifest source is missing: {path}')
  files[relative]={'path':relative,'sha256':stable_source_hash(path)}
 return {'schema_version':'best_beam_artifact_manifest_v1','manifest_kind':'regression_artifacts','mode':mode,'files':[files[key] for key in sorted(files)]}

def write_artifact_manifest(run,mode):
 out,_,_=output_paths(run,mode)
 _write_json(out/'artifact_manifest.json',artifact_manifest_value(run,mode))

def write_summary_transactional(run,mode,fields,rows):
 out,_,_=output_paths(run,mode)
 with tempfile.TemporaryDirectory(prefix='best_beam_summary_',dir=out.parent) as temporary:
  stage=Path(temporary); staged_summary=stage/'best_model_summary.csv'
  _write_csv(staged_summary,fields,rows)
  relative=str((out/'best_model_summary.csv').relative_to(run))
  manifest=artifact_manifest_value(run,mode,{relative:staged_summary})
  staged_manifest=stage/'artifact_manifest.json'; _write_json(staged_manifest,manifest)
  atomic_promote_files({staged_summary:out/'best_model_summary.csv',staged_manifest:out/'artifact_manifest.json'})

def write_legacy_summary_transactional(run,mode,fields,rows,validation):
 out,_,_=output_paths(run,mode)
 source=out/'detailed_run_results.csv'
 relative=str(source.relative_to(run))
 metadata={
  'schema_version':'best_beam_legacy_summary_metadata_v1',
  'manifest_kind':'legacy_summary_metadata',
  'mode':mode,
  'structural_validation_passed':True,
  'release_validation_passed':False,
  'provenance_status':validation.get('provenance_status','missing'),
  'source_result_hashes':{relative:stable_source_hash(source)},
 }
 with tempfile.TemporaryDirectory(prefix='best_beam_legacy_summary_',dir=out.parent) as temporary:
  stage=Path(temporary); staged_summary=stage/'best_model_summary.csv'; staged_metadata=stage/'legacy_summary_metadata.json'
  _write_csv(staged_summary,fields,rows); _write_json(staged_metadata,metadata)
  atomic_promote_files({staged_summary:out/'best_model_summary.csv',staged_metadata:out/'legacy_summary_metadata.json'})

def _finite(value):
 if isinstance(value,dict): return all(_finite(item) for item in value.values())
 if isinstance(value,list): return all(_finite(item) for item in value)
 if isinstance(value,(int,float)): return math.isfinite(float(value))
 return True

def _load_json(path):
 try: return json.loads(path.read_text(encoding='utf-8'))
 except (OSError,json.JSONDecodeError) as exc: raise RegressionInputError(f'invalid JSON artifact: {path}') from exc

def _validate_artifact_manifest(run,base,mode,modelout,reportout):
 path=base/'artifact_manifest.json'
 if not path.is_file(): return {'status':'missing','verified':False}
 manifest=_load_json(path)
 if manifest.get('schema_version')!='best_beam_artifact_manifest_v1' or manifest.get('mode')!=mode: raise RegressionInputError('invalid artifact manifest schema or mode')
 entries=manifest.get('files')
 if not isinstance(entries,list): raise RegressionInputError('artifact manifest files must be a list')
 actual={}
 for entry in entries:
  if not isinstance(entry,dict) or not isinstance(entry.get('path'),str) or not isinstance(entry.get('sha256'),str): raise RegressionInputError('malformed artifact manifest entry')
  relative=Path(entry['path'])
  if relative.is_absolute() or '..' in relative.parts: raise RegressionInputError('artifact manifest contains a non-portable path')
  if entry['path'] in actual: raise RegressionInputError('artifact manifest contains duplicate paths')
  artifact=run/relative
  if not artifact.is_file(): raise RegressionInputError(f'artifact manifest references missing file: {relative}')
  digest=stable_source_hash(artifact)
  if digest!=entry['sha256']: raise RegressionInputError(f'artifact hash mismatch: {relative}')
  actual[entry['path']]=digest
 expected=[base/name for name in ('experiment_manifest.json','provenance_manifest.json','target_alignment_report.json','resolved_split.json','validation_summary.json','detailed_run_results.csv','held_out_predictions.csv')]
 expected.extend(sorted((base/'invocations').glob('*.json')))
 expected.extend(sorted(modelout.glob('*.pkl'))); expected.append(reportout/'best_beam_power_regression_report.json')
 optional=base/'best_model_summary.csv'
 if optional.is_file(): expected.append(optional)
 expected_names={str(item.relative_to(run)) for item in expected}
 if set(actual)!=expected_names: raise RegressionInputError('artifact manifest inventory does not match generated outputs')
 return {'status':'verified','verified':True,'files':len(actual)}

def _validate_prediction_rows(predictions,items,aligned):
 test_rows=[row for row in aligned if row['split']=='test']
 expected=[(int(row['source_frame_id']),row['rx_id'],int(row['row_index']),float(row[TARGET_NAME])) for row in test_rows]
 grouped={}
 for prediction in predictions:
  key=(prediction.get('representation'),prediction.get('model'))
  grouped.setdefault(key,[]).append(prediction)
 expected_keys=[(frame,rx) for frame,rx,_,_ in expected]
 validated={}
 for item in items:
  key=(item.get('representation'),item.get('model'))
  rows=grouped.pop(key,[])
  if len(rows)!=len(expected): raise RegressionInputError(f'prediction count mismatch for {key}: expected {len(expected)}, got {len(rows)}')
  keys=[]; y_true=[]; y_pred=[]; rx_ids=[]
  for prediction,expected_row in zip(rows,expected,strict=True):
   frame,rx,row_index,target=expected_row
   try: observed=(int(prediction['source_frame_id']),prediction['rx_id'])
   except (KeyError,TypeError,ValueError) as exc: raise RegressionInputError(f'invalid prediction row identity for {key}') from exc
   if observed!=(frame,rx): raise RegressionInputError(f'prediction row order or identity mismatch for {key}')
   if 'split' in prediction and prediction['split']!='test': raise RegressionInputError(f'prediction row is not in test split for {key}')
   if 'row_index' in prediction and int(prediction['row_index'])!=row_index: raise RegressionInputError(f'prediction row_index mismatch for {key}')
   if float(prediction['y_true'])!=target or not math.isfinite(float(prediction['y_pred'])): raise RegressionInputError(f'prediction target or value mismatch for {key}')
   keys.append(observed)
   y_true.append(target); y_pred.append(float(prediction['y_pred'])); rx_ids.append(rx)
  if keys!=expected_keys or len(set(keys))!=len(keys): raise RegressionInputError(f'test key order mismatch for {key}')
  if set(row['rx_id'] for row in rows)!=set(item.get('per_rx_metrics',{})): raise RegressionInputError(f'per-RX coverage mismatch for {key}')
  validated[key]={'y_true':np.asarray(y_true,float),'y_pred':np.asarray(y_pred,float),'rx_ids':rx_ids}
 if grouped: raise RegressionInputError(f'predictions contain unlisted combinations: {sorted(grouped)}')
 return len(expected),expected_keys,validated

def _metrics_match(expected,actual,label):
 if set(expected)!=set(actual): raise RegressionInputError(f'{label} metric fields differ')
 for name in expected:
  left,right=expected[name],actual[name]
  if isinstance(left,(int,float)) and isinstance(right,(int,float)):
   if not math.isclose(float(left),float(right),rel_tol=METRIC_REL_TOL,abs_tol=METRIC_ABS_TOL): raise RegressionInputError(f'{label} metric mismatch: {name}')
  elif left!=right:
   raise RegressionInputError(f'{label} metric mismatch: {name}')

def _validate_recomputed_metrics(items,validated):
 for item in items:
  key=(item['representation'],item['model']); values=validated[key]
  aggregate=regression_metrics(values['y_true'],values['y_pred'])
  _metrics_match(aggregate,item['aggregate_metrics'],f'{key} aggregate')
  expected_per_rx={rx:regression_metrics(values['y_true'][np.asarray([value==rx for value in values['rx_ids']])],values['y_pred'][np.asarray([value==rx for value in values['rx_ids']])]) for rx in sorted(set(values['rx_ids']))}
  _metrics_match(expected_per_rx,item['per_rx_metrics'],f'{key} per-RX')

def _validate_detail_consistency(summary_items,details):
 if len(summary_items)!=len(details): raise RegressionInputError('detailed results and validation summary have different row counts')
 scalar=('representation','model','seed','feature_count','target_name','target_unit','final_fit_partition')
 structured=('validation_metrics','aggregate_metrics','per_rx_metrics','convergence','parameters')
 for summary,detail in zip(summary_items,details,strict=True):
  for field in scalar:
   expected=summary.get(field); observed=detail.get(field)
   if field in ('seed','feature_count'): observed=int(observed)
   if observed!=expected: raise RegressionInputError(f'detailed result mismatch in {field}')
  for field in structured:
   try: observed=json.loads(detail[field])
   except (KeyError,json.JSONDecodeError) as exc: raise RegressionInputError(f'invalid detailed JSON field: {field}') from exc
   if observed!=summary.get(field): raise RegressionInputError(f'detailed result mismatch in {field}')

def validate_result_tree(base,mode):
 required=[base/'validation_summary.json',base/'detailed_run_results.csv',base/'held_out_predictions.csv',base/'resolved_split.json',base/'target_alignment_report.json']
 if any(not p.is_file() for p in required): raise RegressionInputError('regression result set is incomplete')
 summary=_load_json(base/'validation_summary.json'); predictions=_read_csv(base/'held_out_predictions.csv'); details=_read_csv(base/'detailed_run_results.csv'); items=summary.get('runs',[])
 if summary.get('mode')!=mode or summary.get('selection_metric')!='validation_mae' or not isinstance(items,list) or not items: raise RegressionInputError('invalid mode, selection protocol, or result inventory')
 expected={(r,m) for r in ('G','GS','GI','GSI') for m in MODELS}
 actual={(item.get('representation'),item.get('model')) for item in items}
 if mode=='full' and (len(items)!=len(expected) or actual!=expected): raise RegressionInputError('full result inventory must contain exactly 28 requested combinations')
 if len(actual)!=len(items) or any(rep not in ('G','GS','GI','GSI') or model not in MODELS for rep,model in actual): raise RegressionInputError('result inventory contains duplicate or unsupported combinations')
 for item in items:
  if item.get('final_fit_partition')!='training_plus_validation' or (item.get('model') not in ('mean','per_rx_mean','persistence') and not item.get('convergence',{}).get('converged')): raise RegressionInputError('selected model is non-converged or final-fit protocol is invalid')
  if not _finite(item.get('validation_metrics')) or not _finite(item.get('aggregate_metrics')) or not _finite(item.get('per_rx_metrics')): raise RegressionInputError('non-finite metric')
 run=base.parents[2]; representations=[]
 for item in items:
  if item['representation'] not in representations: representations.append(item['representation'])
 arrays,aligned,alignment=load_aligned(run,representations)
 if _load_json(base/'target_alignment_report.json')!=alignment or _load_json(base/'resolved_split.json')!=temporal_metadata(aligned): raise RegressionInputError('alignment or split metadata is inconsistent with source inputs')
 _validate_detail_consistency(items,details)
 test_count,test_keys,validated_predictions=_validate_prediction_rows(predictions,items,aligned)
 _validate_recomputed_metrics(items,validated_predictions)
 _,modelout,reportout=output_paths(run,mode)
 trainable=set(MODELS)-{'mean','per_rx_mean','persistence'}; expected_models={f'{item["representation"]}_{item["model"]}.pkl' for item in items if item['model'] in trainable}; actual_models={path.name for path in modelout.glob('*.pkl')}
 if actual_models!=expected_models: raise RegressionInputError(f'model inventory mismatch: expected {sorted(expected_models)}, got {sorted(actual_models)}')
 artifact_status=_validate_artifact_manifest(run,base,mode,modelout,reportout)
 expected_inputs=regression_input_hashes(run,representations)
 expected_jobs=[(item['representation'],item['model']) for item in items]
 expected_invocation={'mode':mode,'jobs':job_inventory(expected_jobs)}
 expected_sources=_source_fingerprints(); expected_dependencies=regression_dependency_versions()
 canonical_path=base/'experiment_manifest.json'; canonical_hash=stable_source_hash(canonical_path) if canonical_path.is_file() else None
 canonical_error=None
 if canonical_path.is_file():
  try:
   if _load_json(canonical_path)!=canonical_manifest_for(run,mode,expected_jobs,expected_inputs,int(items[0].get('seed',-1))): canonical_error='canonical experiment manifest differs from the current result inventory'
  except (OSError,TypeError,ValueError,RegressionInputError) as exc: canonical_error=str(exc)
 else: canonical_error='canonical experiment manifest is missing'
 provenance_path=base/'provenance_manifest.json'; provenance_data=_load_json(provenance_path) if provenance_path.is_file() else None
 compatibility=assess_compatibility(provenance_data,expected_source_hashes=expected_sources,expected_input_hashes=expected_inputs)
 binding_errors=[]
 if provenance_data is not None:
  if provenance_data.get('invocation')!=expected_invocation: binding_errors.append('invocation inventory differs from results')
  if provenance_data.get('seed')!=items[0].get('seed'): binding_errors.append('seed provenance differs from results')
  if canonical_error: binding_errors.append(canonical_error)
  if provenance_data.get('canonical_manifest_sha256')!=canonical_hash: binding_errors.append('provenance canonical manifest hash differs from the current manifest')
  if provenance_data.get('input_hashes')!=expected_inputs: binding_errors.append('provenance input hashes differ from current inputs')
  if provenance_data.get('job_identity')!=['best_beam_power_regression',mode]: binding_errors.append('provenance result identity is invalid')
  if provenance_data.get('execution_status') not in ('generated','resumed'): binding_errors.append('provenance execution status is invalid')
  for item in items:
   job=(item['representation'],item['model'])
   if item.get('canonical_manifest_sha256')!=canonical_hash or item.get('input_hashes')!=expected_inputs: binding_errors.append(f'job {job} canonical or input hashes differ')
   try:
    validate_run_invocation_binding(base,item,job,expected_execution_source_hashes=expected_sources,expected_dependency_versions=expected_dependencies)
   except Exception as exc:
    binding_errors.append(f'job {job} invocation binding: {exc}')
  if binding_errors: compatibility={**compatibility,'release_validation_passed':False,'reason':'; '.join(filter(None,(compatibility.get('reason'),*binding_errors)))}
 release_passed=bool(compatibility.get('release_validation_passed') and not binding_errors and canonical_path.is_file() and artifact_status['verified'])
 return {'passed':release_passed,'structural_validation_passed':True,'runs':len(items),'test_rows_per_run':test_count,'result_directory':str(base),'provenance_status':compatibility['status'],'compatibility':compatibility,'invocation_binding_status':'verified' if provenance_data is not None and not binding_errors else 'missing_or_invalid','canonical_manifest_status':'verified' if provenance_data is not None and not canonical_error else 'missing_or_invalid','artifact_manifest_status':artifact_status['status'],'artifact_hashes_verified':artifact_status['verified'],'model_inventory':{'expected':sorted(expected_models),'actual':sorted(actual_models)},'release_validation_passed':release_passed}

def make_model(name,params,seed):
 from sklearn.pipeline import Pipeline
 from sklearn.preprocessing import StandardScaler
 from sklearn.linear_model import Ridge,ElasticNet
 from sklearn.ensemble import RandomForestRegressor
 from sklearn.svm import SVR
 if name=='ridge': return Pipeline([('scale',StandardScaler()),('model',Ridge(alpha=params['alpha'],tol=1e-4))])
 if name=='elastic_net': return Pipeline([('scale',StandardScaler()),('model',ElasticNet(alpha=params['alpha'],l1_ratio=params['l1_ratio'],tol=params['tol'],max_iter=params['max_iter'],random_state=seed))])
 if name=='random_forest': return RandomForestRegressor(**params,random_state=seed,n_jobs=-1)
 if name=='rbf_svr': return Pipeline([('scale',StandardScaler()),('model',SVR(C=params['C'],epsilon=params['epsilon'],kernel='rbf',cache_size=params['cache_size']))])
 raise RegressionInputError('not trainable')
def fitted_estimator(estimator): return estimator.named_steps['model'] if hasattr(estimator,'named_steps') else estimator
def fit_checked(name,params,x,y,seed,log):
 """Fit once, retry Elastic Net once, and serialize convergence evidence."""
 from sklearn.exceptions import ConvergenceWarning
 attempt=0; active=dict(params)
 while True:
  estimator=make_model(name,active,seed)
  with warnings.catch_warnings(record=True) as caught:
   warnings.simplefilter('always',ConvergenceWarning); estimator.fit(x,y)
  model=fitted_estimator(estimator); warning_text=[str(item.message) for item in caught if issubclass(item.category,ConvergenceWarning)]
  fit_status=getattr(model,'fit_status_',0); n_iter=getattr(model,'n_iter_',None); n_iter=int(np.max(np.asarray(n_iter))) if n_iter is not None else None
  converged=not warning_text and (fit_status in (None,0))
  meta={'converged':bool(converged),'warning_text':warning_text,'n_iter':n_iter,'fit_status':fit_status,'max_iter':active.get('max_iter'),'tolerance':active.get('tol'),'attempt':attempt+1}
  progress(log,f'candidate {name} {active} converged={converged}')
  if converged or name!='elastic_net' or attempt: return estimator,active,meta
  attempt+=1; active['max_iter']=int(active['max_iter']*2)
def baseline_prediction(name,rows,y,indices,fitting):
 fallback=float(y[fitting].mean())
 if name=='mean': return np.full(len(indices),fallback)
 if name=='per_rx_mean':
  means={rx:float(y[[i for i in fitting if rows[i]['rx_id']==rx]].mean()) for rx in {r['rx_id'] for r in rows}}
  return np.asarray([means[rows[i]['rx_id']] for i in indices])
 lookup={(int(r['source_frame_id']),r['rx_id']):float(v) for r,v in zip(rows,y,strict=True)}
 return np.asarray([lookup.get((int(rows[i]['source_frame_id'])-1,rows[i]['rx_id']),fallback) for i in indices])
def select(name,x,y,part,rows,seed,log):
 tr,va=np.flatnonzero(part['training']),np.flatnonzero(part['validation'])
 if name in ('mean','per_rx_mean','persistence'):
  pred=baseline_prediction(name,rows,y,va,tr); return {},regression_metrics(y[va],pred),{'converged':True,'baseline_statistics_partition':'training','baseline_type':'previous-measurement-aided' if name=='persistence' else 'fitting-only'},None
 candidates=[]
 for params in GRIDS[name]:
  estimator,used,meta=fit_checked(name,params,x[tr],y[tr],seed,log)
  if meta['converged']:
   pred=estimator.predict(x[va]);
   if not np.isfinite(pred).all(): meta['converged']=False; meta['warning_text'].append('non-finite validation prediction')
  if meta['converged']:
   metric=regression_metrics(y[va],pred); candidates.append((metric['mae'],used,meta,metric))
 if not candidates: raise RegressionInputError(f'no converged candidate for {name}')
 _,params,metadata,metric=min(candidates,key=lambda z:(z[0],json.dumps(z[1],sort_keys=True))); progress(log,f'selected {name} {params} validation_mae={metric["mae"]:.6g}')
 return params,metric,metadata,None

def main(argv=None):
 args=parser().parse_args(argv); run=resolve_experiment_root(args.experiment_root,create=False,require_existing=True); modes=sum(getattr(args,x.replace('-','_')) for x in ('audit-target','build-targets','validate-inputs','validate-results','dry-run','smoke','full','summarize-results'))
 if modes!=1: parser().error('choose exactly one execution mode')
 if args.allow_legacy_summary and not args.summarize_results: parser().error('--allow-legacy-summary is only valid with --summarize-results')
 if args.audit_target: print(json.dumps(audit_target(run),indent=2)); return
 if args.build_targets: print(json.dumps(build_targets(run)[1],indent=2)); return
 if args.validate_results: print(json.dumps(validate_result_tree(output_paths(run,args.result_mode)[0],args.result_mode),indent=2)); return
 if args.summarize_results:
  base=output_paths(run,args.result_mode)[0]
  validation=validate_result_tree(base,args.result_mode)
  if not validation.get('structural_validation_passed'):
   raise RegressionInputError('cannot summarize structurally invalid results')
  if not validation.get('release_validation_passed'):
   if not args.allow_legacy_summary or validation.get('provenance_status') != 'missing':
    raise RegressionInputError('cannot summarize results without release validation; --allow-legacy-summary is limited to missing-provenance legacy outputs')
  rows=_read_csv(base/'detailed_run_results.csv'); best={}
  for row in rows:
   if row['representation'] not in best or float(json.loads(row['validation_metrics'])['mae'])<float(json.loads(best[row['representation']]['validation_metrics'])['mae']): best[row['representation']]=row
  if validation.get('release_validation_passed'):
   write_summary_transactional(run,args.result_mode,list(rows[0]),list(best.values()))
  else:
   write_legacy_summary_transactional(run,args.result_mode,list(rows[0]),list(best.values()),validation)
  return
 arrays,rows,alignment=load_aligned(run,args.representation); split=temporal_metadata(rows); part=masks(rows); models=args.model or (['mean','per_rx_mean','ridge'] if args.smoke else list(MODELS))
 if args.validate_inputs: print(json.dumps({**alignment,'resolved_split':split},indent=2)); return
 if args.dry_run: print(json.dumps({'dry_run':True,'would_fit_models':models,'resolved_split':split,'parameter_grids':GRIDS},indent=2)); return
 mode='smoke' if args.smoke else 'full'; out,modelout,reportout=output_paths(run,mode); jobs=[(rep,name) for rep in arrays for name in models]; input_hashes=regression_input_hashes(run,arrays); source_fingerprints=_source_fingerprints(); dependency_versions=regression_dependency_versions(); canonical=canonical_manifest_for(run,mode,jobs,input_hashes,args.seed)
 if any(path.exists() for path in (out,modelout,reportout)) and not args.force:
  existing=validate_result_tree(out,mode)
  if not existing.get('release_validation_passed'): raise RegressionInputError(f'refusing to resume non-release-valid {mode} outputs; pass --force for an explicit replacement')
  existing_summary=_load_json(out/'validation_summary.json'); existing_jobs=[(item['representation'],item['model']) for item in existing_summary.get('runs',[])]
  if job_inventory(existing_jobs)!=job_inventory(jobs): raise RegressionInputError(f'cannot resume a different {mode} job selection')
  write_canonical_manifest(out/'experiment_manifest.json',canonical); invocation_id=new_invocation_id(); started=invocation_manifest_payload(invocation_id=invocation_id,requested_jobs=jobs,normalized_cli_args=normalize_cli_args(vars(args)),execution_source_hashes=source_fingerprints,dependency_versions=dependency_versions,command_mode=mode,canonical_manifest_sha256=stable_source_hash(out/'experiment_manifest.json'),input_hashes=input_hashes,status='started'); write_invocation_manifest(out/'invocations',started); timestamp=started['timestamp_utc']; context={'out':out,'mode':mode,'jobs':jobs,'normalized_cli_args':normalize_cli_args(vars(args)),'source_fingerprints':source_fingerprints,'dependency_versions':dependency_versions,'canonical_manifest_sha256':stable_source_hash(out/'experiment_manifest.json'),'input_hashes':input_hashes,'invocation_id':invocation_id,'timestamp_utc':timestamp,'completed_jobs':jobs,'resumed_jobs':jobs,'failed_jobs':[]}; _ACTIVE_INVOCATION=context
  for item in existing_summary['runs']: item.update(binding_metadata(invocation_id,mode,(item['representation'],item['model']),'resumed',timestamp,context['canonical_manifest_sha256'],input_hashes,source_fingerprints,dependency_versions))
  existing_summary['runs']=existing_summary['runs']; _write_json(out/'validation_summary.json',existing_summary); _write_json(out/'provenance_manifest.json',provenance(run,input_hashes,{'mode':mode,'jobs':job_inventory(jobs)},args.seed,binding_metadata(invocation_id,mode,('best_beam_power_regression',mode),'resumed',timestamp,context['canonical_manifest_sha256'],input_hashes,source_fingerprints,dependency_versions))); completed=invocation_manifest_payload(invocation_id=invocation_id,requested_jobs=jobs,normalized_cli_args=context['normalized_cli_args'],execution_source_hashes=source_fingerprints,dependency_versions=dependency_versions,command_mode=mode,canonical_manifest_sha256=context['canonical_manifest_sha256'],input_hashes=input_hashes,timestamp_utc=timestamp,status='completed',completed_jobs=jobs,resumed_jobs=jobs); write_invocation_manifest(out/'invocations',completed); write_artifact_manifest(run,mode); _ACTIVE_INVOCATION=None; print(json.dumps(validate_result_tree(out,mode),indent=2)); return
 if any(path.exists() for path in (out,modelout,reportout)):
  for path in (out,modelout,reportout):
   if path.exists(): shutil.rmtree(path)
 for path in (out,modelout,reportout): path.mkdir(parents=True,exist_ok=True)
 write_canonical_manifest(out/'experiment_manifest.json',canonical); invocation_id=new_invocation_id(); started=invocation_manifest_payload(invocation_id=invocation_id,requested_jobs=jobs,normalized_cli_args=normalize_cli_args(vars(args)),execution_source_hashes=source_fingerprints,dependency_versions=dependency_versions,command_mode=mode,canonical_manifest_sha256=stable_source_hash(out/'experiment_manifest.json'),input_hashes=input_hashes,status='started'); write_invocation_manifest(out/'invocations',started); timestamp=started['timestamp_utc']; _ACTIVE_INVOCATION={'out':out,'mode':mode,'jobs':jobs,'normalized_cli_args':normalize_cli_args(vars(args)),'source_fingerprints':source_fingerprints,'dependency_versions':dependency_versions,'canonical_manifest_sha256':stable_source_hash(out/'experiment_manifest.json'),'input_hashes':input_hashes,'invocation_id':invocation_id,'timestamp_utc':timestamp,'completed_jobs':[],'resumed_jobs':[],'failed_jobs':[]}
 _write_json(out/'provenance_manifest.json',provenance(run,input_hashes,{'mode':mode,'jobs':job_inventory(jobs)},args.seed,binding_metadata(invocation_id,mode,('best_beam_power_regression',mode),'generated',timestamp,_ACTIVE_INVOCATION['canonical_manifest_sha256'],input_hashes,source_fingerprints,dependency_versions)))
 log_path=experiment_log_path(run,f'training/best_beam_power_regression/{mode}.log'); y=np.asarray([float(r[TARGET_NAME]) for r in rows]); trva=part['training']|part['validation']; test=np.flatnonzero(part['test']); results=[]; predictions=[]
 with log_path.open('a') as log:
  _write_json(out/'target_alignment_report.json',alignment); _write_json(out/'resolved_split.json',split)
  for rep,x in arrays.items():
   progress(log,f'representation {rep}')
   for name in models:
    progress(log,f'model {name}'); params,valmetric,convergence,_=select(name,x,y,part,rows,args.seed,log)
    if name in ('mean','per_rx_mean','persistence'): pred=baseline_prediction(name,rows,y,test,np.flatnonzero(trva))
    else:
     progress(log,f'final refit {rep}/{name} on training_plus_validation'); estimator,params,final_convergence=fit_checked(name,params,x[trva],y[trva],args.seed,log)
     if not final_convergence['converged']: raise RegressionInputError(f'final refit did not converge: {name}')
     convergence['final_refit']=final_convergence; pred=estimator.predict(x[test]);
     if name=='ridge' and not np.isfinite(fitted_estimator(estimator).coef_).all(): raise RegressionInputError('Ridge coefficients are non-finite')
     if name=='random_forest': convergence['fitted_tree_count']=len(estimator.estimators_)
     with (modelout/f'{rep}_{name}.pkl').open('wb') as h: pickle.dump(estimator,h)
    if not np.isfinite(pred).all(): raise RegressionInputError(f'non-finite test predictions: {name}')
    aggregate=regression_metrics(y[test],pred); per_rx={rx:regression_metrics(y[test][np.asarray([rows[i]['rx_id']==rx for i in test])],pred[np.asarray([rows[i]['rx_id']==rx for i in test])]) for rx in sorted({r['rx_id'] for r in rows})}
    results.append({'representation':rep,'model':name,'parameters':params,'seed':args.seed,'target_name':TARGET_NAME,'target_unit':TARGET_UNIT,'feature_count':int(x.shape[1]),'validation_metrics':valmetric,'aggregate_metrics':aggregate,'per_rx_metrics':per_rx,'convergence':convergence,'final_fit_partition':'training_plus_validation',**binding_metadata(invocation_id,mode,(rep,name),'generated',timestamp,_ACTIVE_INVOCATION['canonical_manifest_sha256'],input_hashes,source_fingerprints,dependency_versions)})
    _ACTIVE_INVOCATION['completed_jobs'].append((rep,name))
    predictions.extend({'representation':rep,'model':name,'source_frame_id':rows[i]['source_frame_id'],'rx_id':rows[i]['rx_id'],'row_index':rows[i]['row_index'],'split':rows[i]['split'],'y_true':float(y[i]),'y_pred':float(v)} for i,v in zip(test,pred,strict=True)); progress(log,f'test evaluation {rep}/{name}')
 completed=invocation_manifest_payload(invocation_id=invocation_id,requested_jobs=jobs,normalized_cli_args=_ACTIVE_INVOCATION['normalized_cli_args'],execution_source_hashes=source_fingerprints,dependency_versions=dependency_versions,command_mode=mode,canonical_manifest_sha256=_ACTIVE_INVOCATION['canonical_manifest_sha256'],input_hashes=input_hashes,timestamp_utc=timestamp,status='completed',completed_jobs=_ACTIVE_INVOCATION['completed_jobs'],resumed_jobs=[]); write_invocation_manifest(out/'invocations',completed); _write_json(out/'validation_summary.json',{'passed':True,'mode':mode,'selection_metric':'validation_mae','runs':results}); fields=['representation','model','seed','feature_count','target_name','target_unit','validation_metrics','aggregate_metrics','per_rx_metrics','convergence','parameters','final_fit_partition']; _write_csv(out/'detailed_run_results.csv',fields,[{field:(json.dumps(r[field]) if field in ('validation_metrics','aggregate_metrics','per_rx_metrics','convergence','parameters') else r[field]) for field in fields} for r in results]); _write_csv(out/'held_out_predictions.csv',['representation','model','source_frame_id','rx_id','row_index','split','y_true','y_pred'],predictions); _write_json(reportout/'best_beam_power_regression_report.json',{'methods':models,'selection_metric':'validation_mae','final_fit_partition':'training_plus_validation'}); write_artifact_manifest(run,mode); _ACTIVE_INVOCATION=None; print(json.dumps(validate_result_tree(out,mode),indent=2))
if __name__=='__main__':
 try: main()
 except Exception:
  _record_failed_invocation()
  raise
