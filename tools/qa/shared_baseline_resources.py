"""Actual fuel intervention and DSH-only operation over one frozen synthetic base."""
import argparse
import copy
import json
from pathlib import Path
import urllib.request
import uuid


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',action='store_true')
    p.add_argument('--fuel',type=int,nargs='+',default=[0,2000]);p.add_argument('--fuel-only',action='store_true')
    p.add_argument('--persistent',action='store_true');p.add_argument('--offset',type=float,default=.001)
    p.add_argument('--tag',choices=['','arrival'],default='');p.add_argument('--analyze-fuel',action='store_true');args=p.parse_args()
    if not args.live:p.error('Use --live with owned isolated QA')
    from gentactix import missions
    root=Path('.cache/qa/shared-baseline');checks=[];out={'passed':False,'checks':checks}
    def save(name,v):(root/((args.tag+'-' if args.tag else '')+name+'.json')).write_text(json.dumps(v,ensure_ascii=False,indent=2))
    def check(v,s):
        if not v:raise AssertionError(s)
        checks.append(s);print('PASS',s,flush=True)
    def call(method,path,data=None):
        req=urllib.request.Request('http://127.0.0.1:18998'+path,method=method,headers={'Content-Type':'application/json'},
            data=None if data is None else json.dumps(data,ensure_ascii=False).encode())
        with urllib.request.urlopen(req,timeout=1200) as r:return json.load(r)
    parent=json.loads((root.parent/'ww2-phases/runtime/scenario-drafts/99d23447185e4b1eb4d22f0a2afac523.json').read_text())
    baseline=copy.deepcopy(parent['configuration']);battle=parent['historical_base']['initial']['definition']['battle']
    def create(config,engine):
        draft=call('POST','/api/scenarios/validate',{'mission_id':'','configuration':config,'parent_draft_id':parent['id'],'execution_backend':engine})
        sid=call('POST','/api/sessions',{'scenario':'同一合成初态的燃油与执行器QA；数值为演习假设',
            'battle':battle,'time_step':'15分钟','product_mode':'synthetic','scenario_draft_id':draft['id'],
            'synthetic_configuration':draft['configuration'],'execution_backend':engine,'persist_roles':False})['session_id']
        return sid,call('POST',f'/api/sessions/{sid}/init')
    def step(sid,move=False):
        v=call('GET',f'/api/sessions/{sid}/commands');r={'expected_turn':v['turn'],**{k:v[k] for k in ('revision','world_version')}}
        target=next(u for u in v['units'] if u['name']=='蓝方演习装甲队')
        world=call('GET',f'/api/sessions/{sid}')['war_state'];unit=next(u for u in world['blue_units'] if u['name']==target['name'])
        orders=[{'unit_id':u['id'],'duration':'until_arrived' if move and args.persistent and u['id']==target['id'] else 'next',**({'action':'move','destination':{'lat':unit['lat']+args.offset,'lng':unit['lng']}}
            if move and u['id']==target['id'] else {'action':'hold'})} for u in v['units']]
        call('PUT',f'/api/sessions/{sid}/commands',{**r,'orders':orders,'control_team':'red','director':True,'no_fire':False,'unit_agents':[]})
        v=call('GET',f'/api/sessions/{sid}/commands');r={'expected_turn':v['turn'],**{k:v[k] for k in ('revision','world_version')}}
        return call('POST',f'/api/sessions/{sid}/next',{**r,'batch_id':uuid.uuid4().hex,
            'instruction':'执行全部已确认待命命令；四个编组均保留，无交战不新增死伤或装备毁损，只估计许可的库存与状态变化，不改历史来源。' if not move else ''})
    try:
        original=call('GET','/api/sessions/ab9e42f20993')['war_state'];fuel=[]
        for amount in args.fuel:
            config=copy.deepcopy(baseline);config['teams']['blue'][1]['fuel_liters']=amount
            sid,first=create(config,'afsim');after=step(sid,move=True);save('fuel-'+str(amount),{'session_id':sid,'initial':first,'after':after})
            old=next(u for u in first['war_state']['blue_units'] if u['name']=='蓝方演习装甲队');new=next(u for u in after['war_state']['blue_units'] if u['name']==old['name'])
            distance=missions.distance(old,new);check((distance<.001 if amount==0 else 0<distance<.082 if amount==1 else .100<distance<.12),'native armor movement reflects '+str(amount)+' liters')
            check(new['formation']['fuel_liters']==(0 if amount<2 else amount-2),'native fuel ledger reflects actual movement')
            check(all(u['personnel']['casualties']==0 for _,u in missions.units(after['war_state'])),'hold/move without fire does not create casualties')
            if args.persistent:
                saved=call('GET',f'/api/sessions/{sid}/commands')
                receipts=call('GET',f'/api/sessions/{sid}/unit-decisions?start_turn=1&end_turn=1&limit=50')['items']
                receipt=next(r for r in receipts if r['unit_name']=='蓝方演习装甲队')
                check(receipt['status']=='completed' and not saved['orders'],'continuous move completes inside the existing 10-meter arrival tolerance')
            if amount<2:
                saved=call('GET',f'/api/sessions/{sid}/commands')
                receipts=call('GET',f'/api/sessions/{sid}/unit-decisions?start_turn=1&end_turn=1&limit=50')['items']
                receipt=next(r for r in receipts if r['unit_name']=='蓝方演习装甲队')
                check('燃油' in receipt['reason'] and '行动未执行' not in receipt['reason'],'actual execution receipt explains fuel-limited progress')
            fuel.append({'fuel_liters':amount,'session_id':sid,'distance_km':distance,'receipt':new['formation']['last_execution']})
        save('fuel-comparison',fuel)
        check(call('GET','/api/sessions/ab9e42f20993')['war_state']==original,'resource comparison does not change the main battle')
        if args.analyze_fuel:
            before=call('GET',f'/api/sessions/{sid}')['war_state']
            analysis=call('POST',f'/api/sessions/{sid}/chat',{'message':'实际get_afsim_observation和get_afsim_changes核对蓝方演习装甲队移动。简短区分收到命令、实际移动、是否到达目的地；列初始与当前燃油和本轮位移，解释blocked=10及回合跨度。燃油系数与部署都是合成演习参数，不是历史车辆实测。只读，不改局。'})
            save('fuel-analysis',analysis)
            check(analysis['war_state']==before and analysis['engine_meta']['finish_reason']=='completed','real DSH reads fuel-limited native motion without modifying it')
        if args.fuel_only:
            out.update(passed=True,fuel=fuel);return
        sid,first=create(baseline,'narrative');save('dsh-only-initial',first)
        check(first['settings']['product_mode']=='synthetic' and not first['war_state'].get('afsim'),'same four-unit synthetic base initializes with AFSIM disabled')
        after=step(sid);save('dsh-only-after',after)
        check(after['war_state']['historical_initial']==first['war_state']['historical_initial'],'real DSH-only execution keeps historical facts')
        check(after['war_state']['current_time']=='1938-03-24 08:15' and len(missions.units(after['war_state']))==4,'real DSH-only execution preserves four units and advances one selected step')
        check(all(u['personnel']['casualties']==0 and all(e['damaged']+e['destroyed']==0 for e in u['equipment']) for _,u in missions.units(after['war_state'])),'real DSH-only all-hold round does not invent losses')
        out.update(passed=True,fuel=fuel,dsh_only_session=sid)
    except Exception as exc:out['error']=str(exc);raise
    finally:save('fuel-result' if args.fuel_only else 'resources-result',out)


if __name__=='__main__':main()
