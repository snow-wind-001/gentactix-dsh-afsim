"""Actual native firing cadence/resource/ledger acceptance; not historical replay."""
import argparse
import copy
import json
from pathlib import Path
import urllib.error
import urllib.request
import uuid

from tools.qa.historical_operational_fixture import BATTLE, inputs

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--live',action='store_true')
parser.add_argument('--port',type=int,default=18994)
args=parser.parse_args()
if not args.live or not 18900<=args.port<=18999:raise SystemExit('Use --live and isolated QA port')
root=Path('.cache/qa/combat-effects/live');root.mkdir(parents=True,exist_ok=True)
base=f'http://127.0.0.1:{args.port}';result={'passed':False,'scope':'QA numerical assumptions; actual AFSIM, no live model calls','checks':[]}


def call(method,path,data=None):
    request=urllib.request.Request(base+path,method=method,data=None if data is None else json.dumps(data,ensure_ascii=False).encode(),headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(request,timeout=120) as response:return json.load(response)
    except urllib.error.HTTPError as exc:raise RuntimeError(exc.read().decode()) from exc


def save(name,value):(root/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2))
def check(ok,label):
    if not ok:raise AssertionError(label)
    result['checks'].append(label);print('PASS',label,flush=True)


def create(name,step='30分钟',shells=3000,ammo=80,cover=False):
    _,params=inputs();params=copy.deepcopy(params)
    params['clock']['time_step']=step;params['goal']['deadline_turn']=30
    for actor in params['actors'].values():
        actor['formation']['shells']=shells;actor['logistics']['ammo']=ammo
        if cover:actor['formation'].update(entrenchment=90,protection=.9,dispersion_km2=8)
    sid=call('POST','/api/sessions',{'scenario':name+'；火力量级与时间测试，数量和坐标为QA假设，不是史实部署',
        'battle':BATTLE,'product_mode':'historical','execution_backend':'afsim','historical_parameters':params,'persist_roles':False})['session_id']
    initial=call('POST','/api/sessions/'+sid+'/init');save(name+'-initial',initial)
    return sid,initial


def advance(name,sid,initial,fire=True):
    path='/api/sessions/'+sid;view=call('GET',path+'/commands');by_name={u['name']:u for u in view['units']}
    red=next(u for u in view['units'] if u['team']=='red');blue=by_name['日军濑谷支队']
    orders=[{'unit_id':u['id'],'action':'bombard' if fire and u['id'] in (red['id'],blue['id']) else 'hold','duration':'next',
             **({'target_id':blue['id'] if u['id']==red['id'] else red['id']} if fire and u['id'] in (red['id'],blue['id']) else {})} for u in view['units']]
    rev={k:view[k] for k in ('revision','world_version')};rev['expected_turn']=view['turn']
    view=call('PUT',path+'/commands',{**rev,'orders':orders,'control_team':'red','director':True,'no_fire':False,'intent':'持续炮击量级验收','unit_agents':[]})
    rev={k:view[k] for k in ('revision','world_version')};rev.update(expected_turn=view['turn'],batch_id=uuid.uuid4().hex)
    snap=call('POST',path+'/next',rev);world=snap['war_state'];save(name+f'-turn{snap["turn_count"]}',snap)
    if not world['afsim']['model_skipped'] or world['afsim']['combat_revision']!=2:raise AssertionError('Native fire model not used')
    if world['historical_initial']!=initial['war_state']['historical_initial']:raise AssertionError('Historical facts changed')
    for side in ('red','blue'):
        for u in world[side+'_units']:
            p=u['personnel'];assert p['committed']==p['current']+p['casualties']+p['noncombat_losses']
            assert p['casualties']==sum(p[k] for k in ('killed','wounded','missing','captured','unclassified_casualties'))
            assert 0<=u['formation']['combat_damage_remainder']<1
    return snap


def stats(snap):
    return {u['name']:{**{k:u['personnel'][k] for k in ('casualties','killed','wounded','unclassified_casualties')},
        'cycles':u['formation']['last_execution']['fire_cycles'],'rounds':u['formation']['last_execution']['shots'],
        'active_s':u['formation']['last_execution']['active_fire_s'],'stop':u['formation']['last_execution']['fire_stop_reason']}
        for side in ('red','blue') for u in snap['war_state'][side+'_units']}


try:
    check(not call('GET','/api/health')['build']['restart_required'],'current source backend')
    sid,initial=create('sustained');turns=[]
    for _ in range(6):
        snap=advance('sustained',sid,initial);turns.append(stats(snap))
    first,last=turns[0],turns[-1]
    check(all(first[n]['cycles']>1 for n in ('第31师','日军濑谷支队')),'multiple real volleys within one turn')
    check(snap['war_state']['simulation_clock']['elapsed_seconds']==10800,'three hours of authoritative native time')
    check(all(last[n]['casualties']>first[n]['casualties'] for n in ('第31师','日军濑谷支队')),'sustained exposure accumulates losses on both sides')
    check(all(last[n]['killed']>0 and last[n]['wounded']>0 for n in ('第31师','日军濑谷支队')),'death and wounds recorded separately as estimates')
    result.update(sustained_session=sid,three_hour_history=turns)
    hour,hour_initial=create('hour','1小时');hour_stats=stats(advance('hour',hour,hour_initial))
    check(hour_stats['第31师']['rounds']>first['第31师']['rounds']*1.7,'one hour fires more than one half-hour instead of one arbitrary event')
    check(hour_stats['日军濑谷支队']['casualties']>first['日军濑谷支队']['casualties'],'longer actual firing increases effects')
    for unit in ('第31师','日军濑谷支队'):
        split=turns[1][unit]['casualties'];whole=hour_stats[unit]['casualties']
        check(abs(split-whole)<=max(3,whole*.15),unit+' one hour and two half-hours agree within repeated-command delay tolerance')
    low,low_initial=create('low-ammo',ammo=3);low_stats=stats(advance('low-ammo',low,low_initial))
    check(low_stats['第31师']['cycles']==3 and low_stats['第31师']['stop']==8,'workload depletion stops sustained fire')
    tiny,tiny_initial=create('five-shells',shells=5);tiny_stats=stats(advance('five-shells',tiny,tiny_initial))
    check(tiny_stats['第31师']['rounds']==5 and tiny_stats['第31师']['cycles']==1,'native rounds never exceed five available shells')
    quiet,quiet_initial=create('no-fire');quiet_stats=stats(advance('no-fire',quiet,quiet_initial,False))
    check(all(u['casualties']==0 and u['cycles']==0 for u in quiet_stats.values()),'no historical quota casualties without combat')
    protected,protected_initial=create('protected',cover=True);protected_stats=stats(advance('protected',protected,protected_initial))
    check(protected_stats['第31师']['casualties']<first['第31师']['casualties'],'fortifications, dispersion and protection reduce losses')
    result.update(passed=True,first_half_hour=first,one_hour=hour_stats,three_hours=last,limited_ammo=low_stats,five_shells=tiny_stats,no_fire=quiet_stats,protected=protected_stats)
    save('result',result);print(json.dumps({'passed':True,'three_hours':last},ensure_ascii=False))
except Exception as exc:
    result['error']=str(exc);save('result',result);raise
