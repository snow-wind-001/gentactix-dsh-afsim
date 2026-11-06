"""Real native decisions, four-unit synthetic effects and read-only analysis."""
import argparse
import copy
from datetime import datetime
import json
from pathlib import Path
import urllib.error
import urllib.request
import uuid


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',action='store_true');p.add_argument('--session',required=True)
    args=p.parse_args()
    if not args.live:p.error('Use --live with isolated QA')
    from gentactix import missions
    root=Path('.cache/qa/shared-baseline');checks=[];result={'passed':False,'session_id':args.session,'checks':checks,'historical_fit_verified':False}
    def save(name,v):(root/(name+'.json')).write_text(json.dumps(v,ensure_ascii=False,indent=2))
    def check(v,s):
        if not v:raise AssertionError(s)
        checks.append(s);print('PASS',s,flush=True)
    def call(method,path,value=None,expected=200):
        req=urllib.request.Request('http://127.0.0.1:18998'+path,method=method,headers={'Content-Type':'application/json'},
            data=None if value is None else json.dumps(value,ensure_ascii=False).encode())
        try:
            with urllib.request.urlopen(req,timeout=1200) as r:status,body=r.status,json.load(r)
        except urllib.error.HTTPError as exc:status,body=exc.code,json.loads(exc.read())
        if status!=expected:raise RuntimeError(str(status)+': '+str(body)[:1800])
        return body
    def view():
        v=call('GET',f'/api/sessions/{sid}/commands');return v,{'expected_turn':v['turn'],**{k:v[k] for k in ('revision','world_version')}}
    def advance(instruction=''):
        _,r=view();return call('POST',f'/api/sessions/{sid}/next',{**r,'batch_id':uuid.uuid4().hex,'instruction':instruction})
    try:
        sid=args.session;first=call('GET',f'/api/sessions/{sid}');save('initial',first)
        check(first['turn_count']==0 and not call('GET','/api/health')['build']['restart_required'],'fresh service and initialized four-unit synthetic session')
        frozen=copy.deepcopy(first['war_state']['historical_initial'])
        check(first['settings']['product_mode']=='synthetic' and len(missions.units(first['war_state']))==4,'actual initial purpose and roster')
        initial_units={u['name']:u for _,u in missions.units(first['war_state'])}
        check(initial_units['蓝方演习装甲队']['formation']['motorized'],'armored formation uses motorized native rules')
        v,revision=view();selected=next(u for u in v['units'] if u['name']=='红方演习火力队')
        proposal=call('POST',f'/api/sessions/{sid}/commands/resolve',{**revision,'selected_units':[selected['id']],
            'text':'所选演习火力队下一回合原地待命。这只是待确认草稿，不要执行。'})
        save('natural-command',proposal)
        check(proposal['status']=='draft' and proposal['orders'][0]['action']=='hold','real natural language resolves selected added formation')
        check(call('GET',f'/api/sessions/{sid}')['war_state']==first['war_state'],'natural language proposal does not execute or alter facts')
        answer=advance('实际get_afsim_observation读取全部4个单位，再evaluate_action验证。是合成演习，新增编组不是新增历史部队。红第31师fire蓝方演习装甲队，红方演习火力队bombard蓝方演习装甲队；蓝濑谷与蓝装甲都fire第31师。所有双方可行动单位各交一条，不移动。AFSIM负责执行，不生成战损，不强制史实结局。')
        save('turn1',answer)
        check(not answer['war_state']['afsim']['model_skipped'] and len(answer['war_state']['afsim']['orders'])==4,'real DSH plans both sides and all added formations')
        check(any(o['action']=='bombard' and o['unit']=='红方演习火力队' for o in answer['war_state']['afsim']['orders']),'real DSH chooses indirect fire for distant added artillery')
        world=answer['war_state'];before=copy.deepcopy(world);v,r=view()
        branch=call('POST',f'/api/sessions/{sid}/commands/compare',{**r,'turn':1,'orders':[
            {'unit_id':u['id'],'action':'hold','duration':'next'} for u in v['units'] if u['team']=='red']})
        save('hold-comparison',branch)
        check(all(u['personnel']['casualties']==0 for u in branch['alternative']['blue_units']),'holding red fire changes blue losses without a history quota')
        check(call('GET',f'/api/sessions/{sid}')['war_state']==before,'native derived counterfactual leaves main state unchanged')
        ledger=[]
        for turn in range(1,17):
            if turn>1:
                v,r=view();world=answer['war_state'];by_name={u['name']:u for _,u in missions.units(world)}
                targets={team:[u for u in v['units'] if u['team']==team and u['capabilities']['enabled']] for team in ('red','blue')}
                choices=[]
                for u in v['units']:
                    if not u['capabilities']['enabled']:continue
                    enemies=targets['blue' if u['team']=='red' else 'red']
                    enemies=sorted(enemies,key=lambda t:t['name']!=('蓝方演习装甲队' if u['team']=='red' else '第31师'))
                    order={'unit_id':u['id'],'action':'hold','duration':'next'}
                    options=u['capabilities']['actions'];limits=u['capabilities'].get('weapon_limits_m',{})
                    for action in (['bombard','fire'] if '火力队' in u['name'] else ['fire']):
                        if action not in options or action not in limits:continue
                        weapon=limits[action]
                        enemy=next((t for t in enemies if weapon['min_range_m']<=missions.distance(by_name[u['name']],by_name[t['name']])*1000<=weapon['max_range_m']),None)
                        if enemy:
                            order.update(action=action,target_id=enemy['id']);break
                    choices.append(order)
                call('PUT',f'/api/sessions/{sid}/commands',{**r,'orders':choices,'control_team':'red','director':True,'no_fire':False,'unit_agents':[]})
                answer=advance();save('turn'+str(turn),answer)
            world=answer['war_state'];missions.validate(world)
            check(world['historical_initial']==frozen and len(missions.units(world))==4,f'turn {turn} keeps source facts and all four entities')
            check(world['simulation_clock']['elapsed_seconds']==turn*900,f'turn {turn} exact configured clock')
            rows=[]
            for _,u in missions.units(world):
                a=u['personnel'];check(a['committed']==a['current']+a['casualties']+a['noncombat_losses'] and a['casualties']==sum(a[k] for k in ('killed','wounded','captured','missing','unclassified_casualties')),f'turn {turn} {u["name"]} classified personnel conservation')
                check(all(e['committed']==e['operational']+e['damaged']+e['destroyed'] for e in u['equipment']),f'turn {turn} {u["name"]} nonnegative equipment accounting')
                rows.append({'name':u['name'],'personnel':a,'equipment':u['equipment'],'last_execution':u['formation']['last_execution']})
            ledger.append({'turn':turn,'clock':world['current_time'],'units':rows})
        save('ledger',ledger)
        check(world['current_time']=='1938-03-24 12:00' and world['mission']['status']!='active','local objective ends at inherited four-hour deadline')
        check(any(e['damaged']+e['destroyed']>0 for _,u in missions.units(world) for e in u['equipment']),'nonzero allocated equipment suffers actual native attrition')
        before=copy.deepcopy(world)
        analysis=call('POST',f'/api/sessions/{sid}/chat',{'message':'实际get_afsim_observation读取全部4单位，沿get_afsim_changes.next_args读完本局从0开始的变化。600字内表列4单位减员、死伤和装甲/火炮毁损及弹耗；指出新增2编组是演习派生，不是新增历史部队，源历史初态与计算参数/改编分开。说明炮击与步兵直射、资源耗尽后待命、240分钟与15分钟单轮，不按史料配额。只读，不改局。'})
        save('analysis',analysis)
        check(analysis['engine_meta']['finish_reason']=='completed' and analysis['war_state']==before,'native DSH analyzes derived native effects without mutation')
        save('final',call('GET',f'/api/sessions/{sid}'))
        result.update(passed=True,totals={u['name']:{'personnel':u['personnel'],'equipment':u['equipment']} for _,u in missions.units(world)})
    except Exception as exc:result['error']=str(exc);raise
    finally:save('result',result)


if __name__=='__main__':main()
