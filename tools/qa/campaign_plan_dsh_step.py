"""One real DSH physical estimate under the new goal DAG; no AFSIM effects."""
import argparse
import json
from pathlib import Path
import urllib.error
import urllib.request
import uuid


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true')
    if not parser.parse_args().live:parser.error('Use --live for actual configured DSH via isolated 19108 API')
    from tools.qa.campaign_plan_fixture import inputs,NOTE
    root=Path('.cache/qa/campaign-plan-2026-10-31/dsh-step');root.mkdir(parents=True,exist_ok=True)
    def call(method,path,data=None):
        req=urllib.request.Request('http://127.0.0.1:19108/api'+path,method=method,headers={'Content-Type':'application/json'},
            data=json.dumps(data,ensure_ascii=False).encode() if data is not None else None)
        try:
            with urllib.request.urlopen(req,timeout=900) as response:return json.load(response)
        except urllib.error.HTTPError as exc:raise RuntimeError(str(exc.code)+' '+exc.read().decode()) from exc
    path=root/'initial.json'
    if path.exists():
        initial=json.loads(path.read_text());base='/sessions/'+initial['session_id'];before=call('GET',base)
        if before['turn_count']==1:
            print('Already committed DSH goal round retained; no repeat execution',flush=True);return
        assert before['turn_count']==0
    else:
        s,p=inputs();created=call('POST','/sessions',dict(scenario=NOTE+' DSH独立单轮目标图验收。',
            battle=s['definition']['battle'],time_step='30分钟',product_mode='historical',simulation_mode='open',
            execution_backend='narrative',agent_mode='native',historical_parameters=p,historical_initial_version='1.2.0'))
        base='/sessions/'+created['session_id'];before=call('POST',base+'/init');path.write_text(json.dumps(before,ensure_ascii=False,indent=2))
    view=call('GET',base+'/commands')
    call('PUT',base+'/commands',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version'],
        control_team='red',director=True,no_fire=False,intent='本轮全部部队待命；只估计本轮资源变化，不改写目标图，不编造交战。',
        orders=[dict(unit_id=u['id'],action='hold',duration='next') for u in view['units']]))
    view=call('GET',base+'/commands');result={'passed':False,'session_id':before['session_id']}
    try:
        after=call('POST',base+'/next',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version'],batch_id=uuid.uuid4().hex))
        (root/'after.json').write_text(json.dumps(after,ensure_ascii=False,indent=2));w=after['war_state']
        assert after['turn_count']==1 and w['campaign_plan']['turn']==1
        assert w['simulation_clock']['elapsed_seconds']==1800 and w['mission']['status']=='active'
        assert 'dsh_execution' in w and not w.get('afsim')
        assert not w['campaign_plan']['outcomes']['red'] and not w['campaign_plan']['outcomes']['blue']
        assert all(u['personnel']['current']==o['personnel']['current'] for team in ('red','blue')
            for u,o in zip(w[team+'_units'],before['war_state'][team+'_units']))
        result.update(passed=True,actual_dsh=True,host_goal_evaluator=True,physical_source='dsh_model_estimate',afsim_effects=False)
        print('PASS real DSH physical step: six hold estimates, resource guards and host goal DAG, 30 minute clock',flush=True)
    finally:
        (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
