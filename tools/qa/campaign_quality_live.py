"""Isolated real resource/narrative QA; requires explicit --live for model use."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import urllib.error
import urllib.request
import uuid

ROOT = Path('.cache/qa/campaign-quality-2026-10-31')
PORT = 19110


def call(method, path, data=None):
    request = urllib.request.Request(f'http://127.0.0.1:{PORT}/api'+path, method=method,
        headers={'Content-Type': 'application/json'},
        data=json.dumps(data, ensure_ascii=False).encode() if data is not None else None)
    try:
        with urllib.request.urlopen(request, timeout=900) as response: return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(str(exc.code)+' '+exc.read().decode()) from exc


def digest(world):
    return hashlib.sha256(json.dumps(world, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def serve():
    root = (ROOT/'api').resolve(); root.mkdir(parents=True, exist_ok=True)
    for key, suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                        ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key] = str(root/suffix)
    from backend import main, harness_engine
    import uvicorn
    try: uvicorn.run(main.app, host='127.0.0.1', port=PORT, log_level='warning')
    finally: harness_engine.close_harness()


def live():
    from tools.qa.campaign_plan_fixture import inputs, NOTE
    from gentactix import missions, reporting
    ROOT.mkdir(parents=True, exist_ok=True)
    result = {'passed': False, 'scope': NOTE, 'cases': []}
    try:
        for engine, count in [('narrative',3), ('afsim',1)]:
            folder=ROOT/engine;folder.mkdir(exist_ok=True)
            if not (folder/'initial.json').exists():
                source, parameters = inputs()
                created = call('POST','/sessions',dict(scenario='补给与讲解真实验收 '+engine+'；'+NOTE,
                    battle=source['definition']['battle'],time_step='30分钟',product_mode='historical',simulation_mode='open',
                    execution_backend=engine,agent_mode='native',historical_parameters=parameters,historical_initial_version='1.2.0'))
                current=call('POST','/sessions/'+created['session_id']+'/init')
                (folder/'initial.json').write_text(json.dumps(current,ensure_ascii=False,indent=2))
            else:
                created=json.loads((folder/'initial.json').read_text());current=call('GET','/sessions/'+created['session_id'])
            base='/sessions/'+current['session_id']; samples=[]
            while current['turn_count'] < count:
                view=call('GET',base+'/commands')
                call('PUT',base+'/commands',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version'],
                    control_team='red',director=True,no_fire=False,intent='双方所有部队本轮待命。战报逐单位使用全名，保留投入部限定，以具名目标和中文状态区分物理条件及前置目标；不补造交战。',
                    orders=[dict(unit_id=u['id'],action='hold',duration='next') for u in view['units']]))
                view=call('GET',base+'/commands')
                print('Executing real',engine,'round',current['turn_count']+1,flush=True)
                current=call('POST',base+'/next',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version'],batch_id=uuid.uuid4().hex))
                (folder/('after-'+str(current['turn_count'])+'.json')).write_text(json.dumps(current,ensure_ascii=False,indent=2))
                world=current['war_state']
                for _,unit in missions.units(world):
                    assert unit['supply']==min(unit['logistics']['food'],unit['logistics']['ammo'])
                    if engine=='narrative':assert unit['logistics']['food']==80-2*current['turn_count']
                assert world['mission']['status']=='active' and not world['engagements']
                assert (engine=='narrative') == ('dsh_execution' in world)
                assert (engine=='afsim') == ('afsim' in world)
                facts=current['history'][0]
                assert '第161师万家岭投入部' in facts and '当前条件成立；前置目标尚未达成' in facts
                assert 'waiting_dependency' not in facts and '五个步兵师' not in facts
                samples.append(dict(turn=current['turn_count'],food=world['red_units'][0]['logistics']['food'],
                    supply=world['red_units'][0]['supply'],prose_fallback='冲突内容未作为战报事实展示' in facts))
                print('PASS real',engine,'round',current['turn_count'],'food/index=',samples[-1]['food'],samples[-1]['supply'],flush=True)
            result['cases'].append(dict(engine=engine,session_id=current['session_id'],turn=current['turn_count'],
                world_hash=digest(current['war_state']),samples=samples,actual_model=engine=='narrative',actual_afsim=engine=='afsim'))
        result['passed']=True
    finally:
        (ROOT/'live-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))


def cold():
    result=json.loads((ROOT/'live-result.json').read_text())
    cases=list(result['cases'])
    fresh=ROOT/'fresh-first/result.json'
    if fresh.exists():
        row=json.loads(fresh.read_text());cases.append({k:row[k] for k in ('session_id','turn','world_hash')})
    for row in cases:
        snapshot=call('GET','/sessions/'+row['session_id'])
        assert snapshot['turn_count']==row['turn'] and digest(snapshot['war_state'])==row['world_hash']
    (ROOT/'cold-result.json').write_text(json.dumps(dict(passed=True,cases=cases),ensure_ascii=False,indent=2))
    print('PASS',len(cases),'unchanged cold-restored resource/narrative QA worlds')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    for name in ('serve','live','cold'):group.add_argument('--'+name,action='store_true')
    args=parser.parse_args()
    if args.serve:serve()
    elif args.live:live()
    else:cold()
