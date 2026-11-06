"""Native sustained-fire probe using an explicitly corrected real DSH draft."""
import argparse
import copy
import json
from pathlib import Path
import urllib.error
import urllib.request
import uuid

from gentactix import missions
from tools.qa.korean_first_fixture import BATTLE


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',action='store_true')
    p.add_argument('--port',type=int,default=18998);args=p.parse_args()
    if not args.live or not 18900<=args.port<=18999:p.error('Use --live and an isolated QA port')
    root=Path('.cache/qa/korean-first');out=root/'sustained';out.mkdir(exist_ok=True)
    base=f'http://127.0.0.1:{args.port}';result={'passed':False,'checks':[],'historical_fit_verified':False}
    def save(name,value):(out/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2))
    def call(method,path,value=None):
        request=urllib.request.Request(base+path,method=method,headers={'Content-Type':'application/json'},
            data=None if value is None else json.dumps(value,ensure_ascii=False).encode())
        with urllib.request.urlopen(request,timeout=1200) as response:return json.load(response)
    def check(ok,label):
        if not ok:raise AssertionError(label)
        result['checks'].append(label);print('PASS',label,flush=True)
    def rev(v):return {'expected_turn':v['turn'],**{k:v[k] for k in ('revision','world_version')}}
    try:
        check(not call('GET','/api/health')['build']['restart_required'],'fresh source API')
        original=json.loads((root/'unsan-draft.json').read_text());params=copy.deepcopy(original['parameters'])
        payload={'parent_draft_id':original['id'],'parameters':params,'execution_backend':'afsim'}
        try:call('POST','/api/historical-scenarios/validate',payload)
        except urllib.error.HTTPError as exc:
            message=exc.read().decode();save('rejected-old-range',{'status':exc.code,'detail':message})
            check(exc.code==422 and '直射' in message and '间接' in message,'new configuration rejects the eight-kilometre self-defense range')
        else:raise AssertionError('Invalid artillery self-defense range accepted')
        actor=params['actors']['kw.us.artillery99.battery_c'];actor['attack_range_m']=800
        actor['assumption']+='；复验修正：fire直射自卫范围800米是QA估计，火炮间接射程另由rules.artillery_range_m约束；原8000米混填不再沿用。'
        draft=call('POST','/api/historical-scenarios/validate',payload);save('corrected-draft',draft)
        check(draft['afsim']['entity_count']==9 and draft['afsim']['returncode']==0,'corrected DSH-derived draft actually loads nine native entities')
        sid=call('POST','/api/sessions',{'scenario':'云山持续直射效能QA；估计兵力部署，无历史损失配额',
            'battle':BATTLE,'product_mode':'historical','execution_backend':'afsim','historical_parameters':params,
            'scenario_draft_id':draft['id'],'persist_roles':False})['session_id'];result['session_id']=sid
        snap=call('POST',f'/api/sessions/{sid}/init');save('initial',snap)
        targets={'kw.cn.division115':'kw.us.cavalry8.battalion2','kw.cn.division116':'kw.us.cavalry8.battalion1','kw.cn.division117':'kw.rok.regiment15'}
        for turn in range(1,9):
            w=snap['war_state'];units=list(missions.units(w));by_history={u['historical_unit_id']:u for _,u in units}
            v=call('GET',f'/api/sessions/{sid}/commands');ids={u['name']:u['id'] for u in v['units']};orders=[]
            for team,u in units:
                if u['personnel']['current']<=0:continue
                order={'unit_id':ids[u['name']],'action':'hold','duration':'next'}
                if turn==1 and team=='red':
                    target=by_history[targets[u['historical_unit_id']]]
                    order.update(action='move',destination={k:u[k]+.6*(target[k]-u[k]) for k in ('lat','lng')})
                elif turn>1 and u['logistics']['ammo']>0:
                    enemies=[e for side,e in units if side!=team and e['personnel']['current']>0 and missions.distance(u,e)*1000<=u['attack_range']]
                    if enemies:order.update(action='fire',target_id=ids[min(enemies,key=lambda e:missions.distance(u,e))['name']])
                orders.append(order)
            call('PUT',f'/api/sessions/{sid}/commands',{**rev(v),'orders':orders,'control_team':'red','director':True,'no_fire':False,'unit_agents':[]})
            v=call('GET',f'/api/sessions/{sid}/commands')
            snap=call('POST',f'/api/sessions/{sid}/next',{**rev(v),'batch_id':uuid.uuid4().hex});save('turn'+str(turn),snap)
            for _,u in missions.units(snap['war_state']):
                a=u['personnel'];assert a['committed']==a['current']+a['casualties']+a['noncombat_losses']
                assert a['casualties']==sum(a[k] for k in ('killed','wounded','missing','captured','unclassified_casualties'))
                assert all(e['committed']==e['operational']+e['damaged']+e['destroyed'] for e in u['equipment'])
            check(snap['turn_count']==turn,f'turn{turn} explicit native orders and conserved ledgers')
        w=snap['war_state'];review=w['combat_assessment']['units']
        check(any(r['committed']>=1000 and r['tracked_incoming_max_fire_s']>=7200 for r in review),'large formation actually receives over two hours of firing')
        check(not any('sustained_fire_low_attrition' in r['issues'] for r in review),'no silent low-attrition anomaly under sustained in-range direct fire')
        check(w['simulation_clock']['elapsed_seconds']==14400 and w['current_time'].endswith('21:00'),'four-hour clock respected without forced historical loss quota')
        result.update(passed=True,totals={t:{key:sum(u['personnel'][key] for u in w[t+'_units']) for key in ('casualties','killed','wounded')} for t in ('red','blue')})
    except Exception as exc:result['error']=str(exc);raise
    finally:save('result',result)


if __name__=='__main__':main()
