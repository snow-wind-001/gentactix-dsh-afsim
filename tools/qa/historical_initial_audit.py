"""Read-only audit of saved battles and all catalog initial-state factories.

Optional --native-port imports source frames in an isolated running QA backend.
It never touches the installed application's sessions or calls a language model.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from gentactix import adjudication_lib,combined_arms,history_replay,scenario_basis,historical_initial,historical_operations

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--saved-sessions',type=Path,default=Path.home()/'.config/gentactix-desktop/sessions')
p.add_argument('--traces',type=Path,default=Path.home()/'.config/gentactix-desktop/trajectories')
p.add_argument('--output',type=Path,default=ROOT/'.cache/qa/historical-initial-audit')
p.add_argument('--native-port',type=int)
p.add_argument('--require-process-ready',action='store_true',
               help='Exit nonzero when any catalog battle lacks a validated historical process initial state')
a=p.parse_args()
if a.native_port is not None and not 18900<=a.native_port<=18999:raise SystemExit('Only isolated QA ports are allowed')
a.output.mkdir(parents=True,exist_ok=True)
saved=[];manifest=[]
for path in sorted(a.saved_sessions.glob('*.json')):
    raw=path.read_bytes();manifest.append({'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()})
    session=json.loads(raw)['session'];world=session.get('war_state');errors=[]
    for artifact in (a.traces/session['id']).rglob('failed-operations/*.json'):
        record=json.loads(artifact.read_text());errors.append({'phase':record.get('phase'),'error':record.get('error'),'file':str(artifact)})
    units=[{'team':team,**{k:u.get(k) for k in ('name','type','lat','lng','hp','personnel','parameter_sources')}}
           for team in ('red','blue') for u in (world or {}).get(team+'_units',[])]
    saved.append({'id':session['id'],'battle':session.get('battle_choice'),'purpose':session.get('product_mode'),
        'simulation_mode':session.get('simulation_mode'),'engine':session.get('execution_backend','narrative'),
        'initialized':world is not None,'turn':session['turn_count'],'time':(world or {}).get('current_time'),
        'source_replay':bool((world or {}).get('history_replay')),'mission_id':session.get('mission_id'),
        'unit_count':len(units),'units':units,'failures':errors})

rows=[]
profiles={row['battle']:row for row in historical_initial.catalog()}
for battle in adjudication_lib.list_battles():
    spec=next(v for v in combined_arms.catalog() if v['battle']==battle)
    seed=scenario_basis.exercise_seed(spec['id']);legacy_frame=history_replay.frame(battle,0)
    frame=history_replay.frame_pinned(history_replay.pin(battle),0)
    readiness=None;phases=[]
    if profiles[battle]['status']=='profiled':
        baseline=historical_initial.initial(battle)
        readiness=historical_initial.readiness(baseline)
        for phase in baseline['historical_initial']['definition']['phases']:
            snapshot=historical_initial.initial(battle,phase['id'])['historical_initial']
            try:
                actors=historical_operations.partition(snapshot)
                phases.append({'id':phase['id'],'label':phase['label'],'bindable_ground_ids':actors,
                    'scope':'Identity partition only; numerical parameters, full OOB and process acceptance still required'})
            except ValueError as exc:
                phases.append({'id':phase['id'],'label':phase['label'],'bindable_ground_ids':[], 'error':str(exc)})
    rows.append({'battle':battle,'compatibility_mission_id':spec['id'],'reference_rows':len(seed['basis']['units']),
        'synthetic_default':'verified_historical_draft_required',
        'seed_scope':'Explicit representative-template compatibility path, not the current default synthetic launch',
        'references':[{k:u.get(k) for k in ('id','team','name','actual_personnel','actual_equipment','actual_tactical_position')} for u in seed['basis']['units']],
        'replay_units':len(frame['red_units'])+len(frame['blue_units']),
        'legacy_replay_units':len(legacy_frame['red_units'])+len(legacy_frame['blue_units']),
        'new_replay_version':frame['history_replay']['version'],
        'historical_profile_status':frame['history_replay']['roster_status'],
        'positioned_units':sum(u.get('lat') is not None and u.get('lng') is not None
                               for t in ('red','blue') for u in frame[t+'_units']),
        'replay_geo_references':len(frame['history_replay']['geo_references']),
        'teaching_template_units':sum(len(spec['initial_state'][s+'_units']) for s in ('red','blue')),
        'compatibility_seed_units':sum(len(v) for v in seed['configuration']['teams'].values()),
        'compatibility_seed_personnel':[u['personnel'] for v in seed['configuration']['teams'].values() for u in v],
        'compatibility_seed_equipment':[u['equipment'] for v in seed['configuration']['teams'].values() for u in v],
        'source_first_event':frame['current_time'],'template_start':spec['initial_state']['current_time'],
        'factual_readiness':readiness,'phase_identity_binding':phases,
        'verified_historical_initial_state':bool(readiness and readiness['ready_for_process_simulation']),
        'reasons':(readiness['missing'] if readiness else ['尚无历史单位初态档案'])+
                  ['历史参数化模型仍需逐场校准与验收','三种用途未端到端共享完整历史初态']})

result={'generated_at':datetime.now(timezone.utc).isoformat(),'method':'local source/factory audit; saved files read-only; no language-model calls',
    'installed_saved_sessions':saved,'catalog':rows,'catalog_count':len(rows),'catalog_mode_engine_combinations_theoretical':len(rows)*6,
    'inspection_scope':'Static source/replay/compatibility factories and saved-file inspection; not 270 live mode/engine executions. Shared synthetic launch requires a verified historical draft and is tested separately.',
    'summary':{'saved_files':len(saved),'initialized_files':sum(r['initialized'] for r in saved),
        'source_replays_without_units':sum(r['source_replay'] and not r['unit_count'] for r in saved),
        'uninitialized_files':sum(not r['initialized'] for r in saved),
        'reference_rows':sum(r['reference_rows'] for r in rows),
        'replay_zero_units':sum(r['replay_units']==0 for r in rows),
        'legacy_replay_zero_units':sum(r['legacy_replay_units']==0 for r in rows),
        'new_replay_nonempty_rosters':sum(r['replay_units']>0 for r in rows),
        'new_replay_roster_records':sum(r['replay_units'] for r in rows),
        'new_replay_positioned_units':sum(r['positioned_units'] for r in rows),
        'teaching_template_unit_counts':dict(Counter(r['teaching_template_units'] for r in rows)),
        'compatibility_seed_unit_counts':dict(Counter(r['compatibility_seed_units'] for r in rows)),
        'compatibility_seed_same_3000_each_side':sum(r['compatibility_seed_personnel']==[3000,3000] for r in rows),
        'verified_historical_initial_states':sum(r['verified_historical_initial_state'] for r in rows)},'native_imports':[]}

def save():
    (a.output/'audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
save()
if a.native_port:
    base=f'http://127.0.0.1:{a.native_port}'
    def call(path,data):
        req=urllib.request.Request(base+path,data=json.dumps(data,ensure_ascii=False).encode(),headers={'Content-Type':'application/json'},method='POST')
        with urllib.request.urlopen(req,timeout=120) as response:return json.load(response)
    for index,row in enumerate(rows,1):
        try:
            identity=call('/api/sessions',{'scenario':'只读审计的隔离副本；来源帧装载，不调用语言模型',
                'battle':row['battle'],'product_mode':'analysis','simulation_mode':'replay','execution_backend':'afsim','persist_roles':False})['session_id']
            snap=call('/api/sessions/'+identity+'/init',{})
            world=snap['war_state'];entry={'battle':row['battle'],'session_id':identity,'status':'completed',
                'unit_count':sum(len(world[t+'_units']) for t in ('red','blue')),
                'native_entity_count':world['afsim']['entity_count'],
                'geo_reference_count':len(world['history_replay']['geo_references']),
                'source':world['afsim']['source'],'model_skipped':world['afsim']['model_skipped']}
        except Exception as exc:entry={'battle':row['battle'],'status':'failed','error':str(exc)}
        result['native_imports'].append(entry);save()
        print('NATIVE',index,'/',len(rows),entry['status'],row['battle'],'units',entry.get('unit_count'),'entities',entry.get('native_entity_count'),flush=True)
for row in manifest:
    row['unchanged']=Path(row['path']).is_file() and hashlib.sha256(Path(row['path']).read_bytes()).hexdigest()==row['sha256']
result['original_files']=manifest;save()
print(json.dumps(result['summary'],ensure_ascii=False),flush=True)
if a.require_process_ready and any(not row['verified_historical_initial_state'] for row in rows):
    print('FAIL historical business acceptance: incomplete historical initial states remain; '
          'successful source frames or QA model scenarios do not satisfy this gate.',flush=True)
    raise SystemExit(1)
