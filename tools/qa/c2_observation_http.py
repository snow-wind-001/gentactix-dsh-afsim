"""Normal isolated API and native command workflow for intelligence timing QA."""
import argparse
import json
from pathlib import Path
from tools.qa import force_task_execution_live as workflow

ROOT=Path('.cache/qa/c2-observation-2026-10-31')
workflow.ROOT=ROOT;workflow.PORT=19117
call=workflow.call


def run(output=ROOT,label='情报时间原生验收；'):
    from tools.qa.historical_operational_fixture import inputs,NOTE
    output.mkdir(parents=True,exist_ok=True)
    if (output/'http-result.json').exists():raise SystemExit('Preserve actual run evidence')
    source,p=inputs();p['clock']['time_step']='15分钟';p['goal']['deadline_turn']=3
    for actor in p['actors'].values():actor['formation']['intel_age_min']=10.25
    created=call('POST','/sessions',dict(scenario=label+NOTE,battle=source['definition']['battle'],
        historical_parameters=p,historical_initial_version=source['version'],time_step='15分钟',product_mode='historical',
        simulation_mode='open',execution_backend='afsim',agent_mode='native'))
    sid=created['session_id'];base='/sessions/'+sid;before=call('POST',base+'/init');samples=[]
    result=dict(passed=False,session_id=sid,actual_afsim=True,model_calls=False,samples=samples)
    (output/'http-initial.json').write_text(json.dumps(before,ensure_ascii=False,indent=2))
    try:
        for turn in (1,2,3):
            view=call('GET',base+'/commands');orders=[dict(unit_id=u['id'],action='hold',duration='next') for u in view['units']]
            if turn==2:orders[0]['action']='recon'
            call('PUT',base+'/commands',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version'],
                control_team='red',director=True,no_fire=False,intent='仅第二轮第31师侦察，其余均待命；无射击。',orders=orders))
            after=workflow.advance(base);w=after['war_state'];a=w['red_units'][0]['formation']['intel_age_min']
            assert w['afsim']['model_skipped'] and w['simulation_clock']['elapsed_seconds']==turn*900
            events=w['combined_arms']['events'];refresh=next((e for e in events if e['action']=='recon'),None)
            if turn==2:assert refresh is not None and abs(a-(900-refresh['seconds'])/60)<1e-7
            else:assert abs(a-before['war_state']['red_units'][0]['formation']['intel_age_min']-15)<1e-7
            row=dict(turn=turn,age_min=a,refresh=refresh,intelligence=w['combined_arms']['intelligence'])
            samples.append(row);print('PASS actual HTTP',row,flush=True)
            (output/('http-after-'+str(turn)+'.json')).write_text(json.dumps(after,ensure_ascii=False,indent=2))
            before=after
        result.update(passed=True,turn=3,world_hash=workflow.digest(w),history_hash=workflow.digest(after['history']))
    finally:(output/'http-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=['serve','run','run-final','cold']);parser.add_argument('--live',action='store_true');args=parser.parse_args()
    ROOT.mkdir(parents=True,exist_ok=True)
    if args.mode=='serve':workflow.serve()
    elif args.mode in ('run','run-final'):
        if not args.live:parser.error('Actual native workflow requires --live')
        run() if args.mode=='run' else run(ROOT/'http-final','情报时间最终源码验收；')
    else:
        cases=[]
        for folder in (ROOT,ROOT/'http-final'):
            if not (folder/'http-result.json').exists():continue
            result=json.loads((folder/'http-result.json').read_text());base='/sessions/'+result['session_id'];snap=call('GET',base)
            assert not call('GET',base+'/progress')['active']
            assert snap['turn_count']==3 and workflow.digest(snap['war_state'])==result['world_hash']
            assert workflow.digest(snap['history'])==result['history_hash'];cases.append(result['session_id'])
        (ROOT/('http-cold.json' if len(cases)==1 else 'http-final-cold.json')).write_text(json.dumps(dict(passed=True,cases=cases),ensure_ascii=False,indent=2))
        print('PASS cold restore of actual HTTP cases:',len(cases))
