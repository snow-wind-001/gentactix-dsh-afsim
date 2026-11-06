"""Isolated final-source API setup and cold checks; no default/user games.

Browser scripts execute the actual rounds. All numerical inputs are QA estimates.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
from tools.qa import force_task_execution_live as workflow

ROOT=Path('.cache/qa/turn-settlement-2026-11-01/http')
workflow.ROOT=ROOT;workflow.PORT=19118
call=workflow.call


def setup(engine,fire,*,label_tag=None,persist_roles=None):
    from tools.qa.campaign_lifecycle_fixture import inputs,NOTE
    tag=label_tag or ('fire' if fire else 'hold');folder=ROOT/('final-'+engine+'-'+tag);folder.mkdir(parents=True,exist_ok=True)
    path=folder/'case.json'
    if path.exists():raise SystemExit('Preserve the existing case; do not create a replacement silently')
    source,p=inputs()
    scenario='原生过程预览终验 '+engine+' '+tag+'；'+NOTE
    existing=[r for r in call('GET','/sessions')['sessions'] if r['scenario']==scenario]
    assert len(existing)<=1,'Do not silently choose between duplicate QA cases'
    created=({'session_id':existing[0]['session_id']} if existing else call('POST','/sessions',dict(scenario=scenario,
        battle=source['definition']['battle'],time_step='30分钟',product_mode='historical',simulation_mode='open',
        execution_backend=engine,agent_mode='native',persist_roles=persist_roles,historical_parameters=p,historical_initial_version='1.2.0')))
    base='/sessions/'+created['session_id'];initial=call('GET',base)
    if initial['war_state'] is None:initial=call('POST',base+'/init')
    assert initial['turn_count']==0 and not call('GET',base+'/progress')['active'],'Resume setup only before actual rounds'
    view=call('GET',base+'/commands')
    red=next(u for u in view['units'] if u['name']=='第159师');blue=next(u for u in view['units'] if u['team']=='blue')
    orders=[dict(unit_id=u['id'],action='hold',duration='until_turn',end_turn=3) for u in view['units']]
    if fire:
        for actor,target in ((red,blue),(blue,red)):
            order=next(o for o in orders if o['unit_id']==actor['id'])
            order.update(action='fire',target_id=target['id'],duration='next');order.pop('end_turn')
    call('PUT',base+'/commands',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version'],
        control_team='red',director=True,no_fire=False,unit_agents=[],orders=orders,
        intent=('双方已确认直接射击，其余四单位待命；按实际命令、资源和火力过程估计，不预设伤亡数。' if fire else
                '六个单位明确待命，无交战、侦察、运输或工程；分类耗用与粮食工作量分别记账。')))
    case=dict(session_id=created['session_id'],engine=engine,fire=fire,initial=initial,orders=orders)
    path.write_text(json.dumps(case,ensure_ascii=False,indent=2));print('Created',engine,tag,created['session_id'],flush=True)


def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def serve():
    """Add an observation-only QA marker; actual domain dispatch is unchanged."""
    folder=(ROOT/'api').resolve();folder.mkdir(parents=True,exist_ok=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:os.environ['GENTACTIX_'+key]=str(folder/suffix)
    from backend import main,harness_engine,runtime_bridge
    import uvicorn
    markers=ROOT/'preview-boundaries';markers.mkdir(exist_ok=True)
    def dispatch(context,payload):
        reply=main._native_tool_dispatch(context,payload)
        if payload.get('tool')=='preview_turn_effects' and reply.get('ok'):
            sid=context['session']['id'];target=markers/(sid+'.json');temporary=target.with_suffix('.tmp')
            temporary.write_text(json.dumps(dict(operation_id=reply['operation_id'],digest=reply['digest'],after_hash=reply['after_hash'],
                readonly=reply['readonly'],recorded_at=time.time(),evidence='actual_native_tool_bridge_callback')))
            temporary.replace(target)
        return reply
    runtime_bridge.register_dispatcher(dispatch)
    @main.app.get('/qa/preview-boundary/{session_id}')
    def preview_boundary(session_id:str):
        # Only existing QA sessions are addressable; this route observes a marker
        # and cannot execute a tool, mutate the world or manufacture a model reply.
        main._get(session_id)
        path=markers/(session_id+'.json')
        return dict(readonly=True,marker=json.loads(path.read_text()) if path.exists() else None)
    try:uvicorn.run(main.app,host='127.0.0.1',port=workflow.PORT,log_level='warning')
    finally:harness_engine.close_harness()


def cold(verify=False):
    path=ROOT/'final-cold-expected.json';rows={}
    for entry in call('GET','/sessions')['sessions']:
        sid=entry['session_id'];base='/sessions/'+sid
        assert not call('GET',base+'/progress')['active'],'Never restart an in-flight case'
        snapshot=call('GET',base)
        rows[sid]=dict(turn=snapshot['turn_count'],world_hash=digest(snapshot['war_state']),history_hash=digest(snapshot['history']),
            commands_hash=digest(call('GET',base+'/commands')),tasks_hash=digest(call('GET',base+'/force-organization/tasks')))
    if verify:
        assert rows==json.loads(path.read_text()),'Cold restore changed world, history, commands or tasks'
        (ROOT/'final-cold.json').write_text(json.dumps(dict(passed=True,cases=rows),ensure_ascii=False,indent=2))
        print('PASS cold restore',len(rows),'cases')
    else:
        if path.exists():raise SystemExit('Preserve the existing cold evidence')
        path.write_text(json.dumps(rows,ensure_ascii=False,indent=2));print('Saved idle cold checkpoints',len(rows))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['serve','setup','setup-cancel','prepare-cold','cold'])
    p.add_argument('--engine',choices=['narrative','afsim'],default='narrative');p.add_argument('--fire',action='store_true');a=p.parse_args()
    if a.mode=='serve':serve()
    elif a.mode=='setup':setup(a.engine,a.fire)
    elif a.mode=='setup-cancel':setup('narrative',False,label_tag='cancel',persist_roles=True)
    else:cold(a.mode=='cold')
