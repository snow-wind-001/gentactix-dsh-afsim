"""Normal create/init/commands/next over explicit multi-site QA estimates.

Retains Jialing's sourced local roster, but the extra passage is NOT a sourced
1935 site. Optional --serve exposes only this isolated QA session directory.
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
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--native',action='store_true');p.add_argument('--config',type=Path,required=True)
    p.add_argument('--serve',type=int)
    args=p.parse_args()
    if not args.native:p.error('--native required')
    root=Path('.cache/qa/crossing-network-api-2026-10-29')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                       ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    os.environ['GENTACTIX_LLM_CONFIG']=str(args.config.resolve())
    from fastapi.testclient import TestClient
    from backend import main as api,harness_engine as h,runtime_bridge,session_store,agent_tools
    from gentactix import missions,crossing_network,sim_clock
    from tools.qa.jialing_fixture import inputs,NOTE
    runtime_bridge.register_dispatcher(api._native_tool_dispatch)
    client=TestClient(api.app);source,params=inputs(throughput=1000)
    center=params['area']['center'];lat,lng=center['lat'],center['lng']
    bridge=params['facility'];bridge['name']='西侧QA渡点（非历史定位）'
    bridge['crossing_model'].update(barrier={'a':{'lat':lat,'lng':lng-.02},'b':{'lat':lat,'lng':lng+.02}},
        banks={'a':{'lat':lat-.001,'lng':lng},'b':{'lat':lat+.001,'lng':lng}})
    other=copy.deepcopy(bridge);other.update(id='qa-east',name='东侧QA渡点（非历史定位）',lng=lng+.01)
    for point in other['crossing_model']['banks'].values():point['lng']=lng+.01
    other['crossing_model']['throughput_work_per_hour']=600
    bridge['crossing_network']={'version':crossing_network.VERSION,'sites':[other]}
    for i,identity in enumerate(('jl.red.reg263','jl.red.hq_training')):
        params['actors'][identity].update(personnel=600,position={'lat':lat-.001,'lng':lng+i*.01})
    params['goal'].update(objective={'lat':lat+.003,'lng':lng+.005},exit={'lat':lat+.004,'lng':lng+.005},radius_km=.8)
    params['assumptions']+= '增加独立通道仅用于软件测试，不代表嘉陵江三路全场历史联动。'
    def write(name,value):(root/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    write('parameters',params);write('basis',source)
    result={'passed':False,'model_calls':0,'cases':[]}
    def revision(view):return {k:view[v] for k,v in [('expected_turn','turn'),('revision','revision'),('world_version','world_version')]}
    try:
        with patch.object(missions,'advance',side_effect=AssertionError('No Python battle executor')), \
             patch.object(h,'get_ai_response',side_effect=AssertionError('No LLM in controlled acceptance')):
            r=client.post('/api/sessions',json={'scenario':'多渡点原生受控QA（非全战役复原）','battle':source['definition']['battle'],
                'historical_parameters':params,'time_step':'30分钟','execution_backend':'afsim',
                'simulation_mode':'open','product_mode':'historical','persist_roles':False})
            assert r.status_code==200,r.text
            sid=r.json()['session_id'];session=api._SESSIONS[sid];path='/api/sessions/'+sid
            r=client.post(path+'/init');assert r.status_code==200,r.text
            write('initial',r.json());assert r.json()['war_state']['afsim']['entity_count']==4
            for turn in (1,2):
                before=copy.deepcopy(session['war_state']);view=client.get(path+'/commands').json();orders=[]
                roster={u['name']:u for _,u in missions.units(before)}
                for item in view['units']:
                    u=roster[item['name']];o={'unit_id':item['id'],'action':'hold','duration':'next'}
                    if u['historical_unit_id'] in ('jl.red.reg263','jl.red.hq_training'):
                        east=u['historical_unit_id']=='jl.red.hq_training'
                        o.update(action='move',duration='until_arrived',destination={'lat':lat+.003,'lng':lng+(.01 if east else 0)})
                        prior=next((x for x in view['orders'] if x['unit_id']==item['id']),None)
                        if prior:o['id']=prior['id']
                    orders.append(o)
                r=client.put(path+'/commands',json={**revision(view),'orders':orders,'control_team':'red','director':True,'no_fire':False,'intent':NOTE})
                assert r.status_code==200,r.text
                view=client.get(path+'/commands').json();request={**revision(view),'batch_id':uuid.uuid4().hex}
                r=client.post(path+'/next',json=request);assert r.status_code==200,r.text
                snapshot=r.json();world=snapshot['war_state'];write('turn'+str(turn),snapshot)
                assert world['current_time']==sim_clock.target(before,'30分钟')[0]
                assert world['historical_initial']==source and len(missions.units(world))==4
                tasks=[u['crossing'] for u in world['red_units'] if u.get('crossing')]
                assert {t['site_id'] for t in tasks}=={bridge['id'],other['id']}
                observed=agent_tools.execute_tool_call(session,world,{'tool':'get_afsim_observation','args':{'limit':16,'detail':True}})
                assert observed['ok'] and observed['execution']['verified']
                for row in observed['units']:
                    u=next(u for _,u in missions.units(world) if u['name']==row['name'])
                    assert row['position']=={'lat':u['lat'],'lng':u['lng']}
                write('observation'+str(turn),observed)
                decisions=client.get(path+f'/unit-decisions?start_turn={turn}&end_turn={turn}').json()['items']
                assert len(decisions)==4;write('decisions'+str(turn),decisions)
                repeated=client.post(path+'/next',json=request)
                assert repeated.status_code==200 and repeated.json()['command_result']['replayed']
                loaded,errors=session_store.load_all();assert not errors and loaded[sid]['war_state']==world
                assert all(u['personnel']['committed']==u['personnel']['current']+u['personnel']['casualties']+u['personnel']['noncombat_losses'] for _,u in missions.units(world))
                result['cases'].append({'turn':turn,'task_sites':[t['site_id'] for t in tasks],
                    'capacities':[s['crossing_receipt'] for s in crossing_network.sites(world)],'artifact':world['afsim']['artifact']})
            result.update(passed=True,session_id=sid);write('result',result)
            print(json.dumps({'passed':True,'root':str(root),'session_id':sid},ensure_ascii=False),flush=True)
        if args.serve:
            import uvicorn
            uvicorn.run(api.app,host='127.0.0.1',port=args.serve,log_level='warning')
    finally:
        write('result',result);h.close_harness()


if __name__=='__main__':main()
