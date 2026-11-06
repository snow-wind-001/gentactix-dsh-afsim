"""Real DSH/AFSIM range agreement and a preserved legacy-warning import."""
import argparse
import copy
import json
from pathlib import Path
import urllib.request
import urllib.error
import uuid

from tools.qa.historical_operational_fixture import BATTLE, inputs


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',action='store_true')
    p.add_argument('--port',type=int,default=18998)
    p.add_argument('--resume-session',help='Resume the preserved turn-zero QA world after a driver failure')
    args=p.parse_args()
    if not args.live or not 18900<=args.port<=18999:p.error('Use --live with an isolated QA service')
    root=Path('.cache/qa/weapon-ranges');base=f'http://127.0.0.1:{args.port}'
    result={'passed':False,'checks':[],'historical_fit_verified':False}
    def save(name,v):(root/(name+'.json')).write_text(json.dumps(v,ensure_ascii=False,indent=2))
    def check(ok,label):
        if not ok:raise AssertionError(label)
        result['checks'].append(label);print('PASS',label,flush=True)
    def call(method,path,value=None):
        r=urllib.request.Request(base+path,method=method,headers={'Content-Type':'application/json'},
            data=None if value is None else json.dumps(value,ensure_ascii=False).encode())
        with urllib.request.urlopen(r,timeout=1200) as response:return json.load(response)
    def rev(v):return {'expected_turn':v['turn'],**{k:v[k] for k in ('revision','world_version')}}
    try:
        check(not call('GET','/api/health')['build']['restart_required'],'fresh source API')
        _,params=inputs();red=params['actors']['ww2.cn.division31'];red.update(type='炮兵',attack_range_m=800)
        red['formation']['role']='support';red['assumption']+='；本次炮兵聚合与800米自卫范围为QA参数，非第31师实际编制。'
        target=params['actors']['ww2.jp.seya_detachment'];target['position']={**red['position'],'lat':red['position']['lat']+.04}
        params['goal']['deadline_turn']=8
        if args.resume_session:
            sid=args.resume_session;initial=call('GET',f'/api/sessions/{sid}')
            frozen=json.loads((root/'initial.json').read_text())
            check(initial['turn_count']==0 and initial['war_state']==frozen['war_state'],'driver failure left the original QA world unchanged')
        else:
            sid=call('POST','/api/sessions',{'scenario':'武器射程契约QA；引用真实单位ID，人员、编组、射程与位置为显式估计',
                'battle':BATTLE,'product_mode':'historical','execution_backend':'afsim','historical_parameters':params,'persist_roles':False})['session_id']
            initial=call('POST',f'/api/sessions/{sid}/init');save('initial',initial)
        result['session_id']=sid
        v=call('GET',f'/api/sessions/{sid}/commands');u=next(x for x in v['units'] if x['team']=='red');t=next(x for x in v['units'] if x['name']=='日军濑谷支队')
        check(u['capabilities']['weapon_limits_m']['fire']['max_range_m']==800 and u['capabilities']['weapon_limits_m']['bombard']=={'min_range_m':300,'max_range_m':12000},'command metadata separates self-defense and indirect fire')
        for action,valid in (('fire',False),('bombard',True)):
            v=call('GET',f'/api/sessions/{sid}/commands')
            payload={**rev(v),'orders':[{'unit_id':u['id'],'action':action,'target_id':t['id'],'duration':'next'}]}
            try:
                evaluation=call('PUT',f'/api/sessions/{sid}/commands',payload)
                check(valid,action+' accepted as an in-range queued command')
            except urllib.error.HTTPError as exc:
                detail=exc.read().decode();evaluation={'status':exc.code,'detail':detail}
                check(not valid and exc.code==422 and '射程' in detail,action+' is rejected before execution')
            save('queue-'+action,evaluation)
            check(call('GET',f'/api/sessions/{sid}')['war_state']==initial['war_state'],action+' queue validation does not execute a turn')
        v=call('GET',f'/api/sessions/{sid}/commands')
        orders=[{'unit_id':x['id'],'action':'hold','duration':'next'} for x in v['units'] if x['team']=='blue']
        call('PUT',f'/api/sessions/{sid}/commands',{**rev(v),'orders':orders,'control_team':'red','director':True,'no_fire':False,'unit_agents':[]})
        v=call('GET',f'/api/sessions/{sid}/commands')
        after=call('POST',f'/api/sessions/{sid}/next',{**rev(v),'batch_id':uuid.uuid4().hex,
            'instruction':'实际调用get_afsim_observation读取单位及weapon_limits_m。蓝方已人工待命，红方对日军濑谷支队实施远程火力任务，正确选择可覆盖当面距离的武器动作。先evaluate_action校验，不要用自卫fire代替间接炮击；不虚构历史战果。'})
        save('planned-turn',after);w=after['war_state'];order=next(o for o in w['afsim']['orders'] if o['unit']==u['name'])
        check(order['action']=='bombard' and not w['afsim']['model_skipped'],'real DSH selects indirect fire then native AFSIM executes')
        gun=next(x for x in w['red_units'] if x['name']==u['name']);receipt=gun['formation']['last_execution']
        check(receipt['fire_cycles']>0 and receipt['shots']>0 and receipt['active_fire_s']>0,'actual native firing cycles and shell expenditure returned')
        event=next(e for e in w['engagements'] if e['attacker']==u['name'])
        from gentactix.viz import resolve_engagement_radius
        check(event['weapon_action']=='bombard' and resolve_engagement_radius(event,w,event['lat'],event['lng'])[0]==14400,'committed artillery event renders from 12km indirect range')
        before=copy.deepcopy(w)
        answer=call('POST',f'/api/sessions/{sid}/chat',{'message':'调用get_afsim_observation/get_afsim_changes核对本轮。简短说明红方fire自卫与bombard炮击各自范围、最小间瞄射程、本轮实际动作、火力周期和弹耗；实际执行与历史标定分开。不要写权威状态。'})
        save('analysis',answer)
        check(answer['war_state']==before and answer['engine_meta']['finish_reason']=='completed','real DSH reads actual ranges and firing evidence without mutation')
        old=json.loads(Path('.cache/qa/korean-first/runtime/sessions/44cf8714ebe2.json').read_text())
        preview=call('POST','/api/sessions/import/preview',{'export':old});check(not preview['conflict'],'owned old QA save previews without overwriting another session')
        imported=call('POST','/api/sessions/import',{'export':old});legacy=call('GET',f'/api/sessions/{imported["session_id"]}/commands');save('legacy-commands',legacy)
        row=next(x for x in legacy['units'] if x['name']=='美第99野战炮兵营C连')
        check(row['capabilities']['weapon_warnings'] and row['attack_range']==8000,'legacy warning is visible while its frozen range is preserved')
        restored=call('GET',f'/api/sessions/{imported["session_id"]}')
        check(restored['war_state']==old['session']['war_state'],'imported QA world and casualties remain exactly unchanged')
        result.update(passed=True,legacy_session_id=imported['session_id'],receipt=receipt)
    except Exception as exc:result['error']=str(exc);raise
    finally:save('result',result)


if __name__=='__main__':main()
