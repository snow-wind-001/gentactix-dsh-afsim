"""Real Baozuo API/DSH-plugin/AFSIM integration over explicit QA parameters.

No LLM calls: controlled orders isolate engine effects while the separate live
Cheqiao run verifies model planning. This does not certify historical fit.
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
    parser.add_argument('--native',action='store_true')
    parser.add_argument('--config',type=Path,required=True)
    args=parser.parse_args()
    if not args.native:parser.error('--native required')
    root=Path('.cache/qa/baozuo-native-2026-10-29')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','home'),
                       ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    os.environ['GENTACTIX_LLM_CONFIG']=str(args.config.resolve())
    from fastapi.testclient import TestClient
    from backend import main as api,session_store,harness_engine as h,runtime_bridge,agent_tools
    from gentactix import missions,sim_clock
    from tools.qa.baozuo_fixture import inputs
    runtime_bridge.register_dispatcher(api._native_tool_dispatch)
    client=TestClient(api.app);result={'passed':False,'model_calls':0,'historical_fit_verified':False,'cases':[]}

    def write(name,value):
        (root/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')

    def revision(view):
        return {'expected_turn':view['turn'],'revision':view['revision'],'world_version':view['world_version']}

    def create(label,late=False):
        source,parameters=inputs()
        if late:
            parameters['clock']['start']='1935-08-30 18:00';parameters['goal']['deadline_turn']=34
            for entry in parameters['campaign']['arrivals'].values():
                if 'reference_id' not in entry:entry['not_before']='1935-08-30T18:00'
        basis=client.get('/api/historical-scenarios/basis',params={'battle':source['definition']['battle'],'time_step':'1小时'})
        assert basis.status_code==200 and basis.json()['ready']
        assert basis.json()['initial']['phase_id']=='baozuo_core'
        created=client.post('/api/sessions',json={'scenario':'包座原生受控QA：'+label,
            'battle':source['definition']['battle'],'historical_parameters':parameters,
            'time_step':'1小时','execution_backend':'afsim','simulation_mode':'open',
            'product_mode':'historical','persist_roles':False})
        assert created.status_code==200,created.text
        session=api._SESSIONS[created.json()['session_id']]
        path='/api/sessions/'+session['id']
        response=client.post(path+'/init');assert response.status_code==200,response.text
        initialized=response.json()['war_state'];native=initialized['afsim']
        assert native['entity_count']==12 and native['returncode']==0
        assert initialized['historical_initial']==source
        write(label+'-initial',response.json())
        return session,path

    def step(label,session,path,mode):
        before=copy.deepcopy(session['war_state']);view=client.get(path+'/commands').json()
        by_source={u['historical_unit_id']:u for _,u in missions.units(before)}
        targets={}
        if mode in ('attack','red_hold'):
            targets={'lm.blue.dajie_garrison':'lm.red.regiment264',
                     'lm.blue.qiuji_garrison':'lm.red.division10'}
        if mode=='attack':targets.update({v:k for k,v in list(targets.items())})
        source_by_name={u['name']:key for key,u in by_source.items()}
        orders=[]
        for unit in view['units']:
            identity=source_by_name[unit['name']]
            order={'unit_id':unit['id'],'action':'recon' if mode=='arrival' else 'hold','duration':'next'}
            if mode=='corridor' and identity=='lm.red.division10':
                region=before['mission']['definition']['campaign_definition']['objective']['relief_regions'][1]
                order.update(action='move',destination=copy.deepcopy(region['center']))
            if identity in targets:
                target=by_source[targets[identity]]['name']
                target_id=next(u['id'] for u in view['units'] if u['name']==target)
                order.update(action='fire',target_id=target_id)
            orders.append(order)
        response=client.put(path+'/commands',json={**revision(view),'orders':orders,'control_team':'red',
            'director':True,'no_fire':False,'intent':'原生受控QA，非历史命令或史实结果。'})
        assert response.status_code==200,response.text
        view=client.get(path+'/commands').json();request={**revision(view),'batch_id':uuid.uuid4().hex}
        response=client.post(path+'/next',json=request);assert response.status_code==200,response.text
        snapshot=response.json();after=snapshot['war_state'];native=after['afsim'];turn=session['turn_count']
        write(label+'-turn'+str(turn),snapshot)
        assert native['returncode']==0 and native['entity_count']==12 and native['model_skipped']
        assert after['current_time']==sim_clock.target(before,'1小时')[0]
        assert before['historical_initial']==after['historical_initial']
        assert [u['historical_unit_id'] for _,u in missions.units(after)]==list(source_by_name.values())
        for _,unit in missions.units(after):
            personnel=unit['personnel']
            assert personnel['committed']==personnel['current']+personnel['casualties']+personnel['noncombat_losses']
            assert personnel['casualties']==sum(personnel.get(k) or 0 for k in ('killed','wounded','missing','captured','unclassified_casualties'))
            assert all(e['committed']==e['operational']+e['damaged']+e['destroyed'] for e in unit['equipment'])
            if not after['campaign']['actors'][unit['name']]['active']:
                old=next(u for _,u in missions.units(before) if u['name']==unit['name'])
                assert (unit['lat'],unit['lng'])==(old['lat'],old['lng'])
                assert unit['formation']['last_execution']['fire_cycles']==0
        decisions=client.get(path+f'/unit-decisions?start_turn={turn}&end_turn={turn}').json()['items']
        assert len(decisions)==12
        for row in decisions:
            unit=next(u for _,u in missions.units(after) if u['name']==row['unit_name'])
            if unit['formation']['last_execution']['command_done']==0:assert row['status']=='blocked'
        observed=agent_tools.execute_tool_call(session,after,{'tool':'get_afsim_observation','args':{'limit':16,'detail':True}})
        assert observed['ok'] and len(observed['units'])==12 and observed['execution']['verified']
        for row in observed['units']:
            unit=next(u for _,u in missions.units(after) if u['name']==row['name'])
            assert row['personnel']['current']==unit['personnel']['current']
            assert row['position']=={'lat':unit['lat'],'lng':unit['lng']}
        changes=agent_tools.execute_tool_call(session,after,{'tool':'get_afsim_changes','args':{'mode':'aggregate','since_turn':0,'limit':16}})
        assert changes['ok']
        write(label+'-observation'+str(turn),observed);write(label+'-changes'+str(turn),changes)
        write(label+'-decisions'+str(turn),decisions)
        replay=client.post(path+'/next',json=request)
        assert replay.status_code==200 and replay.json()['command_result']['replayed']
        restored,errors=session_store.load_all();assert not errors and restored[session['id']]['war_state']==after
        summary={'case':label,'turn':turn,'totals':{t:sum(u['personnel']['casualties'] for u in after[t+'_units']) for t in ('red','blue')},
            'staged':sum(not x['active'] for x in after['campaign']['actors'].values()),'native_artifact':native['artifact']}
        result['cases'].append(summary);write('result',result);print(summary,flush=True)
        return after

    try:
        with patch.object(h,'get_ai_response',side_effect=AssertionError('Manual QA must not call LLM')), \
             patch.object(missions,'advance',side_effect=AssertionError('No Python combat fallback')):
            session,path=create('attack');attack=step('attack',session,path,'attack')
            assert all(sum(u['personnel']['casualties'] for u in attack[t+'_units'])>0 for t in ('red','blue'))
            for _ in range(2):step('attack',session,path,'attack')
            session,path=create('red-hold');held=step('red-hold',session,path,'red_hold')
            assert sum(u['personnel']['casualties'] for u in held['blue_units'])==0
            session,path=create('all-hold');idle=step('all-hold',session,path,'hold')
            assert all(u['personnel']['casualties']==0 for _,u in missions.units(idle))
            session,path=create('corridor');corridor=step('corridor',session,path,'corridor')
            assert corridor['campaign']['objective']['relief_denied']
            assert all(u['personnel']['casualties']==0 for _,u in missions.units(corridor))
            assert next(u for u in corridor['blue_units'] if u['historical_unit_id']=='lm.blue.qiuji_garrison')['personnel']['current']>0
            session,path=create('arrival',late=True)
            step('arrival',session,path,'arrival');arrived=step('arrival',session,path,'arrival')
            for _,unit in missions.units(arrived):
                identity=unit['historical_unit_id']
                if identity=='lm.blue.regiment291':
                    assert arrived['campaign']['actors'][unit['name']]['active']
                    assert unit['formation']['last_execution']['command_done']==1
                elif identity in ('lm.blue.regiment289','lm.blue.regiment294'):
                    assert not arrived['campaign']['actors'][unit['name']]['active']
        result.update(passed=True,checks=['12 native identities loaded through init API','same baseline decision contrast',
            'three continuous turns','corridor control without destroying Qiuji garrison',
            'staged entities cannot fire or move','source-bound release permits later orders',
            'personnel/equipment conservation','DSH observation matches native state','command delivery receipts',
            'idempotent submission','checkpoint reload'])
    finally:
        h.close_harness();write('result',result)
        (root.parent/'latest.json').write_text(json.dumps({'directory':str(root)})+'\n');print(root)


if __name__=='__main__':main()
