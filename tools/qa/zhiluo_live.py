"""Opt-in sourced identities + estimated inputs, native fire and DSH observation."""
import argparse
import copy
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--live', action='store_true')
    p.add_argument('--port', type=int, default=18998)
    p.add_argument('--out', type=Path, default=Path('.cache/qa/change-paging'))
    p.add_argument('--resume-session', help='Continue the same owned QA session after a driver failure')
    a = p.parse_args()
    if not a.live or not 18900 <= a.port <= 18999:
        p.error('Use --live with an isolated QA service')
    from gentactix import historical_initial, missions
    root = a.out
    result = {'passed':False, 'checks':[], 'historical_fit_verified':False,
        'scope':'Real source IDs and native execution with explicit QA strength/deployment/effect estimates'}
    def save(name, value):
        (root/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2))
    def check(ok, label):
        if not ok:
            raise AssertionError(label)
        result['checks'].append(label); print('PASS',label,flush=True)
    def call(method, path, value=None):
        req = urllib.request.Request(f'http://127.0.0.1:{a.port}'+path,method=method,
            headers={'Content-Type':'application/json'},
            data=None if value is None else json.dumps(value,ensure_ascii=False).encode())
        try:
            with urllib.request.urlopen(req,timeout=1200) as r:
                return json.load(r)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(str(exc.code)+': '+exc.read().decode()[:1500]) from exc
    def revision(v):
        return {'expected_turn':v['turn'], **{k:v[k] for k in ('revision','world_version')}}
    def advance(sid, instruction=''):
        v = call('GET',f'/api/sessions/{sid}/commands')
        return call('POST',f'/api/sessions/{sid}/next',{**revision(v),'batch_id':uuid.uuid4().hex,'instruction':instruction})
    started = time.monotonic()
    try:
        check(not call('GET','/api/health')['build']['restart_required'],'fresh source API')
        draft = json.loads((root/'zhiluo-draft.json').read_text())
        params = draft['parameters']; battle = draft['initial']['definition']['battle']
        check(draft['construction']['source']=='dsh_native_skill' and draft['validation']['scope']=='native_load',
              'actual DSH skill generated a configuration that AFSIM loaded')
        check(len(params['actors'])==3 and all(u['personnel']==4500 for u in params['actors'].values()),
              'three actual IDs retain explicit QA strength estimates')
        sid = a.resume_session or call('POST','/api/sessions',{'scenario':'直罗镇首轮局部推演QA；编号有出处，人数部署效能为显式估计，不是全战役史实复原。',
            'battle':battle,'product_mode':'historical','execution_backend':'afsim','historical_parameters':params,
            'scenario_draft_id':draft['id'],'persist_roles':False})['session_id']
        result['session_id'] = sid
        initial = (json.loads((root/'zhiluo-initial.json').read_text()) if a.resume_session
                   else call('POST',f'/api/sessions/{sid}/init'))
        save('zhiluo-initial',initial)
        facts = copy.deepcopy(initial['war_state']['historical_initial'])
        check(initial['war_state']['afsim']['entity_count']==3,'three sourced historical actors load as real AFSIM entities')
        check(facts==historical_initial.initial(battle,'first_attack')['historical_initial'],'source facts remain unchanged in the executable configuration')
        after = (json.loads((root/'zhiluo-turn1.json').read_text()) if a.resume_session else
            advance(sid, '先实际读观察。红1、红15军团在本局的两个投入实体分别fire东北军109师；109师fire红1军团。所有三个单位明确目标和公开理由，使用真实ID。不移动，不召唤援军，不重写人员，不强制历史被俘或阵亡。'))
        save('zhiluo-turn1',after)
        check(not after['war_state']['afsim']['model_skipped'] and len(after['war_state']['afsim']['orders'])==3,
              'real DSH plans both sides before native execution')
        main = copy.deepcopy(after['war_state'])
        current = call('GET',f'/api/sessions/{sid}')
        current_before_comparison = copy.deepcopy(current['war_state'])
        completed = current['turn_count']
        v = call('GET',f'/api/sessions/{sid}/commands')
        alternative = call('POST',f'/api/sessions/{sid}/commands/compare',{**revision(v),'turn':1,
            'orders':[{'unit_id':u['id'],'action':'hold','duration':'next'} for u in v['units'] if u['team']=='red']})
        save('zhiluo-counterfactual',alternative)
        check(alternative['alternative']['blue_units'][0]['personnel']['casualties']==0
              and main['blue_units'][0]['personnel']['casualties']>0,
              'withholding red fire changes blue losses without a historical quota')
        check(call('GET',f'/api/sessions/{sid}')['war_state']==current_before_comparison,'counterfactual leaves the main battle unchanged')
        per_turn = []
        for turn in range(1,9):
            if turn>1 and turn<=completed:
                after = json.loads((root/('zhiluo-turn'+str(turn)+'.json')).read_text())
            elif turn>1:
                v = call('GET',f'/api/sessions/{sid}/commands')
                red = [u for u in v['units'] if u['team']=='red']; blue = next(u for u in v['units'] if u['team']=='blue')
                orders = [{'unit_id':u['id'],'action':'fire','target_id':blue['id'] if u['team']=='red' else red[0]['id'],'duration':'next'}
                          if 'fire' in u['capabilities']['actions'] else {'unit_id':u['id'],'action':'hold','duration':'next'} for u in v['units']]
                call('PUT',f'/api/sessions/{sid}/commands',{**revision(v),'orders':orders,'control_team':'red','director':True,'no_fire':False,'unit_agents':[]})
                after = advance(sid); save('zhiluo-turn'+str(turn),after)
            w = after['war_state']; missions.validate(w)
            units = [u for t in ('red','blue') for u in w[t+'_units']]
            for u in units:
                r = u['personnel']
                check(r['committed']==r['current']+r['casualties']+r['noncombat_losses'],str(turn)+' '+u['name']+' personnel conservation')
                check(r['casualties']==sum(r.get(k) or 0 for k in ('killed','wounded','missing','captured','unclassified_casualties')),
                      str(turn)+' '+u['name']+' loss categories conserve')
                check(all(e['committed']==e['operational']+e['damaged']+e['destroyed'] for e in u['equipment']),str(turn)+' '+u['name']+' equipment conservation')
            check(w['historical_initial']==facts,str(turn)+' source identities remain frozen')
            per_turn.append({'turn':turn,'clock':w['current_time'],'units':[{k:copy.deepcopy(u[k]) for k in ('name','personnel','formation','logistics')} for u in units],
                'assessment':w['combat_assessment']})
        save('zhiluo-ledger',per_turn)
        check(after['war_state']['current_time']=='1935-11-21 10:00','eight native rounds advance exactly four hours')
        before = copy.deepcopy(after['war_state'])
        analysis = call('POST',f'/api/sessions/{sid}/chat',{'message':
            '实际调用get_afsim_observation与get_afsim_changes核对本局。简短表格列三单位当前人员、累计阵亡与负伤、有效火力时长与停止原因；'
            '区分四小时历时和实际射击时长，待命单位不能扣历史配额。解释全战役5300余被俘属于哪一种减员、为何不能称为本局阵亡或每小时应杀人数。'
            '本局投入人数和部署明确是QA估计，缺失历史伤亡保留未知。不要改战局。'})
        save('zhiluo-analysis',analysis)
        check(analysis['war_state']==before and analysis['engine_meta']['finish_reason']=='completed',
              'real native DSH observes losses and historical references without mutating the world')
        result.update(passed=True,seconds=round(time.monotonic()-started,2),turns=8,
            totals={u['name']:u['personnel'] for t in ('red','blue') for u in before[t+'_units']})
    except Exception as exc:
        result['error']=str(exc)
        raise
    finally:
        save('zhiluo-result',result)


if __name__=='__main__':
    main()
