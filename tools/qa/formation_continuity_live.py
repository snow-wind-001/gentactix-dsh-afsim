"""Read-only process-handoff checks over copied actual T1 states.

No new turn, command, runtime split, published scenario, or user game is written.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import time

from tools.qa import force_task_execution_live as api
from tools.qa.formation_registry_live import cases, unit

ROOT=Path('.cache/qa/formation-continuity-2026-11-02')
SOURCE=Path('.cache/qa/formation-conversion-2026-11-02')
api.ROOT=ROOT;api.PORT=19146
call=api.call


def save(name,value):
    p=ROOT/name;p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():raise ValueError('Preserve existing evidence: '+str(p))
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def serve():
    folder=ROOT/'api/sessions';folder.mkdir(parents=True,exist_ok=True);hashes={}
    for _,case in cases():
        source=SOURCE/'api/sessions'/(case['session_id']+'.json');target=folder/source.name
        hashes[str(source)]=hashlib.sha256(source.read_bytes()).hexdigest()
        if not target.exists():shutil.copy2(source,target)
    if not (ROOT/'source-checkpoints.json').exists():save('source-checkpoints.json',hashes)
    api.serve()


def request(snapshot,case):
    base='/sessions/'+case['session_id'];v=call('GET',base+'/commands');n=unit(snapshot)['personnel']['committed']
    return dict(expected_turn=v['turn'],revision=v['revision'],world_version=v['world_version'],kind='split',
        unit_ids=[case['unit_id']],allocations=[dict(id='left',label='左翼过程接续',committed=n//2),
            dict(id='right',label='右翼过程接续',committed=n-n//2)],limit=1,
        assumption='只读当前实态过程接续QA，数额及部署不是历史事实')


def verify():
    from gentactix import formation_continuity as continuity, formation_conversion as fc, missions
    results=[]
    for name,case in cases():
        base='/sessions/'+case['session_id'];before=call('GET',base);u=unit(before)
        commands=call('GET',base+'/commands');org=call('GET',base+'/force-organization')
        checkpoint=ROOT/'api/sessions'/(case['session_id']+'.json');disk=checkpoint.read_bytes()
        args=request(before,case);first=call('POST',base+'/force-organization/conversion-preview',args)
        second=call('POST',base+'/force-organization/conversion-preview',
            {k:args[k] for k in ('expected_turn','revision','world_version')}|first['next_args'])
        assert first['continuity']==second['continuity'] and first['continuity']['world_prepared']
        assert first['view_version']==second['view_version'] and second['next_args'] is None
        assert first['totals_before']==first['totals_after'] and not first['runtime_admitted']
        proposal=fc.split_current(u,args['allocations'],assumption=args['assumption'],operation_id='a'*32,
            product_mode='synthetic',historical_snapshot=before['war_state']['historical_initial'])
        value=continuity.prepare(before['war_state'],proposal,team='red');candidate=value['world']
        restored=json.loads(json.dumps(candidate,ensure_ascii=False))
        assert missions.validate(restored,allow_prepared=True) and restored==candidate
        assert candidate['mission']==before['war_state']['mission']
        assert candidate['simulation_clock']==before['war_state']['simulation_clock']
        rejected=False
        try:missions.validate(restored)
        except ValueError as exc:rejected='事务' in str(exc)
        assert rejected,'Prepared state is not yet a runtime session transaction'
        latest=call('GET',base)
        assert latest['war_state']==before['war_state'] and latest['history']==before['history']
        assert call('GET',base+'/commands')==commands and call('GET',base+'/force-organization')==org
        assert checkpoint.read_bytes()==disk
        save(name+'/preview.json',dict(first=first,second=second));save(name+'/prepared-candidate.json',candidate)
        results.append(dict(case=name,turn=latest['turn_count'],casualties=u['personnel']['casualties'],
            equipment=first['totals_before']['equipment'],continuity=first['continuity'],
            json_restore_validated=True,mission_and_clock_exact=True,runtime_rejected=True,
            source_world_history_commands_organization_and_disk_unchanged=True))
    for path,digest in json.loads((ROOT/'source-checkpoints.json').read_text()).items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest
    save('actual-preview-review.json',dict(passed=True,cases=results,scope='Copied actual T1 states; no new physical execution'))
    print('PASS3 actual-state HTTP handoff previews, full detached validation and JSON restore',flush=True)


def chat():
    case=dict(cases())['equipped-afsim'];base='/sessions/'+case['session_id'];before=call('GET',base);u=unit(before)
    commands=call('GET',base+'/commands');args=request(before,case)
    args={k:v for k,v in args.items() if k not in ('expected_turn','revision','world_version')}
    journals=ROOT/'api/dsh-home/sessions';offsets={str(p):p.stat().st_size for p in journals.rglob('session.v4.jsonl')}
    marker='CONTINUITY-READONLY-'+case['session_id']
    prompt=(marker+'。只读核对第159师。先调用get_afsim_observation读取实态，再实际调用preview_force_conversion参数'
        +json.dumps(args,ensure_ascii=False)+'，沿next_args读完两页。不要下令或推进回合。'
        '准备通过仍不是运行中实际分兵。最后仅用一个JSON对象回答turn,personnel_current,casualties,gear_committed,'
        'world_prepared,clock_advanced,goals_evaluated,command_task_platform_admitted,runtime_admitted,executed,preview_rows。')
    start=time.monotonic();response=call('POST',base+'/chat',dict(message=prompt));save('native-chat-response.json',response)
    content=response['chat_messages'][-1]['content'];found=[]
    expected=dict(turn=1,personnel_current=u['personnel']['current'],casualties=u['personnel']['casualties'],
        gear_committed=sum(e['committed'] for e in u['equipment']),world_prepared=True,clock_advanced=False,
        goals_evaluated=False,command_task_platform_admitted=False,runtime_admitted=False,executed=False,preview_rows=2)
    for i,ch in enumerate(content):
        if ch!='{':continue
        try:value,_=json.JSONDecoder().raw_decode(content[i:])
        except ValueError:continue
        if isinstance(value,dict) and expected.keys()<=value.keys():found.append(value)
    assert len(found)==1 and all(found[0][k]==v for k,v in expected.items()),'Public answer must match tool evidence'
    after=call('GET',base)
    assert after['war_state']==before['war_state'] and after['history']==before['history']
    assert call('GET',base+'/commands')==commands
    save('native-chat-review.json',dict(passed=True,marker=marker,expected=expected,answer=found[0],
        elapsed_seconds=round(time.monotonic()-start,2),world_history_commands_unchanged=True))
    calls={};pages=[];sessions=set();observed=False
    # Inspect public tool envelopes only; never print/export assistant reasoning.
    for path in journals.rglob('session.v4.jsonl'):
        with path.open() as f:
            f.seek(offsets.get(str(path),0))
            for line in f:
                event=json.loads(line);data=event.get('data',{})
                if event['type']=='tool/call':calls[data['callId']]=(data['name'],json.loads(data['arguments']))
                elif event['type']=='tool/result':
                    msg=data['message'];name,args=calls.get(msg.get('toolCallId'),(None,{}))
                    if name=='get_afsim_observation' and not msg.get('isError'):observed=True
                    if name!='preview_force_conversion':continue
                    values=[json.loads(b['text']) for b in msg['content'] if b.get('type')=='text']
                    assert len(values)==1 and values[0].get('ok'), 'Native preview failed'
                    value=values[0];assert value['continuity']['world_prepared'] and not value['runtime_admitted']
                    pages.append(dict(offset=args.get('offset',0),rows=len(value['rows']),view_version=value['view_version'],
                        continuity=value['continuity']));sessions.add(path.parent.name)
    assert observed and [p['offset'] for p in pages]==[0,1] and len(sessions)==1
    assert pages[0]['view_version']==pages[1]['view_version'] and pages[0]['continuity']==pages[1]['continuity']
    save('native-tool-review.json',dict(passed=True,pages=pages,native_sessions=sorted(sessions),
        scope='Completed public tool calls/results only; no new physical turn or runtime conversion'))
    print('PASS actual Native tools, two-page continuity proof and honest no-execution answer',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['serve','verify','chat'])
    p.add_argument('--live',action='store_true');a=p.parse_args()
    if a.mode=='serve':serve()
    elif a.mode=='verify':verify()
    elif a.live:chat()
    else:p.error('Actual model call requires --live')
