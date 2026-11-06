"""Replay the prior native fire inputs with classified receipts, then ask DSH."""
import argparse
import copy
import json
from pathlib import Path
import urllib.request
import uuid

from tools.qa.historical_operational_fixture import BATTLE


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',action='store_true')
    p.add_argument('--port',type=int,default=18998);args=p.parse_args()
    if not args.live or not 18900<=args.port<=18999:p.error('Use --live with an isolated QA service')
    root=Path('.cache/qa/weapon-ranges');result={'passed':False,'checks':[],'historical_fit_verified':False}
    def save(name,v):(root/(name+'.json')).write_text(json.dumps(v,ensure_ascii=False,indent=2))
    def check(ok,label):
        if not ok:raise AssertionError(label)
        result['checks'].append(label);print('PASS',label,flush=True)
    def call(method,path,value=None):
        r=urllib.request.Request(f'http://127.0.0.1:{args.port}'+path,method=method,headers={'Content-Type':'application/json'},
            data=None if value is None else json.dumps(value,ensure_ascii=False).encode())
        with urllib.request.urlopen(r,timeout=1200) as f:return json.load(f)
    def rev(v):return {'expected_turn':v['turn'],**{k:v[k] for k in ('revision','world_version')}}
    try:
        check(not call('GET','/api/health')['build']['restart_required'],'fresh source API')
        original=json.loads((root/'initial.json').read_text())['war_state']
        params=original['mission']['definition']['historical_calculation']['parameters']
        sid=call('POST','/api/sessions',{'scenario':'原生分类到货回执QA；沿用前次具名单位的显式QA参数，不是史实效能标定',
            'battle':BATTLE,'product_mode':'historical','execution_backend':'afsim','historical_parameters':params,'persist_roles':False})['session_id']
        result['session_id']=sid;initial=call('POST',f'/api/sessions/{sid}/init');save('supply-initial',initial)
        v=call('GET',f'/api/sessions/{sid}/commands');red=next(u for u in v['units'] if u['team']=='red');target=next(u for u in v['units'] if u['name']=='日军濑谷支队')
        orders=[{'unit_id':u['id'],'action':'bombard' if u['team']=='red' else 'hold','duration':'next',
                 **({'target_id':target['id']} if u['team']=='red' else {})} for u in v['units']]
        call('PUT',f'/api/sessions/{sid}/commands',{**rev(v),'orders':orders,'control_team':'red','director':True,'no_fire':False,'unit_agents':[]})
        v=call('GET',f'/api/sessions/{sid}/commands')
        after=call('POST',f'/api/sessions/{sid}/next',{**rev(v),'batch_id':uuid.uuid4().hex});save('supply-turn',after)
        old=json.loads((root/'planned-turn.json').read_text())['war_state'];w=after['war_state']
        for team in ('red','blue'):
            for prior,current in zip(old[team+'_units'],w[team+'_units']):
                for key in ('personnel','equipment','logistics'):
                    check(prior[key]==current[key],current['name']+' '+key+' matches prior native effect')
        gun=next(u for u in w['red_units'] if u['name']==red['name']);r=gun['formation']['last_execution']
        check(r['shots']==120 and r['received_shells']==24 and gun['formation']['shells']==24,'native shell account: start120 + received24 - fired120 = end24')
        check(r['fire_cycles']==8 and r['active_fire_s']==960 and r['fire_stop_reason']==6,'native firing behavior unchanged while receipt evidence is added')
        before=copy.deepcopy(w)
        a=call('POST',f'/api/sessions/{sid}/chat',{'message':'实际调用get_afsim_observation与get_afsim_changes核对红方回执。用简短等式说明轮初炮弹、实际发射、轮末分类到货、最终库存，以及弹药工作量的前后库存和净变化。解释为何先停止射击后轮末库存又非零；区分命令发生时点和有效火力时长。缺载保持未知，不改战局。'})
        save('supply-analysis',a);check(a['war_state']==before,'real DSH observes classified receipts without mutation')
        text=a['chat_messages'][-1]['content'];check(all(x in text for x in ('120','24','960','80','74')),'real answer includes actual receipt and stock quantities')
        result.update(passed=True,receipt=r)
    except Exception as exc:result['error']=str(exc);raise
    finally:save('supply-result',result)


if __name__=='__main__':main()
