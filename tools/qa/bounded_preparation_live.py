"""Isolated real DSH/API/AFSIM acceptance for a bounded human preparation order.

Reuses an explicitly supplied, previously generated historical configuration.
Does not generate new history, alter existing games, or calibrate combat effects.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import time
import uuid
from unittest.mock import patch


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--basis',type=Path,required=True)
    parser.add_argument('--parameters',type=Path,required=True)
    parser.add_argument('--config',type=Path,required=True)
    args=parser.parse_args()
    if not args.live:parser.error('Explicit --live required')
    root=Path('.cache/qa/bounded-preparation-2026-10-29')/str(time.time_ns())
    root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                       ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    os.environ['GENTACTIX_LLM_CONFIG']=str(args.config.resolve())
    from fastapi.testclient import TestClient
    from backend import main as api,session_store,afsim_state,harness_engine as h,runtime_bridge
    from gentactix import commands,historical_operations,missions
    sources={str(p):p.read_bytes() for p in (args.basis,args.parameters,args.config)}
    basis=json.loads(args.basis.read_text());parameters=json.loads(args.parameters.read_text())
    world=historical_operations.initial(basis['initial'],parameters)
    session=api._new_session('车桥历史条件持续准备命令验收','30分钟',False,world['mission']['definition']['battle'],False,False)
    session.update(scenario_input='车桥历史条件开放推演；缺载数值与部署为未标定估计，不能预定历史战果。',
                   war_state=world,mission_id=world['mission']['id'],turn_count=0,
                   execution_backend='afsim',simulation_mode='open',product_mode='historical',
                   historical_definition=copy.deepcopy(world['mission']['definition']))
    session_store.validate(session);session_store.save(session)
    api._SESSIONS[session['id']]=session
    client=TestClient(api.app);path='/api/sessions/'+session['id'];tools=[]
    result={'passed':False,'session_id':session['id'],'scope':'three real-model turns; not historical calibration','turns':[]}

    def write(name,value):
        (root/name).write_text(json.dumps(value,ensure_ascii=False,indent=2))

    def dispatch(context,payload):
        response=api._native_tool_dispatch(context,payload)
        tools.append({'tool':payload.get('tool'),'args':payload.get('args'),'ok':response.get('ok')})
        return response

    def get_view():return client.get(path+'/commands').json()

    def revision(view):return {'expected_turn':view['turn'],'revision':view['revision'],'world_version':view['world_version']}

    runtime_bridge.register_dispatcher(dispatch)
    try:
        h.enable_afsim_runtime()
        assert h.role_policy('engine')['reasoning_effort']=='high'
        assert h.role_policy('engine')['max_tokens']==65536
        initial=copy.deepcopy(world);view=get_view()
        artillery=next(u for u in view['units'] if u['type']=='炮兵')
        start=client.get(path).json();write('start.json',start)
        response=client.post(path+'/commands/resolve',json={**revision(view),'selected_units':[artillery['id']],
            'text':'此炮兵单位待命两回合，之后交回规划器。只约束选中炮兵，不改变全军禁止射击设置，不对其他部队下令。'})
        write('natural-proposal.json',response.json());assert response.status_code==200,response.text
        proposal=response.json();assert proposal['status']=='draft',proposal
        assert len(proposal['orders'])==1 and proposal['orders'][0]['duration']=='until_turn'
        assert proposal['orders'][0]['end_turn']==2 and proposal['orders'][0]['action']=='hold'
        assert not get_view()['orders'] and api._SESSIONS[session['id']]['war_state']==initial
        response=client.put(path+'/commands',json={**revision(get_view()),'orders':proposal['orders'],
            'proposal_id':proposal['id'],'control_team':'red','director':False,'no_fire':False,
            'intent':'维持历史条件开放推演：明确炮兵准备命令优先，其他单位根据当前态势自主行动。不得预定胜负或历史伤亡。'})
        assert response.status_code==200,response.text
        command_id=response.json()['orders'][0]['id']
        write('queued-session.json',session_store.serializable(api._SESSIONS[session['id']]))
        print('PASS real DSH proposed two-turn hold; API confirmed without changing world',flush=True)
        for turn in (1,2,3):
            before=copy.deepcopy(api._SESSIONS[session['id']]['war_state']);view=get_view()
            request={**revision(view),'batch_id':uuid.uuid4().hex}
            with patch.object(missions,'advance',side_effect=AssertionError('No Python combat fallback')):
                response=client.post(path+'/next',json=request)
            write(f'turn-{turn}-response.json',response.json())
            assert response.status_code==200,response.text
            snap=response.json();after=snap['war_state'];native=after['afsim'];view=get_view()
            receipts=client.get(path+f'/unit-decisions?start_turn={turn}&end_turn={turn}').json()['items']
            write(f'turn-{turn}-receipts.json',receipts)
            assert native['returncode']==0 and native['model_skipped'] is False
            assert snap['turn_count']==turn and after['mission']['turn']==turn
            assert [(t,u['name']) for t,u in missions.units(before)]==[(t,u['name']) for t,u in missions.units(after)]
            gun=next(u for u in after['red_units'] if u['name']==artillery['name'])
            old=next(u for u in before['red_units'] if u['name']==artillery['name'])
            execution=gun['formation']['last_execution']
            receipt=next(r for r in receipts if r['unit_id']==artillery['id'])
            assert gun['formation']['shells']==old['formation']['shells']+execution['received_shells']-execution['shots']
            if turn<=2:
                assert receipt['source']=='human' and receipt['command_id']==command_id
                assert receipt['status']==('executing' if turn==1 else 'completed')
                assert execution['shots']==0 and execution['command_done']==1
                assert len(view['orders'])==(1 if turn==1 else 0)
            else:
                assert receipt['source']=='model_batch' and receipt['command_id'] is None
                assert receipt['rationale'] and not view['orders']
            # Replay a completed batch and reload the durable checkpoint each round.
            replay=client.post(path+'/next',json=request)
            assert replay.status_code==200 and replay.json()['command_result']['replayed']
            restored,errors=session_store.load_all();assert not errors,errors
            api._SESSIONS[session['id']]=restored[session['id']]
            assert restored[session['id']]['war_state']==after
            result['turns'].append({'turn':turn,'time':after['current_time'],'source':receipt['source'],
                'command_status':receipt['status'],'action':receipt['action'],'execution':execution,
                'native':{k:native[k] for k in ('artifact','returncode','entity_count','wall_ms')}})
            write('result.json',result)
            print(f'PASS T+{turn} native, source={receipt["source"]}, action={receipt["action"]}, status={receipt["status"]}, checkpoint/retry',flush=True)
        observed=api._SESSIONS[session['id']];frozen=copy.deepcopy(observed)
        observer=h.RunObserver('准备任务到期后原生态势只读分析')
        answer=h._run_brain('仅做只读验收。通过get_afsim_observation工具读取当前炮兵单位'+artillery['name']+
            '的原生执行回执。只返回JSON {"unit":"单位名","turn":当前回合,"shots":本轮原生发射数,"action":"本轮原生动作","time":"当前模拟时间"}。不要发起试算或下令。',
            None,observer=observer,role='chat',native_context=afsim_state.operation_context(observed))
        parsed=h.parse_json_object(answer.final_response);write('dsh-observation.json',parsed)
        assert parsed['unit']==artillery['name'] and parsed['turn']==3
        assert parsed['shots']==execution['shots'] and parsed['action']==execution['action']
        assert parsed['time']==observed['war_state']['current_time'] and observed==frozen
        assert any(t['tool']=='get_afsim_observation' for t in tools)
        assert all(Path(p).read_bytes()==content for p,content in sources.items())
        result.update(passed=True,observation=parsed,original_sources_unchanged=True)
        print('PASS real DSH read final native artillery telemetry; originals unchanged',flush=True)
    finally:
        h.close_harness();write('result.json',result);write('tool-calls.json',tools)
        Path('.cache/qa/bounded-preparation-2026-10-29/latest.txt').write_text(str(root))
        print(root,flush=True)


if __name__=='__main__':main()
