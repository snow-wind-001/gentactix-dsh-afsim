"""Run/resume the full 57-turn Cheqiao window with real DSH and native AFSIM.

All checkpoints live under --root. A failed turn stops; resume starts from the
last committed checkpoint. Historical plausibility is reported separately from
software invariants, never enforced with casualty quotas or a fixed winner.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import uuid
from unittest.mock import patch


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--live',action='store_true');p.add_argument('--resume',action='store_true')
    p.add_argument('--root',type=Path,required=True);p.add_argument('--basis',type=Path,required=True)
    p.add_argument('--parameters',type=Path,required=True);p.add_argument('--config',type=Path,required=True)
    args=p.parse_args()
    if not args.live:p.error('Explicit --live required')
    root=args.root.resolve()
    if root.exists() and not args.resume:p.error('Existing run directory: inspect its process before using --resume')
    root.mkdir(parents=True,exist_ok=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                       ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(root/suffix)
    os.environ['GENTACTIX_LLM_CONFIG']=str(args.config.resolve())
    from fastapi.testclient import TestClient
    from backend import main as api,harness_engine as h,runtime_bridge,session_store
    from gentactix import historical_operations,missions,campaign,commands,sim_clock
    inputs={str(x.resolve()):hashlib.sha256(x.read_bytes()).hexdigest() for x in (args.basis,args.parameters,args.config)}

    def write(name,value):
        target=root/name;temp=target.with_suffix(target.suffix+'.tmp')
        temp.write_text(json.dumps(value,ensure_ascii=False,indent=2));temp.replace(target)

    basis=json.loads(args.basis.read_text());params=json.loads(args.parameters.read_text())
    definition=historical_operations.definition(basis['initial'],params)
    assert params['goal']['deadline_turn']==57 and params['clock']['time_step']=='30分钟'
    assert basis['initial']['version']=='1.3.0'
    h.enable_afsim_runtime();runtime_bridge.register_dispatcher(api._native_tool_dispatch)
    client=TestClient(api.app)
    code_hash={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for folder in ('backend','gentactix') for f in Path(folder).glob('*.py')}
    generation=str(time.time_ns());write('code-'+generation+'.json',code_hash)
    if args.resume:
        sid=(root/'session-id.txt').read_text();sessions,errors=session_store.load_all()
        if errors:raise ValueError(errors)
        session=sessions[sid];api._SESSIONS[sid]=session
        result=json.loads((root/'result.json').read_text())
        assert result['inputs']==inputs,'Inputs changed: do not silently resume a different scenario'
        result.pop('error',None)  # Previous failures remain in archived evidence.
    else:
        scenario=('车桥1944年3月5日01:50至6日06:20完整核心窗口：历史条件开放推演。'
            '具名部队与事件参考来自冻结1.3.0档案，缺载兵力、装备、局部部署、工事效能与目标阈值均为显式估计。'
            'DSH规划双方；AFSIM生成位置、交战与人员装备补给结果。历史过程用于解释与约束输入，不预制伤亡、投降或胜负。')
        session=api._new_session(scenario,params['clock']['time_step'],True,definition['battle'],True,False)
        session.update(scenario_input=scenario,mission_id=definition['id'],historical_definition=definition,
            product_mode='historical',simulation_mode='open',execution_backend='afsim')
        sid=session['id'];api._SESSIONS[sid]=session;session_store.save(session)
        (root/'session-id.txt').write_text(sid)
        result={'scope':'57-turn historical-conditions open simulation; effects not historically calibrated',
            'inputs':inputs,'session_id':sid,'turns':[],'passed':False,'artillery_hold_through':15,
            'control_assumption':'来源09时炮兵抵近支援；01:50起30分钟网格无09:00边界，本测试明确选择准备至09:20（T+15结束），不是精确史实时刻。'}
    path='/api/sessions/'+sid
    status={'pid':os.getpid(),'generation':generation,'state':'initializing','session_id':sid,'committed_turn':session['turn_count']}
    stopped=threading.Event()

    def monitor():
        while not stopped.wait(5):
            try:
                current=api._SESSIONS[sid]
                write('status.json',{**status,'checked_at':time.time(),'committed_turn':current['turn_count'],
                    'progress':api.get_progress(sid)})
            except Exception:pass  # Monitoring must not alter or interrupt a turn.

    watcher=threading.Thread(target=monitor,daemon=True);watcher.start()
    def view():return client.get(path+'/commands').json()
    def revision(v):return {'expected_turn':v['turn'],'revision':v['revision'],'world_version':v['world_version']}
    try:
        policy=h.role_policy('engine');assert policy['reasoning_effort']=='high' and policy['max_tokens']==65536
        if not args.resume:
            response=client.post(path+'/init');write('initialization.json',response.json())
            assert response.status_code==200,response.text
            initial=response.json()['war_state'];assert initial['afsim']['returncode']==0
            assert initial['afsim']['entity_count']==19
            v=view();gun=next(u for u in v['units'] if u['type']=='炮兵')
            request={**revision(v),'control_team':'red','director':False,'no_fire':False,
                'orders':[{'unit_id':gun['id'],'action':'recon','duration':'until_turn','end_turn':15}],
                'intent':('本次测试炮兵明确准备至T+15结束（09:20），用侦察保持情报，之后交还规划器。'
                    '其余单位由DSH控制双方全部可用实体：镇内两路突击、芦家滩西北阻援、南侧警戒、北侧策应及预备队职责保持区分。'
                    '蓝方自主防御、补给、必要撤退或协同援军，不漏交命令。入场和启程以当前结构化campaign为准，未解锁不提前行动，解锁后不自动接敌。'
                    '逐轮观察AFSIM位置、射程、粮弹、工事与人员账，按需试算；无必要移动时可明确待命。'
                    '围绕联合目标决定接敌、阻援及资源分配，不能把历史战果当作必须生成的结果，也不能让所有部队集中到镇中心。')}
            response=client.put(path+'/commands',json=request);assert response.status_code==200,response.text
            result['artillery_id']=gun['id'];result['artillery_name']=gun['name']
            result['initial_native']=initial['afsim'];write('result.json',result)
            print('PASS full 19-entity initialization API/native load; explicit preparation through T+15',flush=True)
        while api._SESSIONS[sid]['turn_count']<57:
            session=api._SESSIONS[sid];before=copy.deepcopy(session['war_state']);turn=session['turn_count']+1
            if before['mission']['status']=='completed':break
            status.update(state='running',requested_turn=turn,request_started_at=time.time())
            v=view();request={**revision(v),'batch_id':uuid.uuid4().hex}
            write(f'turn-{turn:02d}-request.json',{'generation':generation,**request})
            with patch.object(missions,'advance',side_effect=AssertionError('Python combat fallback forbidden')):
                response=client.post(path+'/next',json=request)
            snap=response.json();write(f'turn-{turn:02d}-response.json',snap)
            assert response.status_code==200,response.text
            after=snap['war_state'];native=after['afsim'];missions.validate(after)
            assert after['current_time']==sim_clock.target(before,session['time_step'])[0]
            assert after['mission']['turn']==turn and snap['turn_count']==turn
            assert native['returncode']==0 and native['entity_count']==19
            assert native['supply_control_revision']==1
            assert [(t,u['name']) for t,u in missions.units(before)]==[(t,u['name']) for t,u in missions.units(after)]
            receipts=client.get(path+f'/unit-decisions?start_turn={turn}&end_turn={turn}').json()['items']
            write(f'turn-{turn:02d}-receipts.json',receipts)
            assert len(receipts)==19 and len({r['unit_id'] for r in receipts})==19
            old_by_name={u['name']:u for _,u in missions.units(before)}
            for team,u in missions.units(after):
                old=old_by_name[u['name']];p=u['personnel'];execution=u['formation']['last_execution']
                assert p['current']+p['casualties']+p['noncombat_losses']==p['committed']==old['personnel']['committed']
                for equipment in u['equipment']:
                    assert equipment['operational']+equipment['damaged']+equipment['destroyed']==equipment['committed']
                # Legacy `shots` means direct-fire cycles for fire, but actual
                # shells for bombard/suppress. Never subtract rifle cycles from
                # the independent artillery shell inventory.
                spent=execution['shots'] if execution['action'] in ('bombard','suppress') else 0
                assert u['formation']['shells']==old['formation']['shells']+execution['received_shells']-spent, (u['name'],'shell ledger')
                if campaign.release_seconds(after,u)>0:
                    assert not after['campaign']['actors'][u['name']]['active']
                    assert (u['lat'],u['lng'])==(old['lat'],old['lng']) and execution['shots']==0
                if turn<=15 and u['name']==result['artillery_name']:
                    assert execution['shots']==0,'Confirmed preparation order fired before deadline'
            objective=campaign.assess(after)
            assert objective==after['campaign']['objective'],'Native objective and read-only review disagree'
            replay=client.post(path+'/next',json=request)
            assert replay.status_code==200 and replay.json()['command_result']['replayed']
            restored,errors=session_store.load_all();assert not errors,errors
            assert restored[sid]['war_state']==after;api._SESSIONS[sid]=restored[sid]
            row={'turn':turn,'time':after['current_time'],'native_artifact':native['artifact'],
                'native_ms':native['wall_ms'],'engine_ms':snap.get('engine_meta',{}).get('elapsed_ms'),
                'decisions':len(receipts),'blue_actions':[r['action'] for r in receipts if r['team']=='blue'],
                'staged':[u['name'] for _,u in missions.units(after) if not after['campaign']['actors'][u['name']]['active']],
                'losses':{team:{key:sum(u['personnel'].get(key,0) for u in after[team+'_units'])
                    for key in ('current','casualties','killed','wounded','captured','noncombat_losses')} for team in ('red','blue')},
                'objective':objective,'mission_status':after['mission']['status'],'winner':after['mission']['winner'],
                'rag_injected':snap.get('rag',{}).get('last',{}).get('injected'),
                'supply_statuses':[r['supply_status'] for r in after['mission']['ledger']]}
            result['turns']=[r for r in result['turns'] if r['turn']<turn]+[row];write('result.json',result)
            print(json.dumps(row,ensure_ascii=False),flush=True)
        final=api._SESSIONS[sid]['war_state']
        result['final_time']=final['current_time'];result['final_turn']=final['mission']['turn']
        result['full_window_reached']=final['mission']['turn']==57
        result['software_checks_passed']=True
        result['passed']=final['mission']['status']=='completed' and result['full_window_reached']
        result['termination_reason']='deadline' if result['full_window_reached'] else 'early_mission_end'
        result['historical_fit_verified']=False
        assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest for path,digest in inputs.items())
        status['state']='completed'
    except BaseException as exc:
        status.update(state='cancelled' if isinstance(exc,KeyboardInterrupt) else 'failed',error=f'{type(exc).__name__}: {str(exc)[:1200]}')
        result.update(passed=False,error=status['error']);raise
    finally:
        stopped.set();watcher.join(timeout=6)
        status['committed_turn']=api._SESSIONS[sid]['turn_count'];status['checked_at']=time.time()
        write('status.json',status);write('result.json',result);h.close_harness()
        print(root,flush=True)


if __name__=='__main__':main()
