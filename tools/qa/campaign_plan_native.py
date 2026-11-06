"""Actual API/AFSIM rounds: hold, one axis, both axes and a real intervention."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import urllib.request
import urllib.error
import uuid


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true')
    parser.add_argument('--team',choices=['red','blue'],default='red');args=parser.parse_args()
    if not args.live:parser.error('Use --live with the isolated normal API on 19108')
    from gentactix import historical_operations as ho
    from tools.qa.campaign_plan_fixture import inputs,NOTE
    root=Path('.cache/qa/campaign-plan-2026-10-31')/('native' if args.team=='red' else 'native-blue');root.mkdir(parents=True,exist_ok=True)
    def call(method,path,body=None):
        req=urllib.request.Request('http://127.0.0.1:19108/api'+path,
            data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,
            headers={'Content-Type':'application/json'},method=method)
        try:
            with urllib.request.urlopen(req,timeout=180) as response:return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f'{method} {path}: {exc.code} '+exc.read().decode()) from exc
    s,p=inputs();definition=ho.definition(s,p)
    created=call('POST','/sessions',dict(scenario=NOTE,battle=s['definition']['battle'],time_step='30分钟',
        product_mode='historical',simulation_mode='open',execution_backend='afsim',agent_mode='native',
        historical_parameters=p,historical_initial_version='1.2.0'))
    sid=created['session_id'];base='/sessions/'+sid
    current=call('POST',base+'/init');(root/'initial.json').write_text(json.dumps(current,ensure_ascii=False,indent=2))
    result={'passed':False,'session_id':sid,'scope':NOTE,'rounds':[]}
    def revision(view):return dict(world_version=view['world_version'],revision=view['revision'],expected_turn=view['turn'])
    def advance(moves):
        view=call('GET',base+'/commands');orders=[]
        by_source={u['historical_unit_id']:u for u in current['war_state']['red_units']+current['war_state']['blue_units']}
        by_name={u['name']:identity for identity,u in by_source.items()}
        for unit in view['units']:
            point=moves.get(by_name[unit['name']])
            orders.append(dict(unit_id=unit['id'],action='move' if point else 'hold',duration='next',
                **({'destination':point} if point else {})))
        call('PUT',base+'/commands',{**revision(view),'control_team':'red','director':True,'no_fire':False,'intent':NOTE,'orders':orders})
        view=call('GET',base+'/commands')
        return call('POST',base+'/next',{**revision(view),'batch_id':uuid.uuid4().hex})
    try:
        points={n['id']:n['condition'].get('region',{}).get('center') for n in p['campaign_plan']['nodes']}
        if args.team=='red':
            current=advance({});assert current['war_state']['mission']['status']=='active'
            result['rounds'].append({'turn':current['turn_count'],'action':'all_hold','resolution':current['war_state']['campaign_plan']['resolution']})
            current=advance({'ww2.cn.division159':points['north']})
            (root/'one-axis.json').write_text(json.dumps(current,ensure_ascii=False,indent=2))
            state=current['war_state']['campaign_plan']
            assert state['nodes']['north']['status']=='completed',state['nodes']['north']
            assert current['war_state']['mission']['status']=='active' and state['nodes']['preserve']['status']=='waiting_dependency'
            result['rounds'].append({'turn':current['turn_count'],'action':'north_move','resolution':state['resolution']})
            current=advance({'ww2.cn.division51':points['south']})
        else:
            current=advance({'ww2.jp.division106':points['blue_exit']})
        (root/('both-axes.json' if args.team=='red' else 'blue-exit.json')).write_text(json.dumps(current,ensure_ascii=False,indent=2))
        assert current['war_state']['mission']['winner']==args.team and current['war_state']['mission']['status']=='completed'
        result['rounds'].append({'turn':current['turn_count'],'action':'south_move' if args.team=='red' else 'blue_exit','resolution':current['war_state']['campaign_plan']['resolution']})
        original=copy.deepcopy(current['war_state'])
        other_names={u['name'] for u in current['war_state'][('blue' if args.team=='red' else 'red')+'_units']}
        comparison=call('POST',base+'/counterfactual',dict(turn=current['turn_count'],mode='mission',
            orders=[o for o in current['war_state']['mission']['last_orders'] if o['unit'] in other_names]))
        (root/'counterfactual.json').write_text(json.dumps(comparison,ensure_ascii=False,indent=2))
        restored=call('GET',base)
        assert restored['war_state']==original,'Counterfactual changed main world'
        metrics={m['metric']:m for m in comparison['metrics']}
        assert metrics['会战目标图已结算']['factual']==1 and metrics['会战目标图已结算']['alternative']==0,metrics
        label=('红方' if args.team=='red' else '蓝方')+'总目标满足'
        assert metrics[label]['factual']==1 and metrics[label]['alternative']==0
        result.update(passed=True,actual_afsim=True,model_planning_skipped=True,intervention_changed_goal=True,
            main_world_unchanged=True,world_hash=hashlib.sha256(json.dumps(original,sort_keys=True,ensure_ascii=False).encode()).hexdigest())
        print('PASS actual AFSIM/API '+args.team+': native movement resolves its own goal; hold intervention changes result without main-world writes',flush=True)
    finally:
        (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        print('Evidence:',root,flush=True)


if __name__=='__main__':main()
