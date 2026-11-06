"""Actual native distance/ammo checks, then live DSH on the new profile."""
import argparse
import copy
import json
from pathlib import Path
import urllib.error
import urllib.request
import uuid

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--live',action='store_true')
args=parser.parse_args()
if not args.live:raise SystemExit('Use --live on the isolated QA backend')
base='http://127.0.0.1:18995';root=Path('.cache/qa/historical-attendance/sensitivity');root.mkdir(parents=True,exist_ok=True)
parent=json.load(open('.cache/qa/historical-attendance/direct/draft.json'));checks=[]


def call(method,path,data=None):
    request=urllib.request.Request(base+path,method=method,headers={'Content-Type':'application/json'},
        data=None if data is None else json.dumps(data,ensure_ascii=False).encode())
    try:
        with urllib.request.urlopen(request,timeout=1200) as response:return json.load(response)
    except urllib.error.HTTPError as exc:raise RuntimeError(str(exc.code)+': '+exc.read().decode()[:1400]) from exc


def save(name,value):(root/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2))
def check(ok,label):
    if not ok:raise AssertionError(label)
    checks.append(label);print('PASS',label,flush=True)


def create(label,params=None,engine='afsim'):
    p=params or parent['parameters']
    draft=call('POST','/api/historical-scenarios/validate',{'parent_draft_id':parent['id'],'parameters':p,
        'execution_backend':engine,'operation_id':uuid.uuid4().hex})
    sid=call('POST','/api/sessions',{'scenario':label+'；同源配置、未标定数值假设','battle':parent['initial']['definition']['battle'],
        'product_mode':'historical','execution_backend':engine,'persist_roles':False,'historical_parameters':draft['parameters'],'scenario_draft_id':draft['id']})['session_id']
    snap=call('POST',f'/api/sessions/{sid}/init');save(label+'-initial',snap)
    return sid,snap


def fire(label,offset,ammo=80):
    p=copy.deepcopy(parent['parameters']);red=p['actors']['ww2.cn.regiment686']
    p['actors']['ww2.jp.regiment21.train']['position']={'lat':red['position']['lat']+offset,'lng':red['position']['lng']}
    red['logistics']['ammo']=ammo;sid,initial=create(label,p)
    view=call('GET',f'/api/sessions/{sid}/commands');units={u['historical_unit_id']:u for side in ('red','blue') for u in initial['war_state'][side+'_units']}
    names={u['name']:u for u in view['units']};attacker=units['ww2.cn.regiment686']['name'];target=units['ww2.jp.regiment21.train']['name']
    orders=[{'unit_id':u['id'],'action':'fire' if u['name']==attacker else 'hold','duration':'next',
        **({'target_id':names[target]['id']} if u['name']==attacker else {})} for u in view['units']]
    rev={'expected_turn':view['turn'],**{k:view[k] for k in ('revision','world_version')}}
    view=call('PUT',f'/api/sessions/{sid}/commands',{**rev,'orders':orders,'control_team':'red','director':True,'unit_agents':[],'no_fire':False,'intent':label})
    rev={'expected_turn':view['turn'],**{k:view[k] for k in ('revision','world_version')},'batch_id':uuid.uuid4().hex}
    snap=call('POST',f'/api/sessions/{sid}/next',rev);save(label,snap)
    actors={u['historical_unit_id']:u for side in ('red','blue') for u in snap['war_state'][side+'_units']}
    return {'session_id':sid,'casualties':actors['ww2.jp.regiment21.train']['personnel']['casualties'],
        'execution':actors['ww2.cn.regiment686']['formation']['last_execution']}


result={'passed':False,'checks':checks,'scope':'Mechanism sensitivity and real model integration; not historical casualty calibration'}
try:
    maximum=parent['parameters']['actors']['ww2.cn.regiment686']['attack_range_m']
    near_offset=maximum*.3/111320
    near=fire('near',near_offset);far=fire('far',maximum*.75/111320);limited=fire('limited',near_offset,3)
    check(near['casualties']>far['casualties']>0,'same force and cover: closer direct fire has larger native effect')
    check(limited['execution']['fire_cycles']==3 and limited['execution']['fire_stop_reason']==8,'new direct model stops exactly at workload limit')
    check(limited['casualties']<near['casualties'],'limited ammunition reduces direct-fire casualties')
    check(near['execution']['small_arms_rounds_estimate']>limited['execution']['small_arms_rounds_estimate']>0,'native estimated attempts follow actual firing budget')
    result.update(near=near,far=far,limited=limited)
    for engine in ('afsim','narrative'):
        sid,initial=create(engine+'-automatic',engine=engine)
        view=call('GET',f'/api/sessions/{sid}/commands');rev={'expected_turn':view['turn'],**{k:view[k] for k in ('revision','world_version')},'batch_id':uuid.uuid4().hex}
        snap=call('POST',f'/api/sessions/{sid}/next',{**rev,'instruction':'实际观察态势和新的直射假设；双方逐单位明确决策，合理接敌、反击或转移。688为预备队待命，红方是零燃油徒步单位。保持源番号、机动方式和人员装备守恒；损失只作模型估计，不强制历史战果。'})
        save(engine+'-automatic',snap)
        check(snap['war_state']['historical_initial']==initial['war_state']['historical_initial'],engine+' retains sourced phase and identity')
        check(snap['war_state']['combat_reference']['version']=='aggregate-fire-cycles-2.3',engine+' retains frozen direct-fire priors')
        check(not snap['war_state'].get('afsim',{}).get('model_skipped',False),engine+' actual DSH runtime participates')
        if engine=='narrative':check('afsim' not in snap['war_state'],'DSH-only never claims native execution')
        result[engine+'_session']=sid
    result['passed']=True;save('result',result)
except Exception as exc:
    result['error']=str(exc);save('result',result);raise
