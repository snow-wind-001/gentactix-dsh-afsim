"""Read-only ownership verification over three recorded real execution states.

Copies only this project's isolated QA checkpoints. It never advances a turn or
claims the staged entity set was admitted to a running game.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import time

from tools.qa import force_task_execution_live as api

ROOT=Path('.cache/qa/formation-ownership-2026-11-02')
SOURCE=Path('.cache/qa/formation-conversion-2026-11-02')
api.ROOT=ROOT;api.PORT=19144
call=api.call


def save(path,value):
    p=ROOT/path;p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def cases():
    for name in ('afsim','narrative','equipped-afsim'):
        yield name,json.loads((SOURCE/name/'case.json').read_text())


def serve():
    folder=ROOT/'api/sessions';folder.mkdir(parents=True,exist_ok=True)
    hashes={}
    for name,c in cases():
        source=SOURCE/'api/sessions'/(c['session_id']+'.json');target=folder/source.name
        hashes[str(source)]=hashlib.sha256(source.read_bytes()).hexdigest()
        if not target.exists():shutil.copy2(source,target)
    if not (ROOT/'source-checkpoints.json').exists():save('source-checkpoints.json',hashes)
    api.serve()


def unit(snapshot):
    return next(u for u in snapshot['war_state']['red_units'] if u.get('source_historical_unit_id')=='ww2.cn.division159')


def body(base,uid,n):
    v=call('GET',base+'/commands')
    return dict(expected_turn=v['turn'],revision=v['revision'],world_version=v['world_version'],kind='split',
        unit_ids=[uid],allocations=[dict(id='left',label='左翼归属测试',committed=n//2),
            dict(id='right',label='右翼归属测试',committed=n-n//2)],
        assumption='仅验证实际损耗后的候选份额唯一归属；不是实际分兵或历史兵额',limit=1)


def verify():
    if (ROOT/'actual-preview-review.json').exists():raise ValueError('Preserve existing evidence')
    from gentactix import formation_conversion,formation_registry,missions
    results=[]
    for name,c in cases():
        base='/sessions/'+c['session_id'];before=call('GET',base);selected=unit(before)
        command=call('GET',base+'/commands');org=call('GET',base+'/force-organization')
        checkpoint=ROOT/'api/sessions'/(c['session_id']+'.json');disk=checkpoint.read_bytes()
        request=body(base,c['unit_id'],selected['personnel']['committed'])
        first=call('POST',base+'/force-organization/conversion-preview',request)
        second=call('POST',base+'/force-organization/conversion-preview',
            {k:v for k,v in request.items() if k in ('expected_turn','revision','world_version')}|first['next_args'])
        assert first['ownership']==second['ownership']
        assert first['ownership']['verified'] and first['ownership']['selected_roots']==1
        assert first['ownership']['current_entities']==6 and first['ownership']['candidate_entities']==7
        assert not first['runtime_admitted'] and first['totals_before']==first['totals_after']
        assert first['view_version']==second['view_version'] and second['next_args'] is None
        proposal=formation_conversion.split_current(selected,request['allocations'],assumption=request['assumption'],
            operation_id='a'*32,product_mode='synthetic',historical_snapshot=before['war_state']['historical_initial'])
        staged=formation_registry.stage(before['war_state'],proposal,team='red')
        candidate=staged['world'];cold=json.loads(json.dumps(candidate,ensure_ascii=False))
        assert formation_registry.validate(candidate)==formation_registry.validate(cold)
        rejected=False
        try:missions.validate(candidate)
        except ValueError:rejected=True
        assert rejected,'Incomplete command/goal/platform migrations must not admit a new roster'
        latest=call('GET',base)
        assert latest['war_state']==before['war_state'] and latest['history']==before['history']
        assert call('GET',base+'/commands')==command and call('GET',base+'/force-organization')==org
        assert checkpoint.read_bytes()==disk
        save(name+'/preview.json',dict(first=first,second=second))
        save(name+'/staged-candidate.json',candidate)
        results.append(dict(case=name,session_id=c['session_id'],passed=True,turn=latest['turn_count'],
            casualties=selected['personnel']['casualties'],equipment=first['totals_before']['equipment'],
            ownership=first['ownership'],candidate_json_restore_exact=True,candidate_not_admitted=True,
            world_history_commands_organization_and_disk_unchanged=True))
    for path,digest in json.loads((ROOT/'source-checkpoints.json').read_text()).items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest
    save('actual-preview-review.json',dict(passed=True,cases=results,scope='Actual recorded T1 states only; no new turn or physical conversion'))
    print('PASS three real-state ownership previews, detached candidate restore and unchanged source checkpoints',flush=True)


def chat():
    path=ROOT/'native-chat-response.json'
    if path.exists():raise ValueError('Preserve existing actual chat evidence')
    c=dict(cases())['equipped-afsim'];base='/sessions/'+c['session_id'];before=call('GET',base);selected=unit(before)
    commands=call('GET',base+'/commands');request=body(base,c['unit_id'],selected['personnel']['committed'])
    args={k:v for k,v in request.items() if k not in ('expected_turn','revision','world_version')}
    marker='OWNERSHIP-READONLY-'+c['session_id']
    question=(marker+'。只读验证第159师，先调用get_afsim_observation核对当前实态，再实际调用preview_force_conversion参数'
        +json.dumps(args,ensure_ascii=False)+'，沿next_args读完两页。不要下令或推进回合。'
        '只读候选归属验证成功不表示已在战局分兵。最后用一个JSON对象回答turn,personnel_current,casualties,'
        'gear_committed,ownership_verified,current_entities,candidate_entities,preview_rows,runtime_admitted,executed。')
    started=time.monotonic();answer=call('POST',base+'/chat',{'message':question});save('native-chat-response.json',answer)
    content=answer['chat_messages'][-1]['content'];found=[]
    expected=dict(turn=1,personnel_current=selected['personnel']['current'],casualties=selected['personnel']['casualties'],
        gear_committed=sum(e['committed'] for e in selected['equipment']),ownership_verified=True,current_entities=6,
        candidate_entities=7,preview_rows=2,runtime_admitted=False,executed=False)
    for i,c in enumerate(content):
        if c!='{':continue
        try:value,_=json.JSONDecoder().raw_decode(content[i:])
        except ValueError:continue
        if isinstance(value,dict) and expected.keys()<=value.keys():found.append(value)
    assert len(found)==1 and all(found[0][k]==v for k,v in expected.items()),(found,expected)
    after=call('GET',base)
    assert after['war_state']==before['war_state'] and after['history']==before['history']
    assert call('GET',base+'/commands')==commands
    save('native-chat-review.json',dict(passed=True,marker=marker,expected=expected,answer=found[0],
        unchanged=True,elapsed_seconds=round(time.monotonic()-started,2),native_tool_review_pending=True))
    print('PASS actual Native chat ownership facts and explicit no-execution claims',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=['serve','verify','chat'])
    parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if args.mode=='serve':serve()
    elif args.mode=='chat':
        if not args.live:parser.error('Actual model call requires --live')
        chat()
    else:verify()
