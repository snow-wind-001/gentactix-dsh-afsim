"""Actual Native unit planning over retained22 inputs; no physical turn or old session write."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import uuid


def observation_results(observer):
    """Ordinary observation replies do not use preview/report's readonly proof flag."""
    calls={}
    for run in observer.runs:
        for event in run.get('events',[]):
            sid=event.get('session_id')
            if event.get('type')=='tool/call' and event.get('name')=='get_afsim_observation':
                raw=event.get('arguments')
                try:args=json.loads(raw) if isinstance(raw,str) else raw
                except ValueError:continue
                calls[(sid,event.get('callId'))]=(event.get('seq'),args)
            elif event.get('type')=='tool/result':
                message=event.get('message') or {};call=calls.get((sid,message.get('toolCallId')))
                if not call or event.get('isError') or message.get('isError') or event.get('seq',-1)<=call[0]:continue
                raw='\n'.join(b.get('text','') for b in message.get('content',[]) if b.get('type')=='text')
                try:reply=json.loads(raw)
                except ValueError:continue
                if isinstance(reply,dict) and reply.get('ok') is True:yield call[1],reply


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true');parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if not args.live:parser.error('--live required')
    root=args.out
    if root.exists():parser.error('Preserve prior evidence')
    root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str((root/suffix).resolve())
    from backend import harness_engine as h,runtime_bridge,unit_planning,session_branch,unit_order_submission
    from backend.main import _native_tool_dispatch
    from gentactix import commands
    source=Path('.cache/qa/negative-inventory-and-preview-pages-2026-11-03/real-ui-t3/authoritative-after.json')
    source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    original=json.loads(source.read_text());session=session_branch.prepare(original,uuid.uuid4().hex[:12])
    assert session['war_state']==original['war_state']
    prepared=commands.prepare(session);saved=copy.deepcopy(session)
    observer=h.RunObserver('Native all22 situation index and tail observation')
    runtime_bridge.register_dispatcher(_native_tool_dispatch)
    packets=[];real_run=h.unit_run
    def capture(binding,prompt,*positional,**kwargs):
        packets.append(dict(prompt_chars=len(prompt),packet=json.loads(prompt.split('\n')[-1])))
        return real_run(binding,prompt,*positional,**kwargs)
    unit_planning.h.unit_run=capture
    stop=threading.Event()
    def monitor():
        while not stop.wait(15):print('WAIT_NATIVE',observer.steps,observer.total_tokens,flush=True)
    worker=threading.Thread(target=monitor,daemon=True);worker.start();started=time.monotonic()
    result=dict(passed=False,actual_model=True,physical_turn=False,source_sha256=source_hash,
        scope='Fresh normal branch Native unit candidates over actual retained T3 world; no physical commit, cold resume or controlled latency comparison',private_reasoning_read=False)
    try:
        orders,decisions=unit_planning.plan(session,prepared,observer,instruction=
            '这是原生单位候选功能核验，不执行物理回合。请先使用known_units最末条的detail_query读取当前详情，'
            '再依据当前权威状态与原意图自主提出本单位一项合法行动；需要其他目标细节也按ID读取。'
            '不要声称已移动、交战或取得战果，只提交原生候选。')
        assert len(packets)==len(orders)==len(decisions)==2
        for packet,decision in zip(packets,decisions):
            data=packet['packet'];index=data['known_units']
            assert len(index)==22 and len({r['id'] for r in index})==22
            assert data['known_units_view']['complete_registered_index']
            assert decision['proposal']['source']=='dsh_native_unit_order_tool'
            runs=[r for r in observer.runs if r['id'] in decision['run_ids']]
            from types import SimpleNamespace
            details=list(observation_results(SimpleNamespace(runs=runs)))
            assert any(a==index[-1]['detail_query'] and r['units'][0]['id']==index[-1]['id'] for a,r in details)
            context=unit_order_submission.context(session,prepared,decision['unit_id'],operation_id=observer.operation_id)
            proposal,proof=unit_order_submission.submitted(SimpleNamespace(runs=runs),context)
            assert proof==decision['proposal']
        assert session==saved and hashlib.sha256(source.read_bytes()).hexdigest()==source_hash
        result.update(passed=True,seconds=round(time.monotonic()-started,3),actors=22,native_units=2,
            prompt_chars=[p['prompt_chars'] for p in packets],all22indexed=True,both_tail_details_observed=True,
            old_world_and_source_unchanged=True,orders=orders,decisions=decisions,engine_meta=observer.meta())
        print('PASS actual2Native orders,all22indexed,taildetailtools and proofs; no physicalturn',flush=True)
    finally:
        stop.set();worker.join(timeout=1);unit_planning.h.unit_run=real_run
        result.setdefault('seconds',round(time.monotonic()-started,3))
        (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        (root/'public-runs.json').write_text(json.dumps(observer.runs,ensure_ascii=False,indent=2)+'\n')
        (root/'prompt-packets.json').write_text(json.dumps(packets,ensure_ascii=False,indent=2)+'\n')
        h.close_harness()


if __name__=='__main__':main()
