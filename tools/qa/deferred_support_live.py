"""Real backend/SDK support exposure, formal merge, cold restore and resplit.

Fixed explicitly estimated QA parameters; no model-response or state injection.
All gameplay and conversion uses the existing ordinary HTTP interfaces.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import time
import uuid

from . import force_task_execution_live as api

ROOT=Path('.cache/qa/deferred-support-2026-11-03');api.ROOT=ROOT;api.PORT=19378


def save(name,value):
    p=ROOT/name;p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():raise ValueError('Preserve evidence: '+str(p))
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def export(case):return api.call('GET','/sessions/'+case['session_id']+'/export')['session']


def parameters():
    from .converted_phases_live import parameters as base
    # The older helper sets shared client defaults when imported.
    api.ROOT=ROOT;api.PORT=19378
    source,p=base(personnel_rations=True)
    p['clock']['time_step']='30分钟'
    p['support_dynamics'].update(incapacity_after_hours=1,incapacity_fraction_per_hour=.00024,
        assumption='Deliberately accelerated software QA incapacity exposure, NOT a historical/physiological rate. No initial debt or casualty seeded.')
    p['campaign_lifecycle']['phases'][0]['minimum_duration_seconds']=5400
    p['campaign_lifecycle']['phases'][1]['minimum_duration_seconds']=1800
    for a in p['actors'].values():a['logistics']['food']=0
    return source,p


def serve():
    folder=(ROOT/'api').resolve()
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(folder/suffix)
    if not (ROOT/'base-drafts.json').exists():
        from backend import scenario_builder
        source,p=parameters();drafts={}
        for engine in ('afsim','narrative'):
            d=scenario_builder.stage_historical(source,p,construction=dict(source='dsh_native_skill',qa_fixed_input=True,
                explanation='Fixed estimated QA inputs. Actual effects/NC remainders must come from runtime; not model-generated configuration or historical losses.'),execution_backend=engine)
            drafts[engine]=dict(id=d['id'],battle=source['definition']['battle'])
        save('base-drafts.json',drafts)
    api.ROOT=ROOT;api.PORT=19378
    api.serve()


def queue(case):
    base='/sessions/'+case['session_id'];v=api.call('GET',base+'/commands');s=export(case)
    task_status=s.get('command_state',{}).get('task_plans',{}).get(case.get('task'),{}).get('execution',{}).get('status')
    active=not case.get('task') or task_status not in ('completed','cancelled','failed')
    excluded={case['native_unit']}|(set(case['members']) if active else set())
    orders=[dict(unit_id=u['id'],action='hold',duration='next') for u in v['units'] if u['available'] and u['id'] not in excluded]
    api.call('PUT',base+'/commands',dict(expected_turn=v['turn'],revision=v['revision'],world_version=v['world_version'],orders=orders,
        control_team='red',director=True,no_fire=True,unit_agents=[case['native_unit']],
        intent='软件保障QA，所有单位明确hold，不机动不射击。按真实经过时间和已登记保障参数计算饥饿失能，不能补满或记为阵亡。'
        '正式合并的待结算失能负荷保留，后续新增有效暴露时按登记策略结算；不存在交战。'))


def convert(case,kind,label):
    base='/sessions/'+case['session_id'];before=export(case);v=api.call('GET',base+'/commands')
    request=dict(**api.revision(base),kind=kind,unit_ids=case['members'],assumption='Software support-load conversion QA; not a historical reorganization')
    if kind=='split':
        entry=next(u for u in v['units'] if u['id']==case['members'][0]);unit=next(u for u in before['war_state']['red_units'] if u['name']==entry['name']);n=unit['personnel']['committed']
        request['allocations']=[dict(id='a',label='余量左',committed=n//2),dict(id='b',label='余量右',committed=n-n//2)]
    preview=api.call('POST',base+'/force-organization/conversion-preview',request)
    request.update(view_version=preview['view_version'],commit_id=uuid.uuid4().hex)
    result=api.call('POST',base+'/force-organization/conversion-commit',request)['conversion_result']
    after=export(case)
    for key in ('simulation_clock','campaign_lifecycle'):assert after['war_state'][key]==before['war_state'][key]
    assert after['history']==before['history'] and after['trajectory']==before['trajectory']
    from gentactix import formation_conversion as fc,missions
    assert fc._totals([u for _,u in missions.units(before['war_state'])])==fc._totals([u for _,u in missions.units(after['war_state'])])
    case['members']=list(dict.fromkeys(i for values in result['command_map'].values() for i in values))
    save(case['engine']+'/'+label+'.json',dict(request=request,result=result,before=before,after=after))
    return after


def root_units(case,snapshot):
    source_ids={row['id']:row['name'] for row in api.call('GET','/sessions/'+case['session_id']+'/commands')['units']}
    names={source_ids[i] for i in case['members']}
    return [u for u in snapshot['war_state']['red_units'] if u['name'] in names]


def advance(case,label):
    before=export(case);base='/sessions/'+case['session_id'];v=api.call('GET',base+'/commands');start=time.monotonic()
    response=api.call('POST',base+'/next',dict(expected_turn=v['turn'],revision=v['revision'],world_version=v['world_version'],batch_id=uuid.uuid4().hex,
        instruction='所有已确认动作和原生独立单位均hold，无交战。按已登记时间保障产生非战斗失能及余量，不强制历史战损，不填造到货。'))
    after=export(case);turn=after['turn_count'];w=after['war_state']
    assert turn==before['turn_count']+1 and w['simulation_clock']['elapsed_seconds']==turn*1800
    from gentactix import missions
    old={u['name']:u for _,u in missions.units(before['war_state'])}
    for _,u in missions.units(w):
        assert u['personnel']['casualties']==0 and u['logistics']['food']==0
        assert u['personnel']['current']+u['personnel']['noncombat_losses']==u['personnel']['committed']
        assert u['personnel']['current']<=old[u['name']]['personnel']['current']
    decisions=[d for d in after['trajectory'][-1]['decisions'] if d.get('source')=='native_unit_agent']
    assert len(decisions)==1 and decisions[0]['unit_id']==case['native_unit'] and decisions[0]['action']=='hold'
    if case['engine']=='afsim':assert w['afsim']['returncode']==0 and w['afsim']['effects_source']=='afsim-native-teaching-1'
    else:assert w['dsh_execution']['effects_source']=='dsh_model_estimate' and not w.get('afsim')
    save(case['engine']+'/turn-'+str(turn)+'.json',dict(before=before,after=after,engine_meta=response['engine_meta'],label=label))
    print('PASS',case['engine'],'T'+str(turn),label,round(time.monotonic()-start,3),'s',flush=True)
    return after


def start(engine, *, browser_merge=False):
    assert not (ROOT/engine/'case.json').exists()
    source=json.loads((ROOT/'base-drafts.json').read_text())[engine]
    draft=api.call('POST','/scenarios/from-historical',dict(base_draft_id=source['id'],execution_backend=engine))['draft']
    created=api.call('POST','/sessions',dict(scenario='饥饿余量真实结转QA，非历史伤亡标定',battle=source['battle'],product_mode='synthetic',
        scenario_draft_id=draft['id'],synthetic_configuration=draft['configuration'],execution_backend=engine,simulation_mode='open',time_step='30分钟',agent_mode='native',persist_roles=True))
    sid=created['session_id'];base='/sessions/'+sid;initial=api.call('POST',base+'/init');v=api.call('GET',base+'/commands')
    name=next(u['name'] for u in initial['war_state']['red_units'] if u.get('source_historical_unit_id')=='ww2.cn.division159')
    root=next(u['id'] for u in v['units'] if u['name']==name);native=next(u['id'] for u in v['units'] if u['team']=='red' and u['id']!=root)
    case=dict(engine=engine,session_id=sid,members=[root],native_unit=native)
    save(engine+'/created-case.json',case)
    continue_initial(case,browser_merge=browser_merge)


def continue_initial(case, *, browser_merge=False):
    engine=case['engine'];sid=case['session_id'];base='/sessions/'+sid
    s=export(case);assert s['turn_count']==0 and not s.get('formation_commits')
    queue(case)
    # A prior rejected preview may already have saved the explicitly created
    # group. Reuse that exact T0 group; never repeat initialization or a turn.
    org=api.call('GET',base+'/force-organization')
    groups=[g for g in org['groups'] if g['label']=='保障余量任务群']
    assert len(groups)<=1
    if not groups:
        org=api.call('POST',base+'/force-organization/detach',dict(**api.revision(base),unit_ids=case['members'],label='保障余量任务群',assumption='软件保障测试'))
        groups=[g for g in org['groups'] if g['label']=='保障余量任务群']
    case['group']=groups[0]['id']
    from verify_force_task_execution import execution
    req=dict(**api.revision(base),group_id=case['group'],task=dict(kind='uniform',order=dict(action='hold')),
        execution=execution('四轮保持保障任务',finish=dict(kind='turn',end_turn=4,minimum_executions=4)))
    preview=api.call('POST',base+'/force-organization/task-preview',req)
    api.call('POST',base+'/force-organization/tasks',{**req,'preview_hash':preview['preview_hash']})
    case['task']=next(reversed(export(case)['command_state']['task_plans']))
    save(engine+'/prefix-case.json',case);convert(case,'split','initial-split')
    for _ in range(3):queue(case);after=advance(case,'actual support exposure')
    units=root_units(case,after)
    assert len(units)==2 and all(abs(u['sustainment']['noncombat_remainder']-.6)<1e-6 and u['personnel']['noncombat_losses']==0 for u in units)
    if browser_merge:
        save(engine+'/browser-case.json',case);save(engine+'/browser-before-merge.json',after)
        print('BROWSER CHECKPOINT',engine,sid,'T3 both actual remainders .6; normal frontend merge required',flush=True)
        return
    after=convert(case,'merge','integer-merge');u=root_units(case,after)[0]
    assert abs(u['sustainment']['noncombat_remainder']-1.2)<1e-6 and u['personnel']['noncombat_losses']==0
    assert u['runtime_allocation']['support_remainder_policy']=='deferred-support-exposure-1'
    save(engine+'/case.json',case);save(engine+'/expected-pending-cold.json',after)
    print('CHECKPOINT',engine,sid,'T3 pending1.2 earned by actual runtime; explicit cold restart required',flush=True)


def recover_start(engine):
    case=json.loads((ROOT/engine/'created-case.json').read_text())
    continue_initial(case)


def resume(engine):
    case=json.loads((ROOT/engine/'case.json').read_text());expected=json.loads((ROOT/engine/'expected-pending-cold.json').read_text())
    assert export(case)==expected;save(engine+'/cold-review.json',dict(passed=True,whole_session_exact=True,pid=api.call('GET','/health')['build']['pid']))
    queue(case);after=advance(case,'settle prior integer with new exposure');u=root_units(case,after)[0]
    assert u['personnel']['noncombat_losses']==2 and abs(u['sustainment']['noncombat_remainder']-.4)<1e-6
    task=after['command_state']['task_plans'][case['task']]['execution'];assert task['status']=='completed' and all(row['executions']==4 for row in task['member_states'].values())
    convert(case,'split','resplit-after-settlement');queue(case);after=advance(case,'new fractional load after resplit')
    assert all(abs(u['sustainment']['noncombat_remainder']-.8)<1e-6 for u in root_units(case,after))
    after=convert(case,'merge','second-integer-merge');assert abs(root_units(case,after)[0]['sustainment']['noncombat_remainder']-1.6)<1e-6
    queue(case);after=advance(case,'second pending settlement');u=root_units(case,after)[0]
    assert u['personnel']['noncombat_losses']==4 and u['personnel']['current']==9996 and abs(u['sustainment']['noncombat_remainder']-.8)<1e-6
    assert after['command_state']['agent_sessions'][case['native_unit']]['session_id']==expected['command_state']['agent_sessions'][case['native_unit']]['session_id']
    save(engine+'/expected-final-cold.json',after)
    save(engine+'/result.json',dict(passed=True,session_id=case['session_id'],actual_runtime=True,turns=6,formal_conversions=4,
        pending_1_2_and_1_6_preserved=True,root_noncombat_losses=4,root_pending=.8,original_task_completed=True,same_native_unit_binding=True,
        historical_calibration=False,full_campaign_complete=False))
    print('PASS COMPLETE',engine,'T6 repeated pending settlement; not complete campaign/history',flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['serve','start','recover-start','resume']);p.add_argument('--backend',choices=['afsim','narrative']);p.add_argument('--live',action='store_true');p.add_argument('--browser-merge',action='store_true');args=p.parse_args()
    if args.mode=='serve':serve();return
    if not args.live or not args.backend:p.error('--live --backend required')
    if args.mode=='start':start(args.backend,browser_merge=args.browser_merge)
    elif args.mode=='recover-start':recover_start(args.backend)
    else:resume(args.backend)


if __name__=='__main__':main()
