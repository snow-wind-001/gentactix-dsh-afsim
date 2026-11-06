"""Compare frozen direct-fire model revisions on the same sourced QA setup.

This is model sensitivity, not a causal command intervention or historical fit.
"""
import argparse
import json
from pathlib import Path
import urllib.request
import uuid

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--live',action='store_true')
args=parser.parse_args()
if not args.live:raise SystemExit('Use --live on the isolated QA backend')
base='http://127.0.0.1:18995';root=Path('.cache/qa/historical-attendance/direct');root.mkdir(parents=True,exist_ok=True)
old=Path('.cache/qa/historical-attendance/live');checks=[]


def call(method,path,data=None):
    request=urllib.request.Request(base+path,method=method,headers={'Content-Type':'application/json'},
        data=None if data is None else json.dumps(data,ensure_ascii=False).encode())
    with urllib.request.urlopen(request,timeout=1200) as response:return json.load(response)


def save(name,value):(root/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2))
def check(ok,label):
    if not ok:raise AssertionError(label)
    checks.append(label);print('PASS',label,flush=True)


def main():
    check(not call('GET','/api/health')['build']['restart_required'],'current source backend')
    parent=json.load(open(old/'draft.json'))
    draft=call('POST','/api/historical-scenarios/validate',{'parent_draft_id':parent['id'],'parameters':parent['parameters'],
        'execution_backend':'afsim','operation_id':uuid.uuid4().hex});save('draft',draft)
    check(draft['combat_reference']['version']=='aggregate-fire-cycles-2.3','explicitly revalidated new direct-fire profile')
    sid=call('POST','/api/sessions',{'scenario':'同源乔沟参数的新直射模型敏感性复验；非历史拟合或因果命令反事实',
        'battle':draft['initial']['definition']['battle'],'product_mode':'historical','execution_backend':'afsim','persist_roles':False,
        'historical_parameters':draft['parameters'],'scenario_draft_id':draft['id']})['session_id']
    initial=call('POST',f'/api/sessions/{sid}/init');save('initial',initial)
    result={'passed':False,'checks':checks,'session_id':sid,'scope':'Different firing priors, same sourced configuration; not historical calibration or causal comparison'}
    try:
        snap=initial
        for turn in range(1,13):
            reference=json.load(open(old/f'turn{turn}.json'))
            view=call('GET',f'/api/sessions/{sid}/commands');by_name={u['name']:u for u in view['units']}
            units={u['name']:u for side in ('red','blue') for u in snap['war_state'][side+'_units']};orders=[]
            for source in reference['war_state']['afsim']['orders']:
                if units[source['unit']]['personnel']['current']<=0:continue
                action=source['action'];target=source.get('target')
                if target and units[target]['personnel']['current']<=0:action='hold';target=None
                order={'unit_id':by_name[source['unit']]['id'],'action':action,'duration':'next'}
                if action=='move':order['destination']={k:source[k] for k in ('lat','lng')}
                if target:order['target_id']=by_name[target]['id']
                orders.append(order)
            rev={'expected_turn':view['turn'],**{k:view[k] for k in ('revision','world_version')}}
            view=call('PUT',f'/api/sessions/{sid}/commands',{**rev,'orders':orders,'control_team':'red','director':True,
                'no_fire':False,'unit_agents':[],'intent':'同源配置、同策略的新直射模型敏感性；单位失能时明确待命'})
            rev={'expected_turn':view['turn'],**{k:view[k] for k in ('revision','world_version')},'batch_id':uuid.uuid4().hex}
            snap=call('POST',f'/api/sessions/{sid}/next',rev);save(f'turn{turn}',snap)
            check(snap['war_state']['historical_initial']==initial['war_state']['historical_initial'],f'turn{turn} source facts unchanged')
            if turn==1:
                check(any(u['formation']['last_execution'].get('small_arms_rounds_estimate',0)>0 for side in ('red','blue') for u in snap['war_state'][side+'_units']),
                    'native receipt records shooter/cadence-based small-arms attempt estimates')
        totals={side:sum(u['personnel']['casualties'] for u in snap['war_state'][side+'_units']) for side in ('red','blue')}
        check(totals['blue']>29 and totals['red']>5,'repeated direct fire no longer inherits the old double target-size attenuation')
        check(snap['war_state']['simulation_clock']['elapsed_seconds']==21600,'six native hours with resource constraints')
        check(snap['war_state']['mission']['status']=='completed','program objective still terminates at scope boundary')
        check(call('GET',f'/api/sessions/{json.load(open(old/"result.json"))["session_id"]}')['war_state']==json.load(open(old/'turn12.json'))['war_state'],
            'old model battle remains unchanged')
        result.update(passed=True,totals=totals);save('result',result)
    except Exception as exc:
        result['error']=str(exc);save('result',result);raise


if __name__=='__main__':main()
