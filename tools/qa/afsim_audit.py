"""Isolated real AFSIM tests: rule families, movers, continuation and command controls.

Default execution does not call a model. --live also exercises real natural-language
commands, native unit Agents and fresh-state chat/review; it consumes model tokens.
Initial deployments are versioned teaching states or explicitly synthetic fixtures.
"""
from pathlib import Path
import argparse
import copy
import json
import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--profile', choices=['delay','assault','breakout','rail','underground','air','reception','cancel'], help='Retest one profile or cancellation')
    parser.add_argument('--out', type=Path, default=ROOT / '.cache/qa/afsim-audit-20261027/runtime')
    args = parser.parse_args(); output = args.out.resolve(); output.mkdir(parents=True, exist_ok=True)
    os.environ.update(GENTACTIX_SESSION_DIR=str(output/'sessions'), GENTACTIX_TRACE_DIR=str(output/'traces'),
        GENTACTIX_DSH_HOME=str(output/'dsh-home'), GENTACTIX_DSH_WORKSPACE=str(output/'dsh-workspace'),
        GENTACTIX_ROLE_INDEX=str(output/'roles.json'), GENTACTIX_DSH_PATCHES='[]')
    from backend import main as api, harness_engine as h, afsim_world, session_store
    from gentactix import missions, commands, unit_types
    from fastapi.testclient import TestClient
    client = TestClient(api.app); results=[]

    def call(method, path, body=None):
        r = client.request(method, path, json=body)
        if r.status_code != 200: raise RuntimeError(f'{method} {path}: {r.status_code}: {r.text[:1000]}')
        return r.json()

    def revision(view):
        return {key:view[source] for key, source in (('expected_turn','turn'),('revision','revision'),('world_version','world_version'))}

    def step(sid, orders, batch):
        view=call('GET',f'/api/sessions/{sid}/commands')
        view=call('PUT',f'/api/sessions/{sid}/commands',{**revision(view),'orders':orders,'director':True})
        with patch.object(h,'get_ai_response',side_effect=AssertionError('complete manual batch called model')):
            return call('POST',f'/api/sessions/{sid}/next',{**revision(view),'batch_id':batch})

    def case(name, function):
        start=time.monotonic()
        try:
            detail=function(); result={'case':name,'passed':True,'seconds':round(time.monotonic()-start,3),**(detail or {})}
        except Exception as exc:
            result={'case':name,'passed':False,'error':str(exc)[:1700]}
        results.append(result); print(json.dumps(result,ensure_ascii=False),flush=True)
        (output/'results.json').write_text(json.dumps({'live_model':args.live,'cases':results},ensure_ascii=False,indent=2))

    def rule_case(spec):
        sid=call('POST','/api/sessions',{'scenario':spec['battle']+'；固定局部规则验收',
            'mission_id':spec['id'],'execution_backend':'afsim','persist_roles':False})['session_id']
        snap=call('POST',f'/api/sessions/{sid}/init'); turns=0; actions=set()
        while snap['war_state']['mission']['status']!='completed':
            before=copy.deepcopy(snap['war_state']); view=call('GET',f'/api/sessions/{sid}/commands'); orders=[]
            for unit in view['units']:
                if not unit['available']: continue
                action='hold'; draft={'unit_id':unit['id'],'duration':'next'}
                enemy=next((v for v in view['units'] if v['team']!=unit['team'] and v['available']),None)
                first=unit['name'].endswith('1')
                if turns==0 and first:
                    action='move'; draft['destination']=commands.towards(unit['position'],before['mission']['definition']['objective'],min(.5,unit['capabilities']['move_km']))
                elif turns==1 and first and enemy and commands.distance(unit['position'],enemy['position'])*1000<=unit['attack_range']:
                    action='fire'; draft['target_id']=enemy['id']
                elif turns>=2 and first:
                    supported=unit['capabilities']['actions']
                    if 'sabotage' in supported: action='sabotage' if unit['team']=='red' else 'repair'
                    elif 'accept' in supported: action='accept'
                    elif 'conceal' in supported: action='conceal'
                    # Targeted aviation has a separate real-engine acceptance
                    # suite; the legacy oracle must not execute native flights.
                    elif 'air_support' in supported: action='hold'
                elif turns==1 and unit['name'].endswith('2'): action='resupply'
                draft['action']=action; actions.add(action); orders.append(draft)
            with patch.object(missions,'advance',side_effect=AssertionError('Python teaching executor was used in production AFSIM turn')):
                snap=step(sid,orders,'rules-'+str(turns))
            turns+=1
            after=snap['war_state']; missions.validate(after)
            assert snap['afsim']['source']=='dsh_native_mcp_controller' and snap['afsim']['model_skipped']
            assert after['simulation_clock']['elapsed_seconds']==turns*1800
            for team in ('red_units','blue_units'):
                assert len(before[team])==len(after[team])
                for unit in after[team]:
                    p=unit['personnel']; assert p['committed']==p['current']+p['casualties']+p['noncombat_losses']
            assert all(row['ammo_spent']==(3 if row['action'] in ('fire','air_support') else 0) for row in after['mission']['ledger'])
            by_name={unit['name']:unit for _,unit in missions.units(after)}
            replay=[{**order,**({key:by_name[order['unit']][key] for key in ('lat','lng')}
                if order['action']=='move' else {})} for order in after['afsim']['orders']]
            expected=missions.advance(before,replay,spec['time_step'])
            for key in ('ledger','metrics','progress','network','organization','accepted','status','winner'):
                assert after['mission'][key]==expected['mission'][key], (spec['profile'],turns,key,after['mission'][key],expected['mission'][key])
            for (_,actual),(_,reference) in zip(missions.units(after),missions.units(expected)):
                for key in ('current','casualties','noncombat_losses'): assert actual['personnel'][key]==reference['personnel'][key]
                for key in ('operational','destroyed','damaged'): assert actual['equipment'][0][key]==reference['equipment'][0][key]
                assert actual['logistics']==reference['logistics']
            assert [d['stock'] for d in after['supply_nodes']]==[d['stock'] for d in expected['supply_nodes']]
            if turns>4: raise AssertionError('deadline did not settle')
        return {'profile':spec['profile'],'turns':turns,'actions':sorted(actions),'status':snap['war_state']['mission']['status'],
            'native_rules_parity':True,'python_production_executor_calls':0}

    def mover_case():
        units=[{'name':p['id'],'type':p['label'],'lat':30+i*.003,'lng':120,'hp':100} for i,p in enumerate(unit_types.UNIT_PROFILES)]
        before={'red_units':units,'blue_units':[],'engagements':[]}
        scene=afsim_world.compile_scene(before,[],900)
        positions,evidence=afsim_world.run_scene({},scene)
        assert len(positions)==len(units)
        # Explicitly verify the native mover types, independently of the host's
        # ground-only capability policy. This remains an uncalibrated 2D test.
        orders=[{'unit':u['name'],'action':'move','lat':u['lat']+.0005,'lng':u['lng']} for u in units]
        scene=afsim_world.compile_scene(before,orders,900)
        positions,evidence=afsim_world.run_scene({},scene)
        return {'loaded_types':len(units),'moved_types':len(positions),'scope':evidence['scope']}

    def continuation_case():
        fixture={'current_time':'1935-05-29 06:00','current_terrain':'丘陵森林','engagements':[],
            'center':[29.91,102.23], 'red_units':[{'name':'连续移动红方','type':'步兵','lat':29.91,'lng':102.23,'hp':100}],
            'blue_units':[{'name':'待命蓝方','type':'步兵','lat':29.94,'lng':102.24,'hp':100}]}
        sid=call('POST','/api/sessions',{'scenario':'完全合成连续移动与恢复验收','time_step':'15分钟','execution_backend':'afsim','persist_roles':False})['session_id']
        with patch.object(h,'get_ai_response_with_retry',return_value=fixture): call('POST',f'/api/sessions/{sid}/init')
        view=call('GET',f'/api/sessions/{sid}/commands'); first=view['units'][0]
        goal=commands.towards(first['position'],{'lat':29.95,'lng':102.23},first['capabilities']['move_km']*2.4)
        view=call('PUT',f'/api/sessions/{sid}/commands',{**revision(view),'director':True,'orders':[
            {'unit_id':first['id'],'action':'move','destination':goal,'duration':'until_arrived'},
            {'unit_id':view['units'][1]['id'],'action':'hold','duration':'next'}]})
        identities=[u['id'] for u in view['units']]; positions=[]
        for turn in range(3):
            if turn:
                # Restore from serialized disk state, not from a model's memory.
                restored,errors=session_store.load_all(); assert not errors
                api._SESSIONS[sid]=restored[sid]
                view=call('GET',f'/api/sessions/{sid}/commands')
            with patch.object(h,'get_ai_response',return_value={'orders':[]}):
                snap=call('POST',f'/api/sessions/{sid}/next',{**revision(view),'batch_id':'continuous-'+str(turn)})
            positions.append(commands.known_position(snap['war_state']['red_units'][0]))
            assert snap['turn_count']==turn+1 and snap['war_state']['simulation_clock']['elapsed_seconds']==900*(turn+1)
            assert [u['id'] for u in call('GET',f'/api/sessions/{sid}/commands')['units']]==identities
        assert commands.distance(positions[-1],goal)<.01
        return {'turns':3,'checkpoint_restores':2,'arrived':True,'stable_ids':True}

    def live_case():
        sid=call('POST','/api/sessions',{'scenario':'AFSIM控制链真实模型验收；合成局部演习','mission_id':'AJ15-local-v1',
            'execution_backend':'afsim','persist_roles':True})['session_id']
        initial=call('POST',f'/api/sessions/{sid}/init'); view=call('GET',f'/api/sessions/{sid}/commands')
        first=view['units'][0]; target=commands.towards(first['position'],{'lat':first['position']['lat'],'lng':first['position']['lng']+.01},.1)
        proposal=call('POST',f'/api/sessions/{sid}/commands/resolve',{**revision(view),
            'selected_units':[first['id']],'map_target':target,'text':'仅当前单位移动到地图选定位置，本轮执行。'})
        assert proposal['status']=='draft' and len(proposal['orders'])==1
        assert call('GET',f'/api/sessions/{sid}')['war_state']==initial['war_state']
        drafts=[{k:v for k,v in order.items() if k in ('unit_id','action','destination','duration','target_id')} for order in proposal['orders']]
        view=call('PUT',f'/api/sessions/{sid}/commands',{**revision(view),'orders':drafts,'proposal_id':proposal['id'],
            'unit_agents':[view['units'][1]['id']]})
        first_snap=call('POST',f'/api/sessions/{sid}/next',{**revision(view),'batch_id':'live-human-agent',
            'instruction':'除已确认人工移动和独立Agent之外，其余单位待命，不主动射击。'})
        assert commands.distance(commands.known_position(first_snap['war_state']['red_units'][0]),target)<.01
        receipts=call('GET',f'/api/sessions/{sid}/unit-decisions')['items']
        assert any(r['source']=='human' for r in receipts) and any(r['source']=='native_unit_agent' for r in receipts)
        before=copy.deepcopy(first_snap['war_state'])
        chat=call('POST',f'/api/sessions/{sid}/chat',{'message':'先调用get_afsim_observation按需核实：红方第一个单位的最新坐标、当前时间是什么？哪些结果来自AFSIM，哪些来自教学规则？'})
        assert chat['war_state']==before and chat['turn_count']==1
        view=call('GET',f'/api/sessions/{sid}/commands')
        second_target=commands.towards(target,{'lat':target['lat'],'lng':target['lng']+.01},.1)
        all_orders=[{'unit_id':u['id'],'action':'hold','duration':'next'} for u in view['units']]
        all_orders[0].update(action='move',destination=second_target)
        second_snap=step(sid,all_orders,'live-second-manual')
        chat=call('POST',f'/api/sessions/{sid}/chat',{'message':'战局已推进。再次调用get_afsim_observation，只报告当前时间和红方第一个单位最新坐标，不沿用上次回答。'})
        assert chat['war_state']==second_snap['war_state'] and chat['turn_count']==2
        review=call('POST',f'/api/sessions/{sid}/review')
        assert review['war_state']==second_snap['war_state'] and review['review']['text']
        for turn in (1,2):
            trace=call('GET',f'/api/sessions/{sid}/traces/{turn}')
            assert all(p['status']=='verified' for p in trace['persistence'])
        (output/'live-answers.json').write_text(json.dumps({'session_id':sid,'chat':chat['chat_messages'],
            'review':review['review']['text'],'first_position':target,'last_position':second_target},ensure_ascii=False,indent=2))
        return {'session_id':sid,'human_command':True,'native_unit_agent':True,'model_plan':True,
            'fresh_chat_after_movement':True,'read_only_review':True,'native_trace_verified':True}

    def cancel_case():
        sid=call('POST','/api/sessions',{'scenario':'真实AFSIM取消与原子回滚验收','mission_id':'AJ15-local-v1',
            'execution_backend':'afsim','persist_roles':False})['session_id']
        call('POST',f'/api/sessions/{sid}/init'); view=call('GET',f'/api/sessions/{sid}/commands')
        view=call('PUT',f'/api/sessions/{sid}/commands',{**revision(view),'director':True,'orders':[
            {'unit_id':u['id'],'action':'hold','duration':'next'} for u in view['units']]})
        before=copy.deepcopy(api._SESSIONS[sid]['war_state']); queue=copy.deepcopy(api._SESSIONS[sid]['command_state'])
        started=threading.Event(); release=threading.Event(); original=h.afsim_call; process_ids=[]
        def intercept(tool,params,**kwargs):
            reply=original(tool,params,**kwargs)
            if tool=='run_mission' and params.get('background'):
                process_ids.append(reply['payload']['process_id']); started.set()
                if not release.wait(10): raise RuntimeError('cancellation test barrier timed out')
            return reply
        with patch.object(h,'afsim_call',side_effect=intercept), ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(client.post,f'/api/sessions/{sid}/next',json={**revision(view),'batch_id':'cancel-live'})
            try:
                if not started.wait(20): raise RuntimeError('native job did not start')
                stamp=time.monotonic(); response=call('POST',f'/api/sessions/{sid}/cancel'); release.set()
                result=future.result(timeout=20)
                latency=round(time.monotonic()-stamp,3)
                assert result.status_code==409, result.text
            finally: release.set()
        session=api._SESSIONS[sid]
        assert session['war_state']==before and session['command_state']==queue and session['turn_count']==0
        status=h.afsim_call('run_mission',{'action':'status','process_id':process_ids[-1]})['payload']['status']
        assert status!='running'
        return {'cancel_response_s':latency,'native_job_status':status,'world_and_queue_unchanged':True,
                'note':'A short native job can finish before cancellation; its candidate is still rejected.'}

    try:
        if args.live:
            case('live-controls-and-analysis', live_case)
        elif args.profile=='cancel':
            case('native-cancel-rollback',cancel_case)
        else:
            unique={m['profile']:m for m in missions.catalog()}
            for spec in unique.values():
                if not args.profile or args.profile==spec['profile']:
                    case('rules-'+spec['profile'],lambda spec=spec:rule_case(spec))
            if not args.profile:
                case('20-unit-types',mover_case)
                case('continuous-move-and-restore',continuation_case)
    finally:
        h.close_harness()
    return 0 if all(r['passed'] for r in results) else 1


if __name__=='__main__':
    raise SystemExit(main())
