"""Actual AFSIM execution over named units and explicit QA assumptions.

This is not full Xuzhou reconstruction or all-campaign acceptance. The fixture
deliberately supplies model counts/positions while preserving source unknowns.
"""
import argparse
import copy
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid

from tools.qa.historical_operational_fixture import BATTLE, inputs

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--port',type=int,default=18992)
parser.add_argument('--live',action='store_true')
parser.add_argument('--automatic',action='store_true',help='Also call actual DSH to plan all named units')
args=parser.parse_args()
if not args.live or not 18900<=args.port<=18999:raise SystemExit('Use --live and isolated QA port')
base=f'http://127.0.0.1:{args.port}';out=Path('.cache/qa/historical-operations/live');out.mkdir(parents=True,exist_ok=True)
checks=[];result={'passed':False,'scope':'named historical units with explicit QA model assumptions; not full historical deployment','checks':checks}


def call(method,path,data=None):
    request=urllib.request.Request(base+path,method=method,headers={'Content-Type':'application/json'},
        data=json.dumps(data,ensure_ascii=False).encode() if data is not None else None)
    try:
        with urllib.request.urlopen(request,timeout=1200) as response:return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'{path}: HTTP {exc.code}: '+exc.read().decode(errors='replace')[:2000]) from exc


def save(name,value):(out/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2))
def check(value,label):
    if not value:raise AssertionError(label)
    checks.append(label);print('PASS',label,flush=True)


def create(label):
    _,params=inputs()
    params['goal']['deadline_turn']=4
    response=call('POST','/api/sessions',{'scenario':label+'；具名单位绑定与显式QA参数，不是完整徐州会战复原',
        'battle':BATTLE,'product_mode':'historical','simulation_mode':'open','execution_backend':'afsim',
        'persist_roles':False,'historical_parameters':params})
    sid=response['session_id'];world=call('POST','/api/sessions/'+sid+'/init')
    save(label+'-initial',world)
    check(world['war_state']['mission']['id'].startswith('HO-'),label+' uses historical input definition, no CA template')
    check(world['war_state']['afsim']['source']=='dsh_native_mcp_controller' and world['war_state']['afsim']['entity_count']==3,label+' three real native entities loaded')
    return sid,world


try:
    check(not call('GET','/api/health')['build']['restart_required'],'fresh source backend')
    sid,initial=create('manual');path='/api/sessions/'+sid
    view=call('GET',path+'/commands');by_name={u['name']:u for u in view['units']}
    orders=[{'unit_id':by_name['第31师']['id'],'action':'fire','target_id':by_name['日军濑谷支队']['id'],'duration':'next'},
            {'unit_id':by_name['日军濑谷支队']['id'],'action':'fire','target_id':by_name['第31师']['id'],'duration':'next'},
            {'unit_id':by_name['日军坂本支队']['id'],'action':'hold','duration':'next'}]
    revision={k:view[k] for k in ('revision','world_version')};revision['expected_turn']=view['turn']
    view=call('PUT',path+'/commands',{**revision,'orders':orders,'control_team':'red','director':True,
        'no_fire':False,'intent':'QA双边明确射击，其余待命','unit_agents':[]})
    revision={k:view[k] for k in ('revision','world_version')};revision.update(expected_turn=view['turn'],batch_id=uuid.uuid4().hex)
    started=time.monotonic();after=call('POST',path+'/next',revision);save('manual-turn',after)
    check(after['war_state']['afsim']['model_skipped'] is True,'complete manual commands skip model')
    check(after['war_state']['afsim']['effects_source'].startswith('afsim-native-'),'AFSIM supplies native personnel/resource effects')
    before_units={u['historical_unit_id']:u for t in ('red','blue') for u in initial['war_state'][t+'_units']}
    after_units={u['historical_unit_id']:u for t in ('red','blue') for u in after['war_state'][t+'_units']}
    check(set(before_units)==set(after_units),'all historical IDs retained')
    check(after_units['ww2.cn.division31']['personnel']['casualties']>0 and
          after_units['ww2.jp.seya_detachment']['personnel']['casualties']>0,'both sides actually suffer native fire effects')
    check(after['war_state']['historical_initial']==initial['war_state']['historical_initial'],'source fact snapshot stays unchanged')
    check(all(u['personnel']['committed']==u['personnel']['current']+u['personnel']['casualties']+u['personnel']['noncombat_losses'] for u in after_units.values()),'personnel accounts conserved')
    check(len(after['war_state']['engagements'])==2,'two actual fire events on existing frontend contract')
    check(all(u['formation']['last_execution']['shots']>0 for u in after_units.values() if u['name']!='日军坂本支队'),'fire orders really execute')
    result.update(manual_session=sid,manual_seconds=round(time.monotonic()-started,2),
        losses={u['name']:u['personnel']['casualties'] for u in after_units.values()})
    view=call('GET',path+'/commands')
    revision={k:view[k] for k in ('revision','world_version')};revision['expected_turn']=view['turn']
    comparison=call('POST',path+'/commands/compare',{**revision,'turn':1,
        'orders':[{'unit_id':by_name['第31师']['id'],'action':'hold','duration':'next'}]})
    save('manual-counterfactual',comparison)
    altered={u['historical_unit_id']:u for t in ('red','blue') for u in comparison['alternative'][t+'_units']}
    check(altered['ww2.jp.seya_detachment']['personnel']['casualties']==0,'withhold red fire removes blue casualties under fixed other orders')
    check(altered['ww2.cn.division31']['personnel']['casualties']==after_units['ww2.cn.division31']['personnel']['casualties'],'unchanged blue fire retains red casualties')
    check(call('GET',path)['war_state']==after['war_state'],'counterfactual never changes main battle')
    if args.automatic:
        auto,first=create('automatic');started=time.monotonic()
        view=call('GET','/api/sessions/'+auto+'/commands')
        revision={k:view[k] for k in ('revision','world_version')};revision.update(expected_turn=view['turn'],batch_id=uuid.uuid4().hex)
        following=call('POST','/api/sessions/'+auto+'/next',{**revision,'instruction':
            '这是参数化QA，不强制史实结果。双方分别根据真实ID作出明确命令；第31师与濑谷支队互相射击，坂本支队保持待命。不得改写数量、来源或名字。'})
        save('automatic-turn',following)
        check(not following['war_state']['afsim']['model_skipped'],'actual DSH plans named-unit orders')
        check(len(following['war_state']['afsim']['orders'])==3,'DSH covers both sides and all three units')
        check(following['war_state']['historical_initial']==first['war_state']['historical_initial'],'DSH cannot overwrite source facts')
        result.update(automatic_session=auto,automatic_seconds=round(time.monotonic()-started,2))
    result['passed']=True;save('result',result)
except Exception as exc:
    result['error']=str(exc);save('result',result);raise
