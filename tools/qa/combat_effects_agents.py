"""Actual DSH planning/effects, native counterfactual and legacy-loss upgrade.

Only uses isolated QA APIs. Numerical parameters are estimates over source IDs,
not a complete historical deployment. Does not change the installed user saves.
"""
import argparse
import copy
import json
from pathlib import Path
import urllib.error
import urllib.request
import uuid
from gentactix import combat_effects

from tools.qa.historical_operational_fixture import BATTLE, inputs

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--live',action='store_true')
parser.add_argument('--port',type=int,default=18994)
args=parser.parse_args()
if not args.live or not 18900<=args.port<=18999:raise SystemExit('Use --live on isolated QA port')
base=f'http://127.0.0.1:{args.port}';root=Path('.cache/qa/combat-effects/agents');root.mkdir(parents=True,exist_ok=True)
result={'passed':False,'checks':[],'scope':'Actual native DSH and AFSIM; partial historical IDs with explicit QA estimates'}


def call(method,path,data=None,origin=base):
    request=urllib.request.Request(origin+path,method=method,headers={'Content-Type':'application/json'},
        data=None if data is None else json.dumps(data,ensure_ascii=False).encode())
    try:
        with urllib.request.urlopen(request,timeout=1200) as response:return json.load(response)
    except urllib.error.HTTPError as exc:raise RuntimeError(str(exc.code)+': '+exc.read().decode()[:2000]) from exc


def save(name,value):(root/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2))
def check(ok,label):
    if not ok:raise AssertionError(label)
    result['checks'].append(label);print('PASS',label,flush=True)


def revision(sid):
    view=call('GET','/api/sessions/'+sid+'/commands')
    return view,{'revision':view['revision'],'world_version':view['world_version'],'expected_turn':view['turn']}


def create(engine):
    _,p=inputs();p=copy.deepcopy(p);p['goal']['deadline_turn']=30
    for row in p['actors'].values():row['formation']['shells']=3000
    sid=call('POST','/api/sessions',{'scenario':'战损参照实际智能体测试；人数坐标为显式QA假设，非历史部署',
        'battle':BATTLE,'product_mode':'historical','execution_backend':engine,'historical_parameters':p,'persist_roles':False})['session_id']
    initial=call('POST','/api/sessions/'+sid+'/init');save(engine+'-initial',initial)
    return sid,initial


try:
    check(not call('GET','/api/health')['build']['restart_required'],'current backend identity')
    # Reuse the genuine new native trajectory for a controlled intervention.
    sid=json.loads(Path('.cache/qa/combat-effects/live/result.json').read_text())['sustained_session']
    factual=call('GET','/api/sessions/'+sid);view,rev=revision(sid)
    red=next(u for u in view['units'] if u['team']=='red')
    alternative=call('POST','/api/sessions/'+sid+'/commands/compare',{**rev,'turn':1,
        'orders':[{'unit_id':red['id'],'action':'hold','duration':'next'}]})
    save('native-comparison',alternative)
    check(next(u for u in alternative['alternative']['blue_units'] if u['name']=='日军濑谷支队')['personnel']['casualties']==0,
          'withholding red fire removes blue casualties without a historical quota')
    check(call('GET','/api/sessions/'+sid)['war_state']==factual['war_state'],'comparison preserves main battle')
    # Actual live native runtime; no response fixtures or second SDK loop.
    for engine in ('afsim','narrative'):
        auto,initial=create(engine);view,rev=revision(auto)
        instruction=('参数化QA，双方持续相互炮击：第31师和日军濑谷支队各bombard对方，日军坂本支队hold。'
            '先观察实际态势和历史战损参照，再各自明确决策。不得强制匹配历史总伤亡。'
            '如果AFSIM关闭，估计实际本轮接敌时间、炮弹发射量、战斗减员及装备损失，'
            '新增伤亡用killed/wounded/missing/captured/unclassified_casualties分别记录，守恒且明确为模型估计。')
        snap=call('POST','/api/sessions/'+auto+'/next',{**rev,'batch_id':uuid.uuid4().hex,'instruction':instruction})
        save(engine+'-automatic',snap);world=snap['war_state']
        check(world['historical_initial']==initial['war_state']['historical_initial'],engine+' immutable source facts')
        check(world['combat_reference']==initial['war_state']['combat_reference'],engine+' frozen loss reference')
        if engine=='afsim':
            check(not world['afsim']['model_skipped'] and len(world['afsim']['orders'])==3,'real DSH plans all actors on both sides')
            check(len(world['engagements'])==2 and all(u['formation']['last_execution']['fire_cycles']>1
                for u in (world['red_units'][0],world['blue_units'][0])),'DSH plans execute repeated native fire')
        else:
            check('afsim' not in world and world['dsh_execution']['effects_source']=='dsh_model_estimate','DSH-only does not claim native effects')
            check(all(u['personnel']['casualties']>0 for u in (world['red_units'][0],world['blue_units'][0])),'DSH-only estimates both engaged sides')
        result[engine+'_session']=auto
    # Upgrade an owned pre-revision QA export, never a user save.
    document=call('GET','/api/sessions/333373e932c6/export',origin='http://127.0.0.1:18993')
    document['session']['id']=uuid.uuid4().hex[:12]
    legacy=call('POST','/api/sessions/import',{'export':document})['session_id']
    previous=call('GET','/api/sessions/'+legacy);view,rev=revision(legacy)
    old={u['name']:u['personnel']['casualties'] for side in ('red','blue') for u in previous['war_state'][side+'_units']}
    check(sum(old.values())>0,'pre-revision QA export contains unclassified combat losses')
    orders=[{'unit_id':u['id'],'action':'hold','duration':'next'} for u in view['units']]
    view=call('PUT','/api/sessions/'+legacy+'/commands',{**rev,'orders':orders,'control_team':'red','director':True,
        'no_fire':False,'intent':'升级旧账，不重写既有伤亡','unit_agents':[]})
    _,rev=revision(legacy)
    upgraded=call('POST','/api/sessions/'+legacy+'/next',{**rev,'batch_id':uuid.uuid4().hex});save('legacy-upgrade',upgraded)
    for side in ('red','blue'):
        for u in upgraded['war_state'][side+'_units']:
            p=u['personnel']
            check(p['unclassified_casualties']==old[u['name']] and p['killed']==0 and p['wounded']==0,
                  u['name']+' old casualties preserved as unknown, not invented deaths')
    check(upgraded['war_state']['combat_reference']['version']==combat_effects.PROFILE['version'],'legacy upgrade freezes current fire reference')
    result.update(passed=True,legacy_session=legacy);save('result',result)
except Exception as exc:
    result['error']=str(exc);save('result',result);raise
