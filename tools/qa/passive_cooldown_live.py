"""Opt-in actual Native preview rejection/correction from an unchanged T1 copy.

Uses the ordinary import, branch, command and turn APIs. The first stale timer
candidate is deliberately requested as a rejection probe, never as a game state.
Only public tool calls/results are reviewed; private reasoning is not exported.
"""
import argparse
import copy
import json
from pathlib import Path
import time
import uuid

from . import force_task_execution_live as api

ROOT=Path('.cache/qa/passive-cooldown-2026-11-02')
SOURCE=Path('.cache/qa/converted-phases-2026-11-02/narrative')
api.ROOT=ROOT;api.PORT=19211


def save(name,value):
    path=ROOT/name;path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():raise ValueError('Preserve existing evidence: '+str(path))
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def export(sid):return api.call('GET','/sessions/'+sid+'/export')['session']


def rev(base):
    value=api.call('GET',base+'/commands')
    return dict(expected_turn=value['turn'],revision=value['revision'],world_version=value['world_version'])


def public_feedback():
    calls={};rows=[]
    for path in sorted((ROOT/'api/dsh-home/sessions').glob('*/*/session.v4.jsonl')):
        with path.open() as stream:
            for line in stream:
                event=json.loads(line)
                if event.get('type') not in ('tool/call','tool/result'):continue
                data=event.get('data') or {}
                if event['type']=='tool/call' and data.get('name') in ('preview_turn_effects','submit_turn_report'):
                    calls[(str(path),data['callId'])]=data['name']
                elif event['type']=='tool/result':
                    message=data.get('message') or {};name=calls.get((str(path),message.get('toolCallId')))
                    if not name:continue
                    for block in message.get('content',[]):
                        if block.get('type')!='text':continue
                        try:reply=json.loads(block['text'])
                        except (ValueError,KeyError):continue
                        rows.append(dict(tool=name,seq=event.get('seq'),session_id=path.parent.name,
                            **{k:reply[k] for k in ('ok','readonly','error','digest','preview_hash','version') if k in reply},
                            **({'issue_codes':[r.get('code') for r in reply['issues']]} if 'issues' in reply else {})))
    return rows


def run(*,resume=False):
    if (ROOT/'live-case.json').exists() and not resume:raise ValueError('Actual case already exists; inspect rather than rerun')
    source=json.loads((SOURCE/'turn-1.json').read_text())['after']
    copied=copy.deepcopy(source)
    if resume:
        case=json.loads((ROOT/'live-case.json').read_text());sid=case['source_session'];bid=case['session_id']
        original=json.loads((ROOT/'source-copy.json').read_text());summary=json.loads((ROOT/'live-result.json').read_text())
        assert not summary['passed'] and len(summary['rounds'])==1 and export(bid)['turn_count']==2
    else:
        imported=api.call('POST','/sessions/import',dict(format='gentactix-session-v1',session=copied))
        sid=imported['session_id'];base='/sessions/'+sid
        original=export(sid);assert original['war_state']==source['war_state']
        branch=api.call('POST',base+'/commands/open-branch',rev(base));bid=branch['session_id']
        branched=export(bid);assert branched['war_state']==source['war_state']
        assert not branched['command_state']['agent_sessions']
        save('live-case.json',dict(source_session=sid,session_id=bid,source_turn=1,
            initial_world_unchanged=True,fresh_native_branch=True,deliberately_injected_stale_candidate=True,
            scope='Actual Native transport and timer admission QA; previous configuration uses estimated inputs, not historical calibration'))
        save('source-copy.json',original);summary=dict(passed=False,session_id=bid,rounds=[])
    old_case=json.loads((SOURCE/'case.json').read_text());base='/sessions/'+bid
    # The source's latest case.json contains later split identities. Resolve the
    # copied T1 actor against this branch, never borrow future conversion IDs.
    current=api.call('GET',base+'/commands')['units']
    old_case['members']=[next(r['id'] for r in current if r['name']=='第159师')]
    old_case['attacker']=next(r['id'] for r in current if r['name']=='日军第106师团')
    try:
        plan=(('ready-fire',True),('after-fire-hold',False)) if resume else (('reject-correct-hold',False),('ready-fire',True),('after-fire-hold',False))
        for label,combat in plan:
            before=export(bid);view=api.call('GET',base+'/commands');orders=[]
            excluded=set(old_case['members'])|{old_case['native_unit']}
            for row in view['units']:
                if not row['available'] or row['id'] in excluded:continue
                orders.append(dict(unit_id=row['id'],action='fire',target_id=old_case['members'][0],duration='next')
                    if combat and row['id']==old_case['attacker'] else dict(unit_id=row['id'],action='hold',duration='next'))
            api.call('PUT',base+'/commands',dict(**rev(base),orders=orders,control_team='red',director=True,no_fire=not combat,
                unit_agents=[old_case['native_unit']],intent='隔离计时QA：独立单位Agent明确hold；其他单位执行已确认命令及原持续任务，保留旧损伤。'))
            instruction=('软件计时验收，不是史实或效能标定。独立单位Agent本轮明确hold。执行固定命令，保留既有损失。'
                '依据共享火力先验计算每轮装填流逝，不得静默沿用旧值。')
            if label=='reject-correct-hold':
                instruction+=('本轮专门测试原生预览拒收链路：先在完整候选副本中，故意让日军第106师团的'
                    'formation.reload_remaining_s保持轮初60，调用preview_turn_effects。该候选应被拒收，绝不可提交。'
                    '收到真实错误反馈后修正倒计时，重新预览成功，再submit_turn_report。双方本轮没有地面开火。')
            started=time.monotonic()
            result=api.call('POST',base+'/next',dict(**rev(base),batch_id=uuid.uuid4().hex,instruction=instruction))
            after=export(bid);turn=after['turn_count'];world=after['war_state']
            save('live/turn-'+str(turn)+'.json',dict(before=before,after=after,engine_meta=result['engine_meta'],label=label))
            assert turn==before['turn_count']+1 and world['simulation_clock']['elapsed_seconds']-before['war_state']['simulation_clock']['elapsed_seconds']==900
            actor=next(u for u in world['blue_units'] if u['name']=='日军第106师团')
            if not combat:assert actor['formation']['reload_remaining_s']==0
            else:
                row=next(r for r in world['dsh_execution']['fire_ledger']['units'] if r['unit']==actor['name'])
                assert row['fire_cycles']>0 and row['first_fire_s']<900
            if not combat:
                old={u['name']:u for t in ('red','blue') for u in before['war_state'][t+'_units']}
                assert all(u['personnel']==old[u['name']]['personnel'] for t in ('red','blue') for u in world[t+'_units'])
            assert export(sid)==original and source==copied
            summary['rounds'].append(dict(turn=turn,label=label,reload_remaining_s=actor['formation']['reload_remaining_s'],
                seconds=round(time.monotonic()-started,3),finish_reason=result['engine_meta']['finish_reason']))
            print('PASS actual Native',label,'T'+str(turn),'reload_s='+str(actor['formation']['reload_remaining_s']),flush=True)
        feedback=public_feedback();save('public-tool-feedback.json',feedback)
        assert any(r.get('ok') is False and '期末须=0' in r.get('error','') for r in feedback)
        assert any(r['tool']=='submit_turn_report' and r.get('ok') is True for r in feedback)
        save('expected-final-cold.json',export(bid))
        summary.update(passed=True,rejected_stale_preview=True,corrected_by_model=True,automatic_state_repair=False,
            later_actual_fire=True,source_unchanged=True,original_historical_acceptance=False)
    finally:
        save('live-resume-result.json' if resume else 'live-result.json',summary)


def cold():
    expected=json.loads((ROOT/'expected-final-cold.json').read_text())
    assert export(expected['id'])==expected
    source=json.loads((ROOT/'source-copy.json').read_text());assert export(source['id'])==source
    save('cold-review.json',dict(passed=True,whole_branch_exact=True,whole_source_exact=True,turn=expected['turn_count']))
    print('PASS fresh process restored whole branch and source',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=('serve','run','resume','cold'))
    parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if args.mode=='serve':api.serve()
    elif args.mode=='cold':cold()
    else:
        if not args.live:parser.error('Actual model calls require --live')
        run(resume=args.mode=='resume')
