"""Live motion-v3 branch, bounded DSH observation, and native unit-role review."""
import argparse
import copy
import json
from pathlib import Path
import urllib.request
import uuid


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--live',action='store_true');p.add_argument('--stage',choices=['compare','observe','agent'],required=True)
    args=p.parse_args()
    if not args.live:p.error('Use --live only against the owned isolated QA service')
    root=Path('.cache/qa/shared-baseline');checks=[];out={'passed':False,'checks':checks}
    def call(method,path,data=None):
        req=urllib.request.Request('http://127.0.0.1:18998'+path,method=method,headers={'Content-Type':'application/json'},
            data=None if data is None else json.dumps(data,ensure_ascii=False).encode())
        with urllib.request.urlopen(req,timeout=1200) as r:return json.load(r)
    def check(v,s):
        if not v:raise AssertionError(s)
        checks.append(s);print('PASS',s,flush=True)
    def save(name,v):(root/(name+'.json')).write_text(json.dumps(v,ensure_ascii=False,indent=2))
    def revision(v):return {'expected_turn':v['turn'],**{k:v[k] for k in ('revision','world_version')}}
    try:
        check(not call('GET','/api/health')['build']['restart_required'],'live backend uses current source')
        sid='ba36ec26585a' if args.stage=='observe' else json.loads((root/'fuel-2000.json').read_text())['session_id']
        snap=call('GET',f'/api/sessions/{sid}');before=copy.deepcopy(snap['war_state']);out['session_id']=sid
        v=call('GET',f'/api/sessions/{sid}/commands')
        if args.stage=='compare':
            target=next(u for u in v['units'] if u['name']=='蓝方演习装甲队')
            result=call('POST',f'/api/sessions/{sid}/commands/compare',{**revision(v),'turn':1,
                'orders':[{'unit_id':target['id'],'action':'hold','duration':'next'}]})
            save('motion3-counterfactual',result)
            old=json.loads((root/'fuel-2000.json').read_text())['initial']['war_state']
            native=next(u for u in before['blue_units'] if u['name']==target['name'])
            alternative=next(u for u in result['alternative']['blue_units'] if u['name']==target['name'])
            initial=next(u for u in old['blue_units'] if u['name']==target['name'])
            check(alternative['lat']==initial['lat'] and alternative['lng']==initial['lng'],'motion-v3 hold branch does not move')
            check(native['formation']['fuel_liters']==1998 and alternative['formation']['fuel_liters']==2000,'native branch retains fuel while actual move consumed two liters')
            check(call('GET',f'/api/sessions/{sid}')['war_state']==before,'native counterfactual does not change main state')
        elif args.stage=='observe':
            response=call('POST',f'/api/sessions/{sid}/chat',{'message':'实际get_afsim_observation核对本局登记单位总数与返回列表是否完整。区分登记列表完整、完整历史编制、以及传感器发现这三件事。再用get_afsim_changes核对蓝方演习装甲队：初末燃油、本轮真实位移、与目标剩余距离、命令完成状态及其判定依据。简短回答，只读，不改局。'})
            save('roster-motion-analysis',response)
            check(response['engine_meta']['finish_reason']=='completed' and response['war_state']==before,'native DSH reviews complete registered list and fuel-limited motion without mutation')
            out['answer']=response['chat_messages'][-1]['content']
        else:
            target=next(u for u in v['units'] if u['name']=='红方演习火力队')
            orders=[{'unit_id':u['id'],'action':'hold','duration':'next'} for u in v['units'] if u['id']!=target['id']]
            call('PUT',f'/api/sessions/{sid}/commands',{**revision(v),'orders':orders,'control_team':'red','director':True,
                'no_fire':True,'unit_agents':[target['id']],'intent':'本回合停止攻击，所选演习火力队保留弹药原地待命；其余三编组已有人工待命。'})
            v=call('GET',f'/api/sessions/{sid}/commands')
            response=call('POST',f'/api/sessions/{sid}/next',{**revision(v),'batch_id':uuid.uuid4().hex})
            save('native-unit-agent',response)
            decisions=call('GET',f'/api/sessions/{sid}/unit-decisions?start_turn=2&end_turn=2&limit=50');save('native-unit-decisions',decisions)
            row=next(r for r in decisions['items'] if r['unit_name']==target['name'])
            check(row['source']=='native_unit_agent' and row['action']=='hold','added formation is controlled by an actual native DSH unit Agent')
            check(response['war_state']['historical_initial']==before['historical_initial'],'native unit Agent cannot rewrite frozen history')
            units=response['war_state']['red_units']+response['war_state']['blue_units']
            check(response['turn_count']==2 and len(units)==4 and all(u['personnel']['casualties']==0 for u in units),'unit-role round retains roster, selected clock and no-fire effects')
            out['receipt']=row
        out['passed']=True
    except Exception as exc:out['error']=str(exc);raise
    finally:save('native-'+args.stage+'-result',out)


if __name__=='__main__':main()
