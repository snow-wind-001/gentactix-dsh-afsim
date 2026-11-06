"""Live clock propagation and four-hour bilateral effects; explicit QA estimates."""
import argparse
import copy
from datetime import datetime
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--live', action='store_true'); p.add_argument('--session', required=True)
    args = p.parse_args()
    if not args.live: p.error('Use --live with the isolated 18998 API')
    from gentactix import missions
    root = Path('.cache/qa/selected-step'); checks = []
    result = {'passed': False, 'checks': checks, 'historical_fit_verified': False}
    def save(name, value):
        (root/(name+'.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2))
    def check(ok, label):
        if not ok: raise AssertionError(label)
        checks.append(label); print('PASS', label, flush=True)
    def call(method, path, value=None, expected=200):
        req = urllib.request.Request('http://127.0.0.1:18998'+path, method=method,
            headers={'Content-Type': 'application/json'}, data=None if value is None else json.dumps(value, ensure_ascii=False).encode())
        try:
            with urllib.request.urlopen(req, timeout=1200) as r: status, answer = r.status, json.load(r)
        except urllib.error.HTTPError as exc: status, answer = exc.code, json.loads(exc.read())
        if status != expected: raise RuntimeError(str(status)+': '+str(answer)[:1600])
        return answer
    def view(sid):
        v = call('GET', f'/api/sessions/{sid}/commands')
        return v, {'expected_turn': v['turn'], **{k: v[k] for k in ('revision','world_version')}}
    def advance(sid, instruction=''):
        _, revision = view(sid)
        return call('POST', f'/api/sessions/{sid}/next', {**revision,'batch_id':uuid.uuid4().hex,'instruction':instruction})
    def orders(sid):
        v, revision = view(sid)
        target = {t: next(u for u in v['units'] if u['team']==t)['id'] for t in ('red','blue')}
        choices = [{'unit_id':u['id'],'duration':'next', **({'action':'fire','target_id':target['blue' if u['team']=='red' else 'red']}
            if 'fire' in u['capabilities']['actions'] else {'action':'hold'})} for u in v['units']]
        call('PUT', f'/api/sessions/{sid}/commands', {**revision,'orders':choices,'control_team':'red','director':True,'no_fire':False,'unit_agents':[]})
    started = time.monotonic()
    try:
        check(not call('GET','/api/health')['build']['restart_required'], 'fresh source service')
        sid = args.session; first = call('GET',f'/api/sessions/{sid}')
        check(first['turn_count']==0 and first['time_step']=='15分钟','UI-created historical session starts at selected 15 minutes')
        save('initial', first)
        frozen = copy.deepcopy(first['war_state']['historical_initial'])
        planned = advance(sid,'真实调用get_afsim_observation读取局部初态，并retrieve_history检索台儿庄建模约束。两个单位双方都原地fire唯一对手，evaluate_action确认可行，不移动、不漏交蓝方。AFSIM负责结果，不套用史料伤亡配额。')
        save('turn1', planned)
        check(len(planned['war_state']['afsim']['orders'])==2 and not planned['war_state']['afsim']['model_skipped'], 'native DSH controls both sides before AFSIM effects')
        check(all(o['action']=='fire' for o in planned['war_state']['afsim']['orders']), 'both actual model orders request fire')
        before = copy.deepcopy(planned['war_state']); v, revision = view(sid)
        comparison = call('POST',f'/api/sessions/{sid}/commands/compare',{**revision,'turn':1,'orders':[
            {'unit_id':u['id'],'action':'hold','duration':'next'} for u in v['units'] if u['team']=='red']})
        save('hold-comparison', comparison)
        check(comparison['alternative']['blue_units'][0]['personnel']['casualties']==0 and before['blue_units'][0]['personnel']['casualties']>0,'withholding fire changes losses instead of enforcing a quota')
        check(call('GET',f'/api/sessions/{sid}')['war_state']==before, 'counterfactual leaves main world unchanged')
        ledger = []
        for turn in range(1,17):
            if turn > 1:
                orders(sid); planned = advance(sid); save('turn'+str(turn),planned)
            world = planned['war_state']; missions.validate(world)
            elapsed = (datetime.fromisoformat(world['current_time'])-datetime.fromisoformat(first['war_state']['current_time'])).total_seconds()
            check(elapsed==turn*900 and world['combat_assessment']['elapsed_seconds']==900, f'turn {turn} advances exactly 900 seconds')
            check(world['historical_initial']==frozen, f'turn {turn} retains frozen historical identity evidence')
            for _, u in missions.units(world):
                a = u['personnel']
                check(a['committed']==a['current']+a['casualties']+a['noncombat_losses'] and a['casualties']==sum(a[k] for k in ('killed','wounded','captured','missing','unclassified_casualties')), f'turn {turn} {u["name"]} personnel and classified loss conservation')
                check(all(e['committed']==e['operational']+e['damaged']+e['destroyed'] for e in u['equipment']), f'turn {turn} {u["name"]} equipment conservation')
            ledger.append({'turn':turn,'clock':world['current_time'],'assessment':world['combat_assessment'],
                'units':[{'name':u['name'],'personnel':u['personnel'],'ammo':u['logistics']['ammo'],'last_execution':u['formation']['last_execution']} for _,u in missions.units(world)]})
        save('ledger',ledger); result['session_id']=sid
        check(world['mission']['status']!='active', '16 selected steps stop at the four-hour local objective deadline')
        check(all(u['personnel']['casualties']>5 for _,u in missions.units(world)), 'large formations under actual bilateral fire do not finish with only a few casualties')
        before = copy.deepcopy(world)
        answer = call('POST', f'/api/sessions/{sid}/chat', {'message':'实际调用get_afsim_observation和get_afsim_changes读取已提交账，并retrieve_history核对台儿庄来源口径。简短表列双方投入、累计阵亡估计、负伤估计、减员与弹药；分别说明累计分钟、最近一轮分钟、选定步长和实际火力时长。说明低损失/停火的具体原因，历史31师近3000与本局不同统计窗口，不强制伤亡。不得写战局。'})
        save('analysis',answer)
        check(answer['engine_meta']['finish_reason']=='completed' and answer['war_state']==before,'native DSH reads and analyzes effects without state mutation')
        _, revision = view(sid)
        call('POST',f'/api/sessions/{sid}/next',{**revision,'batch_id':uuid.uuid4().hex},expected=422)
        check(call('GET',f'/api/sessions/{sid}')['war_state']==before,'deadline prevents extra time or casualty deductions')
        save('final',call('GET',f'/api/sessions/{sid}'))
        result.update(passed=True, seconds=round(time.monotonic()-started,2), totals={u['name']:u['personnel'] for _,u in missions.units(world)})
    except Exception as exc:
        result['error']=str(exc); raise
    finally: save('result',result)


if __name__=='__main__':main()
