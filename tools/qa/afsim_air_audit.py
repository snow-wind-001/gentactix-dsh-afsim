"""Isolated real native-MCP airstrike/continuity/control/analysis acceptance."""
from pathlib import Path
import argparse
import copy
import json
import os
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))


def main():
    p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');args=p.parse_args()
    home=ROOT/'.cache/qa/afsim-audit-20261027/air-acceptance';home.mkdir(parents=True,exist_ok=True)
    out=home/('run-'+str(time.time_ns()));out.mkdir()
    (home/'latest.json').write_text(json.dumps({'directory':str(out)}))
    os.environ.update(GENTACTIX_SESSION_DIR=str(out/'sessions'),GENTACTIX_TRACE_DIR=str(out/'traces'),
        GENTACTIX_DSH_HOME=str(out/'dsh-home'),GENTACTIX_DSH_WORKSPACE=str(out/'dsh-workspace'),
        GENTACTIX_ROLE_INDEX=str(out/'roles.json'),GENTACTIX_DSH_PATCHES='[]')
    from backend import main as app, harness_engine as h, afsim_state, session_store, afsim_world, afsim_rules, afsim_air
    from gentactix import missions, commands
    from fastapi.testclient import TestClient
    c=TestClient(app.app); results=[]
    def call(method,path,body=None):
        r=c.request(method,path,json=body)
        if r.status_code!=200:raise RuntimeError(f'{r.status_code}: {r.text[:800]}')
        return r.json()
    def revision(v):return {'expected_turn':v['turn'],'revision':v['revision'],'world_version':v['world_version']}
    def case(name,fn):
        try:result={'case':name,'passed':True,**(fn() or {})}
        except Exception as e:result={'case':name,'passed':False,'error':str(e)[:1500]}
        results.append(result);print(json.dumps(result,ensure_ascii=False),flush=True)
        (out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    def battle(identity='AJ18-local-v1'):
        sid=call('POST','/api/sessions',{'scenario':missions.definition(identity)['battle'], 'mission_id':identity,
            'execution_backend':'afsim','persist_roles':False})['session_id']
        snap=call('POST',f'/api/sessions/{sid}/init');return sid,snap
    def step(sid,targeted=True,multiple=False):
        v=call('GET',f'/api/sessions/{sid}/commands');red=[u for u in v['units'] if u['team']=='red'];blue=[u for u in v['units'] if u['team']=='blue']
        orders=[{'unit_id':u['id'],'action':'hold','duration':'next'} for u in v['units'] if u['available']]
        for i,u in enumerate(red[:2 if multiple else 1] if targeted else []):
            next(o for o in orders if o['unit_id']==u['id']).update(action='air_support',target_id=blue[i]['id'])
        v=call('PUT',f'/api/sessions/{sid}/commands',{**revision(v),'orders':orders,'director':True})
        with patch.object(h,'get_ai_response',side_effect=AssertionError('manual batch called model')),patch.object(missions,'advance',side_effect=AssertionError('Python executor called')):
            return call('POST',f'/api/sessions/{sid}/next',{**revision(v),'batch_id':'air-'+str(v['turn'])})
    known={}
    def strike():
        sid,initial=battle();known['sid']=sid;known['initial']=initial
        snap=step(sid);known['snap']=snap;world=snap['war_state'];air=world['air_operations'];task=air['missions'][0]
        assert air['assets']['red']=={'committed':8,'ready':7,'destroyed':1,'sorties':2,'ordnance':22,'fuel':44}
        assert world['blue_units'][0]['personnel']['casualties']==6
        assert world['blue_units'][0]['equipment'][0]['destroyed']==1
        assert world['blue_units'][0]['last_combat_effects']['air_casualties']==6
        assert world['blue_units'][0]['last_combat_effects']['ground_casualties']==0
        assert world['mission']['ledger'][0]['ammo_spent']==0
        assert [e['phase'] for e in task['events']]==['launch','air_defense','strike','returned']
        assert all(e['lat']!=0 and e['lng']!=0 for e in task['events'])
        (out/'snapshot.json').write_text(json.dumps(snap,ensure_ascii=False,indent=2))
        return {'session_id':sid,'native_phases':task['events'],'assets':air['assets'],'personnel_loss':6}
    case('native_targeted_strike_and_separate_accounts',strike)
    def comparison_and_restore():
        sid=known['sid'];before=call('GET',f'/api/sessions/{sid}');v=call('GET',f'/api/sessions/{sid}/commands')
        actor=next(u for u in v['units'] if u['team']=='red')
        result=call('POST',f'/api/sessions/{sid}/commands/compare',{**revision(v),'turn':1,
            'orders':[{'unit_id':actor['id'],'action':'hold','duration':'next'}]})
        assert before['war_state']==call('GET',f'/api/sessions/{sid}')['war_state']
        metric=next(x for x in result['metrics'] if x['metric']=='红方可用飞机')
        assert metric['factual']==7 and metric['alternative']==8
        restored,errors=session_store.load_all();assert not errors
        app._SESSIONS[sid]=restored[sid]
        assert call('GET',f'/api/sessions/{sid}')['war_state']==before['war_state']
        return {'aircraft_counterfactual':metric,'world_unchanged':True,'disk_restore':True}
    case('airstrike_counterfactual_is_read_only_and_checkpoint_restores',comparison_and_restore)
    def continuity():
        sid=known['sid'];before=call('GET',f'/api/sessions/{sid}');after=step(sid,False)
        assert after['war_state']['air_operations']['assets']==before['war_state']['air_operations']['assets']
        assert after['war_state']['air_operations']['missions']==[]
        assert after['war_state']['air_operations']['recent_missions'][0]['target_turn_effects']['air_casualties']==6
        (out/'continuation.json').write_text(json.dumps(after,ensure_ascii=False,indent=2))
        return {'turns':after['turn_count'],'aircraft_conserved':True}
    case('second_turn_preserves_air_pool_without_new_sorties',continuity)
    def parallel():
        sid,_=battle('AJ19-local-v1');after=step(sid,multiple=True);air=after['war_state']['air_operations']
        assert len(air['missions'])==2 and air['assets']['red']['sorties']==4 and air['assets']['red']['destroyed']==2
        return {'missions':2,'pool':air['assets']['red']}
    case('simultaneous_packages_share_native_inventory',parallel)
    def abort():
        # Explicit timing sensitivity fixture: late launch gives the target time
        # to move outside the 500m aim area. No user settings or mission JSON edit.
        world=missions.initial('AJ18-local-v1');target=world['blue_units'][0];actor=world['red_units'][0]
        move=commands.towards(target,{'lat':target['lat']+.1,'lng':target['lng']},.59)
        orders=[{'unit':actor['name'],'action':'air_support','target':target['name']},
                {'unit':target['name'],'action':'move',**move}]
        with patch.dict(afsim_air.CONFIG,preparation_s=1550):
            scene=afsim_world.compile_scene(world,orders,1800,native_rules=True)
        positions,evidence=afsim_world.run_scene({},scene)
        observed=afsim_world.apply_observations(world,positions,scene)
        after=afsim_rules.apply_telemetry(evidence['native_effects'],scene['native_model'],scene,observed)
        air=after['air_operations'];assert air['missions'][0]['outcome']=='aborted'
        assert air['assets']['red']['ready']==8 and air['assets']['red']['ordnance']==24 and air['assets']['red']['fuel']==44
        assert after['blue_units'][0]['personnel']['casualties']==0
        return {'timing_fixture':'1550s prep; parameter sensitivity only','phases':air['missions'][0]['events']}
    case('moving_target_aborts_before_bomb_release',abort)
    if args.live:
        def chat():
            sid=known['sid'];answer=call('POST',f'/api/sessions/{sid}/chat',{'message':'请先调用get_afsim_observation，仅根据最新观察解释当前轮航空出动和当前累计飞机数量、损失、架次与航空油弹；区分本轮与历史，不要编造战果。'})
            (out/'live-chat.json').write_text(json.dumps(answer,ensure_ascii=False,indent=2))
            return {'answer_recorded':True}
        case('real_dsh_analysis_reads_current_air_accounts',chat)
    h.shutdown_runtime() if hasattr(h,'shutdown_runtime') else None
    raise SystemExit(0 if all(r['passed'] for r in results) else 1)


if __name__=='__main__':main()
