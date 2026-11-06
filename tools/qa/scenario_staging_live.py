"""Accept a normal-UI staged build through real DSH planning and native turns."""
import argparse
import copy
import json
from pathlib import Path
import urllib.error
import urllib.request
import uuid

from gentactix import missions


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',action='store_true');p.add_argument('--session',required=True)
    args=p.parse_args()
    if not args.live:raise SystemExit('Use --live with isolated UI-created session')
    root=Path('.cache/qa/scenario-staging');base='http://127.0.0.1:18997';sid=args.session;checks=[]
    result={'passed':False,'session_id':sid,'checks':checks,'scope':'Six sourced identities with explicit QA estimates; not full historical campaign acceptance'}
    def save(name,value):(root/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2))
    def call(method,path,data=None):
        request=urllib.request.Request(base+path,method=method,headers={'Content-Type':'application/json'},data=None if data is None else json.dumps(data,ensure_ascii=False).encode())
        try:
            with urllib.request.urlopen(request,timeout=1200) as r:return json.load(r)
        except urllib.error.HTTPError as exc:raise RuntimeError(str(exc.code)+': '+exc.read().decode()[:1600]) from exc
    def check(ok,label):
        if not ok:raise AssertionError(label)
        checks.append(label);print('PASS',label,flush=True)
    def view():
        v=call('GET',f'/api/sessions/{sid}/commands')
        return v,{'expected_turn':v['turn'],**{k:v[k] for k in ('revision','world_version')}}
    def advance(orders=None,instruction=''):
        v,revision=view()
        if orders is not None:
            call('PUT',f'/api/sessions/{sid}/commands',{**revision,'orders':orders,'control_team':'red','director':True,'no_fire':False,'unit_agents':[],'intent':instruction})
            v,revision=view()
        snap=call('POST',f'/api/sessions/{sid}/next',{**revision,'batch_id':uuid.uuid4().hex,'instruction':instruction})
        save('turn'+str(snap['turn_count']),snap)
        world=snap['war_state'];assert world['historical_initial']==initial['war_state']['historical_initial']
        for side in ('red','blue'):
            for u in world[side+'_units']:
                a=u['personnel'];assert a['committed']==a['current']+a['casualties']+a['noncombat_losses']
                assert a['casualties']==sum(a[k] for k in ('killed','wounded','missing','captured','unclassified_casualties'))
                assert all(e['committed']==e['operational']+e['damaged']+e['destroyed'] for e in u['equipment'])
        return snap
    try:
        check(not call('GET','/api/health')['build']['restart_required'],'current source backend')
        initial=call('GET',f'/api/sessions/{sid}');save('initial',initial)
        draft=json.load(open(root/'draft.json'))
        check(initial['turn_count']==0 and initial['war_state']['afsim']['entity_count']==6,'normal UI initializes six native actors')
        check(draft['construction']['workflow']=='native_agent_registry_scoped_drafts' and len(draft['construction']['stages'])==4,'actual scoped native configuration hierarchy')
        snap=advance(instruction='读取真实初态和工具约束，双方全部可行动单位逐项下令。红方685、686、687按射程接敌，688预备。蓝方至少一支辎重队明确移动脱离，另一支合理掩护或反击，不得漏交蓝方。不得提前叙述未来，不强制历史战果。')
        check(not snap['war_state']['afsim']['model_skipped'] and len(snap['war_state']['afsim']['orders'])==6,'real DSH plans all six actors through actual tools')
        blue={u['name'] for u in snap['war_state']['blue_units']}
        check(any(o['unit'] in blue and o['action']=='move' for o in snap['war_state']['afsim']['orders']),'blue convoy responds to global withdrawal instruction')
        v,_=view();mover=next(u for u in snap['war_state']['red_units'] if u['historical_unit_id']=='ww2.cn.regiment688')
        point={'lat':mover['lat']+.0005,'lng':mover['lng']}
        orders=[{'unit_id':u['id'],'action':'move' if u['name']==mover['name'] else 'hold','duration':'next',
                 **({'destination':point} if u['name']==mover['name'] else {})} for u in v['units']]
        snap=advance(orders,'可视化选点对应的明确单位移动验收')
        moved=next(u for u in snap['war_state']['red_units'] if u['name']==mover['name'])
        check(abs(moved['lat']-point['lat'])<1e-5 and abs(moved['lng']-point['lng'])<1e-5,'selected zero-fuel foot unit reaches ordered map location')
        factual=copy.deepcopy(snap['war_state']);v,rev=view();identity=next(u['id'] for u in v['units'] if u['name']==mover['name'])
        branch=call('POST',f'/api/sessions/{sid}/commands/compare',{**rev,'turn':2,'orders':[{'unit_id':identity,'action':'hold','duration':'next'}]});save('counterfactual',branch)
        alt=next(u for u in branch['alternative']['red_units'] if u['name']==mover['name'])
        check(abs(alt['lat']-mover['lat'])<1e-5 and abs(alt['lat']-moved['lat'])>.0003,'same-profile read-only command change causes different native position')
        check(call('GET',f'/api/sessions/{sid}')['war_state']==factual,'counterfactual preserves authoritative world')
        for turn in range(3,13):
            v,_=view();by_name={u['name']:u for u in v['units']};world=snap['war_state'];orders=[]
            for u in world['red_units']+world['blue_units']:
                if u['personnel']['current']<=0:continue
                action='resupply' if turn==6 else 'recon' if turn==7 else 'restore_comms' if turn==10 else 'hold'
                order={'unit_id':by_name[u['name']]['id'],'action':action,'duration':'next'}
                if turn in (3,4,5,8,9) and u['historical_unit_id']!='ww2.cn.regiment688':
                    team=by_name[u['name']]['team'];enemies=[x for x in world['blue_units' if team=='red' else 'red_units'] if x['personnel']['current']>0]
                    if enemies:
                        target=min(enemies,key=lambda x:missions.distance(u,x));distance=missions.distance(u,target)
                        if distance*1000<=u['attack_range'] and u['logistics']['ammo']>0:order.update(action='fire',target_id=by_name[target['name']]['id'])
                        elif turn in (3,4,5):
                            ratio=min(1,.3/distance);order.update(action='move',destination={k:u[k]+(target[k]-u[k])*ratio for k in ('lat','lng')})
                orders.append(order)
            snap=advance(orders,'接敌、交火、补给、侦察与恢复通信；开放推演不预设历史结果')
            check(snap['turn_count']==turn,f'turn{turn} native clock and personnel/equipment continuity')
        check(snap['war_state']['simulation_clock']['elapsed_seconds']==21600 and snap['war_state']['mission']['status']=='completed','six-hour ground window ends by program objective')
        factual=copy.deepcopy(snap['war_state'])
        chat=call('POST',f'/api/sessions/{sid}/chat',{'message':'调用原生工具读取当前六个历史单位，简要核对人员战损分类、当前位置与初态的区别、火力时长复核和13时计算窗口。说明哪些是模型估计，不将读到史料等同完成历史效能标定。'});save('observation',chat)
        check(chat['war_state']==factual and chat['engine_meta']['finish_reason']=='completed','actual DSH observes final native state without mutation')
        result.update(passed=True,final_turn=snap['turn_count'],totals={side:sum(u['personnel']['casualties'] for u in snap['war_state'][side+'_units']) for side in ('red','blue')})
        save('result',result)
    except Exception as exc:
        result['error']=str(exc);save('result',result);raise


if __name__=='__main__':main()
