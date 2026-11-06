"""Real sourced-phase builder, native execution and DSH observation acceptance.

All numerical/deployment inputs remain marked estimates. Uses isolated QA only.
"""
import argparse
import copy
import json
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from gentactix import missions

from tools.qa.pingxingguan_fixture import BATTLE

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--live',action='store_true')
parser.add_argument('--port',type=int,default=18995)
args=parser.parse_args()
if not args.live or not 18900<=args.port<=18999:raise SystemExit('Use --live and isolated QA port')
base=f'http://127.0.0.1:{args.port}';root=Path('.cache/qa/historical-attendance/live');root.mkdir(parents=True,exist_ok=True)
result={'passed':False,'checks':[],'scope':'Sourced identities and published deployment areas; numerical parameters are model estimates, not historical calibration'}


def call(method,path,data=None):
    req=urllib.request.Request(base+path,method=method,headers={'Content-Type':'application/json'},
        data=None if data is None else json.dumps(data,ensure_ascii=False).encode())
    try:
        with urllib.request.urlopen(req,timeout=1200) as response:return json.load(response)
    except urllib.error.HTTPError as exc:raise RuntimeError(str(exc.code)+': '+exc.read().decode()[:1800]) from exc


def save(name,value):(root/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2))
def check(ok,label):
    if not ok:raise AssertionError(label)
    result['checks'].append(label);print('PASS',label,flush=True)


def commands(sid):
    view=call('GET',f'/api/sessions/{sid}/commands')
    return view,{'expected_turn':view['turn'],**{k:view[k] for k in ('revision','world_version')}}


def next_turn(sid,orders=None,instruction=''):
    view,rev=commands(sid)
    if orders is not None:
        view=call('PUT',f'/api/sessions/{sid}/commands',{**rev,'orders':orders,'control_team':'red','director':True,
            'no_fire':False,'unit_agents':[],'intent':instruction})
        view,rev=commands(sid)
    snap=call('POST',f'/api/sessions/{sid}/next',{**rev,'batch_id':uuid.uuid4().hex,'instruction':instruction})
    save('turn'+str(snap['turn_count']),snap)
    return snap


try:
    check(not call('GET','/api/health')['build']['restart_required'],'current source API')
    basis=call('GET','/api/historical-scenarios/basis?'+urllib.parse.urlencode({'battle':BATTLE,'phase_id':'qiaogou'}));save('basis',basis)
    check(basis['ready'] and len(basis['actors'])==6,'six sourced nonoverlapping ground actors')
    check(len(basis['excluded_references'])==3 and basis['execution_window']['end'].endswith('13:00'),'outside and later references retained with model boundary')
    operation=uuid.uuid4().hex;save('build-operation',{'id':operation})
    instruction=('乔沟早间地面窗口，1937-09-25 07:00计算起点，30分钟回合，12回合到13:00截止。'
        'goal.profile=delay，required_survivors=1。人数、武器、部署与库存缺载处按显式模型估计，非完整史实重建。'
        '保留四个红军团和两支日军辎重队6个真实ID；外围独立团、骑兵营与后续日机不提前部署。'
        '红方约团级规模、蓝方为数百人的车队或辎重队，不能全都3000人。'
        '686团必须在其已有来源粗区域内，其他团按部署方位展开；不要落在灵丘县城，不要重叠，不要把双方间距扩大到无法在本窗口接敌。'
        '全体坦克、炮兵、防空数量为0；射击按步兵轻武器，直射范围约800—1200米并明确为估计。'
        '红方formation.motorized=false且fuel_liters=0，运输单元明确为驮运折算；两支日军formation.motorized=true，燃油正值。'
        '双方弹药工作量80，粮食80；source_scope说明蓝方具体武器配属与随行人员缺载。area为乔沟局部15公里内；exit在区域西南边缘，双方不放在exit旁。')
    started=time.monotonic();draft=call('POST','/api/historical-scenarios/build',{'battle':BATTLE,'phase_id':'qiaogou','instruction':instruction,'operation_id':operation,'execution_backend':'afsim'});save('draft',draft)
    check(draft['afsim']['entity_count']==6 and draft['construction']['source']=='dsh_native_skill','real native DSH skill builds and actually loads six entities')
    check(all(p['formation'].get('motorized') is False and p['formation']['fuel_liters']==0 for k,p in draft['parameters']['actors'].items() if k.startswith('ww2.cn.')),'generated red foot units have explicit zero fuel and no motorized pause')
    result['build_seconds']=round(time.monotonic()-started,2)
    sid=call('POST','/api/sessions',{'scenario':'平型关乔沟地面历史单位参数化验收；数值和坐标为显式估计，非完整复原','battle':BATTLE,'product_mode':'historical',
        'execution_backend':'afsim','persist_roles':False,'historical_parameters':draft['parameters'],'scenario_draft_id':draft['id']})['session_id']
    initial=call('POST',f'/api/sessions/{sid}/init');save('initial',initial);result['session_id']=sid
    check(initial['war_state']['afsim']['entity_count']==6,'six actual native actors initialized from staged source IDs')
    snap=next_turn(sid,instruction='读取实际态势；双方每个可行动单位明确下令。红方685、686、687按实际射程选择接敌或射击，688为预备队待命；蓝方两支辎重队分别合理反击或移动脱离，不得因其为蓝方而漏单。')
    check(not snap['war_state']['afsim']['model_skipped'] and len(snap['war_state']['afsim']['orders'])==6,'real DSH observes and plans all six actors on both sides')
    view,_=commands(sid);by_name={u['name']:u for u in view['units']}
    mover=next(u for u in snap['war_state']['red_units'] if u['historical_unit_id']=='ww2.cn.regiment688')
    target={'lat':mover['lat']+.0005,'lng':mover['lng']}
    orders=[{'unit_id':u['id'],'action':'move' if u['name']==mover['name'] else 'hold','duration':'next',
             **({'destination':target} if u['name']==mover['name'] else {})} for u in view['units']]
    snap=next_turn(sid,orders,'徒步单位零燃油短距离行军验收')
    current=next(u for u in snap['war_state']['red_units'] if u['name']==mover['name'])
    check(abs(current['lat']-target['lat'])<1e-5 and abs(current['lng']-target['lng'])<1e-5 and current['formation']['fuel_liters']==0,'zero-fuel foot reserve actually arrives at selected destination')
    for _ in range(2,12):
        view,_=commands(sid)
        turn=snap['turn_count']+1;world=snap['war_state'];positions={u['name']:u for team in ('red','blue') for u in world[team+'_units']}
        by_name={u['name']:u for u in view['units']};orders=[]
        for u in view['units']:
            actor=positions[u['name']]
            if actor['personnel']['current']<=0:continue
            action='resupply' if turn==6 else 'recon' if turn==7 else 'restore_comms' if turn==10 else 'hold'
            order={'unit_id':u['id'],'action':action,'duration':'next'}
            enemies=[v for v in world['blue_units' if u['team']=='red' else 'red_units'] if v['personnel']['current']>0]
            if turn in (3,4,5,8,9) and enemies and actor['historical_unit_id']!='ww2.cn.regiment688':
                target=min(enemies,key=lambda e:missions.distance(actor,e));distance=missions.distance(actor,target)
                if distance*1000<=actor['attack_range']:
                    order.update(action='fire',target_id=by_name[target['name']]['id'])
                elif turn in (3,4,5):
                    ratio=min(1,.3/distance);order.update(action='move',destination={k:actor[k]+(target[k]-actor[k])*ratio for k in ('lat','lng')})
            orders.append(order)
        snap=next_turn(sid,orders,'接敌/交火、补给、侦察与恢复联络的六小时过程；不强制历史战果')
        check(snap['war_state']['historical_initial']==initial['war_state']['historical_initial'],f'turn{snap["turn_count"]} immutable sources')
        for side in ('red','blue'):
            for u in snap['war_state'][side+'_units']:
                p=u['personnel'];assert p['committed']==p['current']+p['casualties']+p['noncombat_losses']
                assert all(e['committed']==e['operational']+e['damaged']+e['destroyed'] for e in u['equipment'])
    check(snap['war_state']['simulation_clock']['elapsed_seconds']==21600,'six hours of authoritative native time')
    check(snap['war_state']['mission']['status']=='completed' and snap['turn_count']==12,'program terminates at declared ground-model boundary')
    check(any(u['personnel']['casualties']>0 for u in snap['war_state']['red_units']) and
          any(u['personnel']['casualties']>0 for u in snap['war_state']['blue_units']),'actual native contact produces bilateral losses')
    factual=copy.deepcopy(snap['war_state'])
    chat=call('POST',f'/api/sessions/{sid}/chat',{'message':'实际读取当前态势，核对6个已装载单位及外围/后续3项参考，简要说明人员装备账、机动方式与13时窗口限制。不要把缺载人数说成史实。'});save('observation',chat)
    check(chat['war_state']==factual,'DSH analysis is read-only over actual native state')
    result.update(passed=True,final_turn=snap['turn_count']);save('result',result)
except Exception as exc:
    result['error']=str(exc);save('result',result);raise
