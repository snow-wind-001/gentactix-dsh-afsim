"""Normal isolated HTTP workflows for actual persistent-task backends and UI."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid

ROOT=Path('.cache/qa/force-task-execution-2026-10-31');PORT=19114


def call(method,path,value=None):
    request=urllib.request.Request(f'http://127.0.0.1:{PORT}/api'+path,method=method,
        headers={'Content-Type':'application/json'},data=json.dumps(value,ensure_ascii=False).encode() if value is not None else None)
    try:
        with urllib.request.urlopen(request,timeout=900) as response:return json.load(response)
    except urllib.error.HTTPError as exc:raise RuntimeError(str(exc.code)+' '+exc.read().decode()) from exc


def digest(world):return hashlib.sha256(json.dumps(world,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def revision(base):
    view=call('GET',base+'/force-organization')
    return dict(expected_turn=view['turn'],revision=view['command_revision'],world_version=view['world_version'],organization_revision=view['revision'])


def create(label,engine):
    from tools.qa.campaign_plan_fixture import inputs,NOTE
    source,parameters=inputs()
    created=call('POST','/sessions',dict(scenario='持续任务验收 '+label+'；'+NOTE,
        battle=source['definition']['battle'],time_step='30分钟',product_mode='historical',simulation_mode='open',execution_backend=engine,
        agent_mode='native',historical_parameters=parameters,historical_initial_version='1.2.0'))
    base='/sessions/'+created['session_id'];initial=call('POST',base+'/init')
    view=call('GET',base+'/commands');world=initial['war_state']
    names={u['name']:u['historical_unit_id'] for team in ('red','blue') for u in world[team+'_units']}
    ids={names[u['name']]:u['id'] for u in view['units']}
    assigned={ids['ww2.cn.division159'],ids['ww2.cn.division51']}
    call('PUT',base+'/commands',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version'],
        control_team='red',director=True,no_fire=False,intent='真实任务流程QA；其余单位明确待命，物理数值未历史标定。',
        orders=[dict(unit_id=u['id'],action='hold',duration='until_turn',end_turn=10) for u in view['units'] if u['id'] not in assigned]))
    groups={}
    for direction,key in [('north','ww2.cn.division159'),('south','ww2.cn.division51')]:
        view=call('POST',base+'/force-organization/detach',dict(**revision(base),unit_ids=[ids[key]],label='QA'+direction+'方向群',assumption='软件验收临时指挥；不是历史改隶'))
        groups[direction]=next(g['id'] for g in view['groups'] if g['label']=='QA'+direction+'方向群')
    points={n['id']:n['condition'].get('region',{}).get('center') for n in parameters['campaign_plan']['nodes']}
    return dict(session_id=created['session_id'],engine=engine,groups=groups,ids=ids,points=points,initial=call('GET',base))


def add(base,group,point,label,after=()):
    from verify_force_task_execution import execution
    value=dict(**revision(base),group_id=group,task=dict(kind='advance',destination=point),execution=execution(label,after=after))
    preview=call('POST',base+'/force-organization/task-preview',value)
    call('POST',base+'/force-organization/tasks',{**value,'preview_hash':preview['preview_hash']})
    return call('GET',base+'/force-organization/tasks')['rows'][-1]['id']


def advance(base):
    view=call('GET',base+'/commands')
    return call('POST',base+'/next',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version'],batch_id=uuid.uuid4().hex))


def run(engine,case_name=None):
    folder=ROOT/(engine if not case_name else engine+'-'+case_name);folder.mkdir(parents=True,exist_ok=True)
    if (folder/'result.json').exists():raise SystemExit('Evidence already exists; preserve rather than repeat or overwrite')
    case=create(case_name or engine,engine);base='/sessions/'+case['session_id']
    (folder/'initial.json').write_text(json.dumps(case,ensure_ascii=False,indent=2))
    first=add(base,case['groups']['north'],case['points']['north'],'先行方向')
    second=add(base,case['groups']['south'],case['points']['south'],'预备方向',[first])
    summary=dict(passed=False,session_id=case['session_id'],task_ids=[first,second],rounds=[],engine=engine)
    try:
        for turn in (1,2):
            print('Executing actual',engine,'task round',turn,flush=True);started=time.monotonic();snapshot=advance(base)
            (folder/('after-'+str(turn)+'.json')).write_text(json.dumps(snapshot,ensure_ascii=False,indent=2))
            tasks=call('GET',base+'/force-organization/tasks')
            (folder/('tasks-'+str(turn)+'.json')).write_text(json.dumps(tasks,ensure_ascii=False,indent=2))
            indexed={r['id']:r for r in tasks['rows']};world=snapshot['war_state']
            assert indexed[first]['status']=='completed'
            if turn==1:
                assert indexed[second]['status']=='preparing'
                assert world['mission']['status']=='active'
                south=next(u for u in world['red_units'] if u['historical_unit_id']=='ww2.cn.division51')
                original=next(u for u in case['initial']['war_state']['red_units'] if u['historical_unit_id']=='ww2.cn.division51')
                assert south['lat']==original['lat'] and south['lng']==original['lng']
            else:assert indexed[second]['status']=='completed' and world['mission']['winner']=='red'
            members=call('GET',base+'/force-organization/tasks?kind=members&task_id='+second)
            assert members['rows'][0]['executions']==(0 if turn==1 else 1)
            if engine=='afsim':assert world['afsim']['model_skipped']
            else:assert world['dsh_execution'] and not world.get('afsim')
            trace=call('GET',base+'/traces/'+str(turn))
            (folder/('trace-'+str(turn)+'.json')).write_text(json.dumps(trace,ensure_ascii=False,indent=2))
            assert trace['record']['force_task_execution']['changed_count']>=1
            summary['rounds'].append(dict(turn=turn,seconds=round(time.monotonic()-started,3),tasks={r['label']:r['status'] for r in tasks['rows']}))
            print('PASS',engine,'round',turn,'task states',summary['rounds'][-1]['tasks'],flush=True)
            if turn==1:
                # Completion releases command control. The operator deliberately
                # holds the completed north group while the reserve's dependency
                # release on the next round remains automatic.
                view=call('GET',base+'/commands');fields={'id','unit_id','action','duration','destination','target_id','air_pool','end_turn'}
                orders=[{k:v for k,v in o.items() if k in fields} for o in view['orders']]
                orders.append(dict(unit_id=case['ids']['ww2.cn.division159'],action='hold',duration='next'))
                call('PUT',base+'/commands',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version'],
                    control_team='red',director=True,no_fire=False,intent='已完成先行任务的北向部队明确保持阵地；预备队仍由原持续任务释放。',orders=orders))
        summary.update(passed=True,world_hash=digest(world),turn=2,actual_model=engine=='narrative',actual_afsim=engine=='afsim')
    finally:(folder/'result.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))


def serve():
    folder=(ROOT/'api').resolve();folder.mkdir(parents=True,exist_ok=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:os.environ['GENTACTIX_'+key]=str(folder/suffix)
    from backend import main,harness_engine
    import uvicorn
    try:uvicorn.run(main.app,host='127.0.0.1',port=PORT,log_level='warning')
    finally:harness_engine.close_harness()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['serve','setup-ui','native','dsh','cold']);parser.add_argument('--live',action='store_true');parser.add_argument('--name',default='前端');args=parser.parse_args()
    if args.mode=='serve':serve()
    elif args.mode=='setup-ui':
        path=ROOT/('ui-setup.json' if args.name=='前端' else 'ui-setup-'+args.name+'.json')
        if path.exists():raise SystemExit('UI QA already exists; preserve its state')
        case=create(args.name,'afsim');path.write_text(json.dumps(case,ensure_ascii=False,indent=2));print('UI QA',case['session_id'])
    elif args.mode in ('native','dsh'):
        if not args.live:parser.error('Actual execution requires --live')
        run('afsim' if args.mode=='native' else 'narrative',None if args.name=='前端' else args.name)
    else:
        cases=[json.loads(p.read_text()) for p in sorted(ROOT.glob('*/result.json')) if 'world_hash' in json.loads(p.read_text())]
        if (ROOT/'browser-result.json').exists():cases.append(json.loads((ROOT/'browser-result.json').read_text()))
        expected=json.loads((ROOT/'cold-expected.json').read_text()) if (ROOT/'cold-expected.json').exists() else {}
        for row in cases:
            snapshot=call('GET','/sessions/'+row['session_id']);assert digest(snapshot['war_state'])==row['world_hash']
            tasks=call('GET','/sessions/'+row['session_id']+'/force-organization/tasks');assert all(r['status'] in ('completed','cancelled') for r in tasks['rows'])
            if 'checks' in row:assert sum(r['status']=='cancelled' for r in tasks['rows'])==1 and len(tasks['rows'])==3
            if expected:assert digest(tasks)==expected[row['session_id']]['task_observation_hash']
        (ROOT/'cold.json').write_text(json.dumps(dict(passed=True,cases=cases,exact_task_observations_checked=bool(expected)),ensure_ascii=False,indent=2));print('PASS cold restored',len(cases),'task worlds')
