"""Continue the generated local world until all sourced leaves can act together."""
import argparse
import json
from pathlib import Path
import urllib.request
import urllib.error
import uuid


def main():
    p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');p.add_argument('--port',type=int,default=19097)
    p.add_argument('--review-committed',action='store_true',help='Review an already committed final round without running it twice');a=p.parse_args()
    if not a.live or not 19090<=a.port<=19110:p.error('Use --live with isolated QA service')
    root=Path('.cache/qa/wanjialing-sources-2026-10-31/build');sid=json.loads((root/'result.json').read_text())['session_id']
    base=f'http://127.0.0.1:{a.port}/api/sessions/{sid}';result={'passed':False,'session_id':sid,'scope':'Estimated arrivals and local parameters; not historical clock/force calibration'}
    def call(method,path,body=None):
        req=urllib.request.Request(base+path,method=method,headers={'Content-Type':'application/json'},data=None if body is None else json.dumps(body,ensure_ascii=False).encode())
        try:
            with urllib.request.urlopen(req,timeout=1200) as r:return json.load(r)
        except urllib.error.HTTPError as e:raise RuntimeError(str(e.code)+': '+e.read().decode()[:2000]) from e
    def rev(v):return dict(expected_turn=v['turn'],revision=v['revision'],world_version=v['world_version'])
    def save(name,value):(root/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2))
    def check(s):
        units=s['war_state']['red_units']+s['war_state']['blue_units'];assert len(units)==6
        for u in units:
            p=u['personnel'];assert p['committed']==p['current']+p['casualties']+p['noncombat_losses']
            assert all(e['committed']==e['operational']+e['damaged']+e['destroyed'] for e in u['equipment'])
    try:
        if a.review_committed:
            s=json.loads((root/'all-active-combat.json').read_text());assert call('GET','')['war_state']==s['war_state'];check(s)
            turn=s['turn_count'];latest=call('GET',f'/unit-decisions?start_turn={turn}&end_turn={turn}&limit=100')['items']
            waits=call('GET',f'/unit-decisions?start_turn=3&end_turn={turn-1}&limit=200')['items']
            assert len(latest)==6 and all(d['action']=='fire' for d in latest)
            assert sum(bool(d.get('task_context')) for d in latest)==2
            assert len(waits)==(turn-3)*6 and all(d['action']=='hold' for d in waits)
            assert len(s['afsim']['orders'])==6 and all(o['action']=='fire' for o in s['afsim']['orders'])
            result.update(passed=True,reviewed_committed=True,wait_rounds=turn-3,final_turn=turn,time=s['war_state']['current_time'],
                losses={t:sum(u['personnel']['casualties'] for u in s['war_state'][t+'_units']) for t in ('red','blue')},fires=6,task_receipts=2)
            print('PASS reviewed existing committed round, 90 waiting receipts, six fire receipts and two group task contexts; no repeat execution',flush=True)
            return
        before=call('GET','');assert before['turn_count']==2,'Run after the verified contact round'
        frozen=before['war_state']['historical_initial'];ids={u['historical_unit_id'] for u in before['war_state']['red_units']+before['war_state']['blue_units']};rounds=[]
        for _ in range(48):
            v=call('GET','/commands')
            if all(u['capabilities']['arrival']['status']=='active' for u in v['units']):break
            call('PUT','/commands',{**rev(v),'control_team':'red','director':True,'no_fire':False,
                'intent':'等待显式估计的入场窗口，不修改史料或刷新满编','orders':[{'unit_id':u['id'],'action':'hold','duration':'next'} for u in v['units']]})
            v=call('GET','/commands');s=call('POST','/next',{**rev(v),'batch_id':uuid.uuid4().hex});check(s)
            assert s['war_state']['historical_initial']==frozen
            assert {u['historical_unit_id'] for u in s['war_state']['red_units']+s['war_state']['blue_units']}==ids
            rounds.append({'turn':s['turn_count'],'time':s['war_state']['current_time']})
        v=call('GET','/commands');assert all(u['capabilities']['arrival']['status']=='active' for u in v['units'])
        blue=next(u for u in v['units'] if u['team']=='blue');red=[u for u in v['units'] if u['team']=='red']
        org=call('GET','/force-organization');names={'第159师','第161师万家岭投入部'}
        org=call('POST','/force-organization/detach',{**rev(v),'organization_revision':org['revision'],
            'unit_ids':[u['id'] for u in red if u['name'] in names],'label':'第66军方向投入群','assumption':'依据所选1.1.0第119页任务，临时组织两个已配置投入部；不改全161师行政隶属。'})
        group=org['groups'][-1]['id'];v=call('GET','/commands')
        plan=call('POST','/force-organization/task-preview',{**rev(v),'organization_revision':org['revision'],'group_id':group,
            'task':{'kind':'assault','target_id':blue['id'],'destination':blue['position']}})
        call('POST','/force-organization/tasks',{**rev(v),'organization_revision':org['revision'],'group_id':group,
            'task':{'kind':'assault','target_id':blue['id'],'destination':blue['position']},'preview_hash':plan['preview_hash']})
        v=call('GET','/commands');fields={'id','unit_id','action','duration','destination','target_id','end_turn','air_pool'}
        queued={o['unit_id']:o for o in v['orders']};orders=[]
        for u in v['units']:
            assert 'fire' in u['capabilities']['actions']
            if u['id'] in queued:orders.append({k:val for k,val in queued[u['id']].items() if k in fields})
            else:orders.append(dict(unit_id=u['id'],action='fire',target_id=blue['id'] if u['team']=='red' else red[0]['id'],duration='next'))
        call('PUT','/commands',{**rev(v),'control_team':'red','director':True,'no_fire':False,'intent':'全部6单位实际交战；66军方向临时分工回执保留','orders':orders})
        v=call('GET','/commands');s=call('POST','/next',{**rev(v),'batch_id':uuid.uuid4().hex});save('all-active-combat',s);check(s)
        assert all(o['action']=='fire' for o in s['afsim']['orders']),s['afsim']['orders']
        assert len(s['afsim']['orders'])==6
        assert s['war_state']['historical_initial']==frozen
        decisions=call('GET',f'/unit-decisions?start_turn={s["turn_count"]}&end_turn={s["turn_count"]}&limit=100')['items']
        latest=[d for d in decisions if d['turn']==s['turn_count']]
        assert len(latest)==6 and sum(bool(d.get('task_context')) for d in latest)==2
        result.update(passed=True,wait_rounds=len(rounds),rounds=rounds,final_turn=s['turn_count'],time=s['war_state']['current_time'],
            losses={t:sum(u['personnel']['casualties'] for u in s['war_state'][t+'_units']) for t in ('red','blue')},
            fires=len(s['afsim']['orders']),task_receipts=2)
        print('PASS staged arrivals without reset, all six native fire orders, source-based temporary group and six decision receipts',flush=True)
    finally:save('activation-result',result);print('Evidence:',root,flush=True)


if __name__=='__main__':main()
