"""Opt-in real skill/build, bilateral orders and native conservation on new phases.

Numerical strength, equipment and placement are QA estimates. This is not
historical calibration or acceptance of a complete campaign order of battle.
Uses the application's native DSH workflow and existing AFSIM API only.
"""
import argparse
import copy
from datetime import datetime
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid

from gentactix import historical_operations as ho, missions, sim_clock
from tools.qa.korean_series_fixture import inputs


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--port',type=int,default=18998)
    parser.add_argument('--cases',nargs='+',default=['KW02-second','KW03-third','KW04-fourth',
        'KW05-fifth','KW06-autumn1951','KW07-counter1952','KW08-sangganling','KW09-summer1953'])
    parser.add_argument('--reuse',action='store_true',help='Continue only the saved owned QA session for each case')
    args=parser.parse_args()
    if not args.live or not 18900<=args.port<=18999:parser.error('Use --live and an isolated QA port')
    root=Path('.cache/qa/korean-series');root.mkdir(parents=True,exist_ok=True)

    def call(method,path,value=None,expected=200):
        request=urllib.request.Request(f'http://127.0.0.1:{args.port}'+path,method=method,
            headers={'Content-Type':'application/json'},
            data=None if value is None else json.dumps(value,ensure_ascii=False).encode())
        try:
            with urllib.request.urlopen(request,timeout=1200) as f:status,answer=f.status,json.load(f)
        except urllib.error.HTTPError as exc:status,answer=exc.code,json.loads(exc.read())
        if status!=expected:raise RuntimeError(str(status)+': '+str(answer)[:1800])
        return answer

    for case in args.cases:
        result={'passed':False,'historical_fit_verified':False,'checks':[]}
        started=time.monotonic()
        def save(label,value):
            (root/(case+'-'+label+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
        def check(value,label):
            if not value:raise AssertionError(label)
            result['checks'].append(label);print(case,'PASS',label,flush=True)
        def revision(sid):
            view=call('GET',f'/api/sessions/{sid}/commands')
            return view,{'expected_turn':view['turn'],**{k:view[k] for k in ('revision','world_version')}}
        try:
            check(not call('GET','/api/health')['build']['restart_required'],'fresh source API')
            snapshot,qa=inputs(case);battle=snapshot['definition']['battle'];phase=snapshot['phase_id']
            if args.reuse:
                draft=json.loads((root/(case+'-draft.json')).read_text())
                initial=json.loads((root/(case+'-initial.json')).read_text());sid=initial['session_id']
            else:
                instruction=('只构建选定局部阶段的真实ID，不使用CA代表编组。所有人数、装备、位置与效能明确标为软件QA估计，'
                    '不是史实实到量。以阶段geographic_scope.center作工作中心，范围3公里地形因子1.5。'
                    '红在中心南约300米、蓝在北约300米，各单位经度稍错开；支援单位在本方后方1.5公里。'
                    '普通步兵师估计4500人、团1600人、营500人，侦察班12人；高阳垈守备分队135仅作QA选择。'
                    '支援单位250人、formation.role=support，4门火炮240发炮弹，type炮兵；其余role=infantry、'
                    'type步兵或侦察且无火炮。armor/air_defense/engineer为0，蓝方4辆transport、1000升燃油，'
                    '红方徒步无transport/fuel。无航空，非谓历史没有航空。步兵自卫1000米、炮兵自卫800米，'
                    'speed3、粮弹工作量80、fatigue10、entrenchment15、suppression0、protection0.15、'
                    'dispersion_km2=1（侦察班0.05）、intel_confidence80、signal90。'
                    '时钟从execution_window.start开始，30分钟一步，deadline_turn='+str(qa['goal']['deadline_turn'])+'。'
                    'goal使用delay，在截止时红至少一个可用单位且蓝未到红后方南2公里出口，'
                    '这是局部软件目标，不是历史胜负；不启用桥梁、capacity/integrity为0，不能有假障碍。'
                    '双方后方1.5公里各给stock300和明确五类补给库存。不得为了战果配额扣人；'
                    '马良山全程20死104伤（15继续执勤）和格洛斯特622含被俘等均非本局必达损失。'
                    '真实读取skill/basis、调用校验，再生成完整参数并由原生AFSIM装载。')
                print(case,'BUILD native DSH skill',flush=True)
                operation_id=uuid.uuid4().hex
                save('build-request',{'operation_id':operation_id,'battle':battle,'phase_id':phase})
                draft=call('POST','/api/historical-scenarios/build',{'battle':battle,'phase_id':phase,
                    'instruction':instruction,'execution_backend':'afsim','time_step':'30分钟','operation_id':operation_id})
                save('draft',draft)
                sid=call('POST','/api/sessions',{'scenario':case+'具名历史局部QA，人数装备部署为估计；不代表全战役重现。',
                    'battle':battle,'product_mode':'historical','execution_backend':'afsim','use_rag':True,
                    'historical_parameters':draft['parameters'],'scenario_draft_id':draft['id'],'persist_roles':False})['session_id']
                initial=call('POST',f'/api/sessions/{sid}/init');save('initial',initial)
            result['session_id']=sid
            construction=draft['construction']
            calls={e.get('name') for run in construction['runs'] for e in run.get('events',[]) if e.get('type')=='tool/call'}
            check(construction['source']=='dsh_native_skill' and
                {'read_scenario_skill','get_scenario_basis','validate_scenario_configuration'}<=calls,
                'real skill, source and validation tool evidence')
            check(draft['validation']['scope']=='native_load','actual AFSIM native draft load')
            expected=set(ho.partition(snapshot));w=initial['war_state'];frozen=copy.deepcopy(w['historical_initial'])
            check({u['historical_unit_id'] for _,u in missions.units(w)}==expected,'exact non-overlapping sourced phase actors')
            check(w['afsim']['entity_count']==len(expected),'native actor count')
            answer=call('GET',f'/api/sessions/{sid}')
            if answer['turn_count']==0:
                _,rev=revision(sid)
                answer=call('POST',f'/api/sessions/{sid}/next',{**rev,'batch_id':uuid.uuid4().hex,
                    'instruction':'实际读取get_afsim_observation与retrieve_history。双方每一个可行动单位均下令；步兵fire最近可见敌人、火炮bombard最近敌人，不移动。逐一使用本局ID。结果由AFSIM产生，不套历史歼敌配额，不将被俘算阵亡。'})
                save('turn1',answer)
            else:
                answer=json.loads((root/(case+'-turn1.json')).read_text())
            check(not answer['war_state']['afsim']['model_skipped'] and
                len(answer['war_state']['afsim']['orders'])==len(expected),'real DSH issues bilateral orders')
            exported=call('GET',f'/api/sessions/{sid}/export')['session']
            turn=next(t for t in exported['trajectory'] if t.get('turn')==1)
            used={e.get('name') for run in turn['runs'] for e in run.get('events',[]) if e.get('type')=='tool/call'}
            check({'get_afsim_observation','retrieve_history'}<=used,'planner actually observes and retrieves')
            current=call('GET',f'/api/sessions/{sid}');v,rev=revision(sid)
            branch=call('POST',f'/api/sessions/{sid}/commands/compare',{**rev,'turn':1,
                'orders':[{'unit_id':u['id'],'action':'hold','duration':'next'} for u in v['units'] if u['team']=='red']})
            save('counterfactual',branch)
            check(sum(u['personnel']['casualties'] for u in branch['alternative']['blue_units'])<
                sum(u['personnel']['casualties'] for u in answer['war_state']['blue_units']),
                'withholding red fire reduces blue losses')
            check(call('GET',f'/api/sessions/{sid}')['war_state']==current['war_state'],'counterfactual leaves main world unchanged')
            deadline=draft['parameters']['goal']['deadline_turn'];completed=current['turn_count'];ledger=[]
            for n in range(1,deadline+1):
                if n<=completed:answer=json.loads((root/(case+'-turn'+str(n)+'.json')).read_text())
                else:
                    if answer['war_state']['mission']['status']!='active':break
                    view,rev=revision(sid);orders=[]
                    for u in view['units']:
                        if not u['capabilities']['enabled']:continue
                        enemies=[e for e in view['units'] if e['team']!=u['team'] and e['available']]
                        order={'unit_id':u['id'],'action':'hold','duration':'next'}
                        for action in ('bombard','fire'):
                            if action not in u['capabilities']['actions']:continue
                            limits=u['capabilities']['weapon_limits_m'][action]
                            targets=[e for e in enemies if limits['min_range_m']<=
                                missions.distance(u['position'],e['position'])*1000<=limits['max_range_m']]
                            if targets:
                                target=min(targets,key=lambda e:missions.distance(u['position'],e['position']))
                                order.update(action=action,target_id=target['id']);break
                        orders.append(order)
                    call('PUT',f'/api/sessions/{sid}/commands',{**rev,'orders':orders,'control_team':'red',
                        'director':True,'no_fire':False,'unit_agents':[]})
                    _,rev=revision(sid)
                    answer=call('POST',f'/api/sessions/{sid}/next',{**rev,'batch_id':uuid.uuid4().hex})
                    save('turn'+str(n),answer)
                w=answer['war_state'];missions.validate(w)
                check(all(u['personnel']['committed']==u['personnel']['current']+u['personnel']['casualties']+u['personnel']['noncombat_losses']
                    and u['personnel']['casualties']==sum(u['personnel'].get(k) or 0 for k in ('killed','wounded','missing','captured','unclassified_casualties'))
                    and all(e['committed']==e['operational']+e['damaged']+e['destroyed'] for e in u['equipment'])
                    for _,u in missions.units(w)),str(n)+' personnel and equipment conservation')
                check(w['historical_initial']==frozen,str(n)+' immutable source snapshot')
                ledger.append({'turn':n,'clock':w['current_time'],'mission':w['mission']['status'],
                    'units':[{'name':u['name'],'personnel':u['personnel'],'logistics':u['logistics'],
                        'execution':u['formation'].get('last_execution')} for _,u in missions.units(w)]})
            save('ledger',ledger)
            elapsed=(datetime.fromisoformat(w['current_time'])-datetime.fromisoformat(initial['war_state']['current_time'])).total_seconds()
            check(elapsed==len(ledger)*1800,'exact 30-minute native clock')
            check(w['mission']['status']!='active','program objective terminates within the phase deadline')
            main=copy.deepcopy(w)
            analysis=call('POST',f'/api/sessions/{sid}/chat',{'message':'实际读取get_afsim_observation和get_afsim_changes(mode=aggregate)的全部页。简短表列本局每单位累计减员/阵亡/负伤与弹药工作量；核对时间与有效火力不同，指出停火/耗弹后的停止。引用同番号参照时明确全程和本局窗口不同，格洛斯特含被俘、马良山伤者继续执勤不能算全部永久减员，缺载不编造。不修改战局。'})
            save('analysis',analysis)
            check(analysis['war_state']==main and analysis['engine_meta']['finish_reason']=='completed','real DSH analyzes native effects without mutation')
            _,rev=revision(sid);call('POST',f'/api/sessions/{sid}/next',{**rev,'batch_id':uuid.uuid4().hex},expected=422)
            check(call('GET',f'/api/sessions/{sid}')['war_state']==main,'finished window cannot repeat losses')
            result.update(passed=True,turns=len(ledger),elapsed_seconds=elapsed,
                totals={u['name']:u['personnel'] for _,u in missions.units(w)})
        except Exception as exc:
            result['error']=str(exc);raise
        finally:
            result['seconds']=round(time.monotonic()-started,2);save('result',result)


if __name__=='__main__':main()
