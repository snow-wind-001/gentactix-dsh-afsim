"""Read-only command/task candidates over existing actual T1 QA checkpoints."""
import argparse
import hashlib
import json
from pathlib import Path
import time

from tools.qa import formation_continuity_live as base

ROOT=Path('.cache/qa/formation-session-2026-11-02')
base.ROOT=ROOT;base.api.ROOT=ROOT;base.api.PORT=19148
call=base.call;save=base.save


def verify(tag='final-actual'):
    from gentactix import commands,formation_conversion as fc,formation_session as handoff
    from backend import session_store
    results=[]
    for name,case in base.cases():
        url='/sessions/'+case['session_id'];before=call('GET',url);u=base.unit(before)
        commands_before=call('GET',url+'/commands');org=call('GET',url+'/force-organization')
        path=ROOT/'api/sessions'/(case['session_id']+'.json');disk=path.read_bytes()
        source=json.loads(disk)['session'];args=base.request(before,case)
        first=call('POST',url+'/force-organization/conversion-preview',args)
        second=call('POST',url+'/force-organization/conversion-preview',
            {k:args[k] for k in ('expected_turn','revision','world_version')}|first['next_args'])
        assert first['session_continuity']==second['session_continuity'] and first['view_version']==second['view_version']
        assert first['session_continuity']['commands_prepared'] and not first['runtime_admitted']
        p=fc.split_current(u,args['allocations'],assumption=args['assumption'],operation_id='a'*32,
            product_mode='synthetic',historical_snapshot=source['war_state']['historical_initial'])
        candidate=handoff.prepare(source,p,team='red');after=candidate['session'];cold=json.loads(json.dumps(after))
        assert handoff.validate(cold) and cold==after
        ids=candidate['command_map'][case['unit_id']];assert len(ids)==2
        assert next(r for r in after['command_state']['registry'] if r['id']==case['unit_id'])['retired']
        assert after['command_state'].get('agent_sessions')==source['command_state'].get('agent_sessions')
        assert after['decision_log']==source['decision_log'] and after['history']==source['history']
        probe=handoff.command_probe(after);assert probe['state']['receipts']==after['command_state']['receipts']
        assert set(ids)<={r['command']['unit_id'] for r in probe['manual']}
        refused=False
        try:session_store.validate(cold)
        except ValueError as exc:refused='事务' in str(exc)
        assert refused,'Platform commit remains intentionally unadmitted'
        latest=call('GET',url)
        assert latest['war_state']==before['war_state'] and latest['history']==before['history']
        assert call('GET',url+'/commands')==commands_before and call('GET',url+'/force-organization')==org
        assert path.read_bytes()==disk
        save(tag+'/'+name+'/preview.json',dict(first=first,second=second));save(tag+'/'+name+'/prepared-session.json',after)
        results.append(dict(case=name,passed=True,casualties=u['personnel']['casualties'],
            session_continuity=first['session_continuity'],new_command_ids=ids,json_restore_validated=True,
            probe_manual=len(probe['manual']),probe_blocked=[dict(unit_id=o['unit_id'],reason=o['reason']) for o in probe['blocked']],
            original_receipts_decisions_native_bindings_unchanged=True,source_checkpoint_and_runtime_unchanged=True,
            normal_host_admission_rejected=True))
    for path,digest in json.loads((ROOT/'source-checkpoints.json').read_text()).items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest
    save(tag+'/actual-preview-review.json',dict(passed=True,cases=results,new_physics_turns=0,
        scope='Detached command/session candidates over copied real T1 states; no runtime conversion'))
    print('PASS3 actual-state HTTP/session candidates, command probes and cold restore',flush=True)


def review():
    """Recheck saved final candidates; no network/model call or state write."""
    from gentactix import formation_session as handoff,force_task_execution as tasks
    results=[]
    for name,_ in base.cases():
        after=json.loads((ROOT/'final-actual'/name/'prepared-session.json').read_text())
        assert handoff.validate(after);cs=after['command_state'];event=cs['formation_handoffs'][-1]
        ids=set(i for values in event['command_map'].values() for i in values)
        probe=handoff.command_probe(after);assert ids<={r['command']['unit_id'] for r in probe['manual']}
        checked=[]
        for tid,record in cs.get('task_plans',{}).items():
            old=event['before_command_state'].get('task_plans',{}).get(tid)
            if not old or 'execution' not in old or old['execution']['status'] in tasks.TERMINAL:continue
            if not set(old['execution']['members'])&set(event['command_map']):continue
            current=record['execution'];prior=old['execution']
            assert current['definition_hash']==prior['definition_hash'] and current['definition']==prior['definition']
            assert set(current['members'])==set(i for old_id in prior['members'] for i in event['command_map'].get(old_id,[old_id]))
            assert all(current['member_states'][i]['executions']==probe['state']['task_plans'][tid]['execution']['member_states'][i]['executions'] for i in current['members'])
            checked.append(tid)
        results.append(dict(case=name,both_new_actors_have_legal_commands=True,converted_tasks=checked,
            task_definition_and_execution_counts_unchanged=True))
    assert len(results[-1]['converted_tasks'])==1
    save('final-actual/command-probe-review.json',dict(passed=True,cases=results,network_calls=0,model_calls=0,
        scope='Saved current-source candidate/proposal review; not physical execution'))
    print('PASS3 saved candidates, both new commands and exact frozen task/count preservation',flush=True)


def setup_task():
    """Use normal APIs on the disposable equipped copy; no world advance."""
    from gentactix import commands
    from verify_force_task_execution import execution
    case=dict(base.cases())['equipped-afsim'];url='/sessions/'+case['session_id'];before=call('GET',url)
    old=call('GET',url+'/commands')
    tasks=call('GET',url+'/force-organization/tasks')['rows']
    if any(r['status'] not in ('completed','failed','cancelled') and case['unit_id'] in r['member_sample'] for r in tasks):
        save('task-setup.json',dict(existing=True,world_unchanged=True));return
    drafts=[{k:v for k,v in o.items() if k in commands.DRAFT_FIELDS} for o in old['orders'] if o['unit_id']!=case['unit_id']]
    call('PUT',url+'/commands',dict(expected_turn=old['turn'],revision=old['revision'],world_version=old['world_version'],
        control_team='red',director=True,no_fire=False,intent='隔离QA：保持已发生损耗，检验待执行任务的身份接续',orders=drafts))
    org=call('POST',url+'/force-organization/detach',dict(**base.api.revision(url),unit_ids=[case['unit_id']],
        label='Native候选接续QA群',assumption='软件测试临时指挥，不是历史改隶'))
    group=next(g['id'] for g in org['groups'] if g['label']=='Native候选接续QA群')
    value=dict(**base.api.revision(url),group_id=group,task=dict(kind='defend'),
        execution=execution('Native候选任务接续',start=old['turn']+1,
            finish=dict(kind='turn',end_turn=old['turn']+3,minimum_executions=2)))
    preview=call('POST',url+'/force-organization/task-preview',value)
    call('POST',url+'/force-organization/tasks',{**value,'preview_hash':preview['preview_hash']})
    latest=call('GET',url);assert latest['war_state']==before['war_state'] and latest['history']==before['history']
    save('task-setup.json',dict(existing=False,world_unchanged=True,turn=old['turn'],group_id=group,
        commands_before=old,commands_after=call('GET',url+'/commands'),tasks_after=call('GET',url+'/force-organization/tasks')))
    print('PASS isolated API task assignment on actual T1 state without advancing',flush=True)


def chat(*,review_only=False):
    case=dict(base.cases())['equipped-afsim'];url='/sessions/'+case['session_id']
    if review_only:
        from gentactix import commands,formation_continuity
        before=json.loads((ROOT/'final-actual/equipped-afsim/prepared-session.json').read_text())
        event=before['command_state']['formation_handoffs'][-1]
        before['war_state']=formation_continuity._undo_latest(before['war_state'],before['war_state']['formation_registry']['transactions'][-1])
        before['command_state']=event['before_command_state'];before['force_organization']=event['before_organization']
        old=commands.view(before)
    else:
        before=call('GET',url);old=call('GET',url+'/commands')
    u=base.unit(before);args=base.request(before,case)
    args={k:v for k,v in args.items() if k not in ('expected_turn','revision','world_version')}
    prompt=('SESSION-HANDOFF-READONLY-'+case['session_id']+'。只读核对第159师。先实际调用get_afsim_observation，再实际调用preview_force_conversion参数'
        +json.dumps(args,ensure_ascii=False)+'，沿next_args读完两页。不要下令或推进。最后仅以JSON回答turn,personnel_current,casualties,'
        'gear_committed,world_prepared,commands_prepared,organization_prepared,active_tasks,agent_sessions_cloned,runtime_admitted,executed,preview_rows。'
        '候选状态已经接续不表示已提交或实际分兵。')
    journals=ROOT/'api/dsh-home/sessions';offsets={} if review_only else {str(p):p.stat().st_size for p in journals.rglob('session.v4.jsonl')}
    start=time.monotonic()
    if review_only:response=json.loads((ROOT/'native-chat-response.json').read_text())
    else:
        response=call('POST',url+'/chat',dict(message=prompt));save('native-chat-response.json',response)
    content=response['chat_messages'][-1]['content'];values=[]
    expected=dict(turn=1,personnel_current=u['personnel']['current'],casualties=u['personnel']['casualties'],
        gear_committed=sum(e['committed'] for e in u['equipment']),world_prepared=True,commands_prepared=True,
        organization_prepared=True,active_tasks=1,agent_sessions_cloned=False,runtime_admitted=False,executed=False,preview_rows=2)
    for i,ch in enumerate(content):
        if ch!='{':continue
        try:d,_=json.JSONDecoder().raw_decode(content[i:])
        except ValueError:continue
        if isinstance(d,dict) and expected.keys()<=d.keys():values.append(d)
    assert len(values)==1,'Public answer must provide one unambiguous object'
    checked=dict(values[0]);gear=checked.get('gear_committed')
    if isinstance(gear,dict):
        classes={e['category']:e['committed'] for e in u['equipment']}
        assert gear==classes|dict(total=sum(classes.values())),'Every reported equipment class must match, not only the total'
        checked['gear_committed']=gear['total']
    assert all(checked[k]==v for k,v in expected.items()),'Public facts must match actual observations'
    latest=call('GET',url);assert latest['war_state']==before['war_state'] and latest['history']==before['history']
    assert call('GET',url+'/commands')==old
    save('native-chat-review.json',dict(passed=True,expected=expected,answer=values[0],checked_facts=checked,
        seconds=None if review_only else round(time.monotonic()-start,2),reused_original_response=review_only,
        initial_rejection='Scalar-only equipment assertion rejected equivalent classified object' if review_only else None,
        world_history_commands_unchanged=True))
    calls={};pages=[];sessions=set();observed=False
    for path in journals.rglob('session.v4.jsonl'):
        with path.open() as f:
            f.seek(offsets.get(str(path),0))
            for line in f:
                event=json.loads(line);data=event.get('data',{})
                if event['type']=='tool/call':calls[data['callId']]=(data['name'],json.loads(data['arguments']))
                elif event['type']=='tool/result':
                    m=data['message'];name,args=calls.get(m.get('toolCallId'),(None,{}))
                    if name=='get_afsim_observation' and not m.get('isError'):observed=True
                    if name!='preview_force_conversion':continue
                    rows=[json.loads(b['text']) for b in m['content'] if b.get('type')=='text']
                    assert len(rows)==1 and rows[0].get('ok')
                    value=rows[0];assert value['session_continuity']['commands_prepared'] and not value['runtime_admitted']
                    pages.append(dict(offset=args.get('offset',0),rows=len(value['rows']),view_version=value['view_version'],
                        session_continuity=value['session_continuity']));sessions.add(path.parent.name)
    assert observed and [p['offset'] for p in pages]==[0,1] and len(sessions)==1
    assert pages[0]['view_version']==pages[1]['view_version'] and pages[0]['session_continuity']==pages[1]['session_continuity']
    save('native-tool-review.json',dict(passed=True,pages=pages,native_sessions=sorted(sessions),
        scope='Public Native tool call/result envelopes only; no private assistant reasoning'))
    print('PASS actual Native session-continuity proofs, no cloned sessions or execution claim',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['serve','setup-task','verify','review','chat','review-chat']);p.add_argument('--live',action='store_true');a=p.parse_args()
    if a.mode=='serve':base.serve()
    elif a.mode=='setup-task':setup_task()
    elif a.mode=='verify':verify()
    elif a.mode=='review':review()
    elif a.mode=='review-chat':chat(review_only=True)
    elif a.live:chat()
    else:p.error('Actual model call requires --live')
