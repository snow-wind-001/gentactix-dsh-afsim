"""Real SDK validation of a retained full22 candidate; no physical commit."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import uuid


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true');parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if not args.live:parser.error('--live required')
    root=args.out
    if root.exists():parser.error('Preserve previous Native evidence')
    root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str((root/suffix).resolve())
    from backend import harness_engine as h,runtime_bridge,turn_preview as p,dsh_simulation
    from backend.main import _native_tool_dispatch
    from backend.extensions import public_tool_results
    from gentactix import commands,missions,turn_settlement
    old=Path('.cache/qa/personnel-projection-2026-11-02/real-ui-t2-fixed')
    source_path=old/'authoritative-before.json';source_hash=hashlib.sha256(source_path.read_bytes()).hexdigest()
    session=json.loads(source_path.read_text());session['id']=uuid.uuid4().hex[:12]
    accepted=json.loads((old/'authoritative-after.json').read_text())
    observer=h.RunObserver('Full22 Native candidate paging and inventory negation')
    prior=SimpleNamespace(runs=accepted['trajectory'][-1]['runs'])
    original=list(public_tool_results(prior,p.TOOL))[-1][0]['candidate']
    native=[r['planned'] for r in accepted['command_state']['receipts']
            if r['turn']==2 and r['source']=='native_unit_agent']
    ctx=p.context(session,commands.prepare(session),native_orders=native,operation_id=observer.operation_id)
    expected=dsh_simulation.apply(session['war_state'],p.normalize(ctx,original),session['time_step'],require_fire_ledger=True)
    saved=copy.deepcopy(session);captures=[]
    def dispatch(context,payload):
        reply=_native_tool_dispatch(context,payload)
        if payload.get('tool') in (p.READ_TOOL,p.REPORT_TOOL):
            captures.append(dict(tool=payload['tool'],args=copy.deepcopy(payload['args']),reply=copy.deepcopy(reply)))
        print('TOOL',payload.get('tool'),reply.get('ok'),str(reply.get('error',''))[:120],flush=True)
        return reply
    runtime_bridge.register_dispatcher(dispatch)
    report='炮兵第2团第3营炮弹与弹药工作量均未耗尽。炮兵第1团第6连炮弹与弹药工作量均未耗尽。'
    prompt=('这是只读工具集成验收，原候选来自已经完成的实际22单位回合，所有数值仍是计算估计，不是史实标定。'
        '不规划新行动、不更改候选、不执行或提交世界。\n'
        '1. 将下方完整既有候选原样传给preview_turn_effects。\n'
        '2. 用成功digest调用get_turn_preview(kind="units",offset=16,limit=16)读取末6条，再offset=0读取前16条，核对共22单位。\n'
        '3. 用该digest调用submit_turn_report，report严格为“全军弹药未耗尽。”；这一步应被范围检查拒收，保留反馈，不改效果。\n'
        '4. 仍用同一digest调用submit_turn_report，report严格为：'+report+'\n'
        '   此句应根据分页的当前炮弹及弹药正库存通过。最后只需简短确认，不重复候选或输出私有推理。\n'
        '既有完整候选：'+json.dumps(original,ensure_ascii=False))
    stop=threading.Event()
    def monitor():
        while not stop.wait(15):
            print('WAIT_NATIVE',json.dumps({k:observer.progress.get(k) for k in ('steps','turns','runtime_state','tokens')},ensure_ascii=False),flush=True)
    worker=threading.Thread(target=monitor,daemon=True);worker.start();began=time.monotonic()
    result=dict(passed=False,actual_model=True,actors=22,source_file=str(source_path),source_sha256=source_hash,
        scope='Readonly actual SDK reuse of retained full22 public candidate; not a new physical turn, historical calibration or latency benchmark',private_reasoning_read=False)
    try:
        run=h._run_brain(prompt,None,role='engine',observer=observer,native_context=ctx)
        result.update(seconds=round(time.monotonic()-began,3),finish_reason=run.finish_reason,captures=captures)
        actual_preview=list(public_tool_results(observer,p.TOOL))[-1]
        actual=dsh_simulation.apply(session['war_state'],p.normalize(ctx,actual_preview[0]['candidate']),session['time_step'],require_fire_ledger=True)
        result['literal_old_candidate_world_match']=missions.digest(actual)==missions.digest(expected)
        # Check the digest of the ACTUAL proposed candidate, including all its
        # prose. An earlier request to copy a description verbatim is a separate
        # model-obedience check, not the candidate paging protocol's hash basis.
        pages=[r for r in captures if r['tool']==p.READ_TOOL and r['reply'].get('ok')]
        seen={(r['team'],r['name']):r for page in pages for r in page['reply']['items']}
        expected_rows={(r['team'],r['name']):r for r in turn_settlement.build(expected,session['war_state'])['units']}
        assert seen.keys()==expected_rows.keys() and len(seen)==22
        for identity,row in expected_rows.items():
            for key,value in row.items():assert seen[identity][key]==value,(identity,key)
        assert all(page['reply']['after_hash']==missions.digest(actual)==actual_preview[1]['after_hash'] for page in pages)
        denied=[r for r in captures if r['tool']==p.REPORT_TOOL and r['args']['report']=='全军弹药未耗尽。']
        assert denied and all(not r['reply']['ok'] and any(i['code']=='inventory_claim' and i.get('quote') for i in r['reply']['issues']) for r in denied)
        final=p.submitted_report(observer,ctx);assert final and final[0]['report']==report
        assert session==saved and hashlib.sha256(source_path.read_bytes()).hexdigest()==source_hash
        result.update(passed=True,actual_page_units=22,both_sides=True,world_unchanged=True,unknown_scope_rejected=True,
            negative_claim_accepted=True,report_proof=final[1],runs=[{k:r.get(k) for k in ('id','session_id','finish_reason','event_count')} for r in observer.runs])
        print('PASS real SDK full22 pages, scoped positive-stock negation and global-scope refusal; no commit',flush=True)
    finally:
        stop.set();worker.join(timeout=1)
        result.setdefault('seconds',round(time.monotonic()-began,3));result.setdefault('captures',captures)
        (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        (root/'public-runs.json').write_text(json.dumps([dict(id=r['id'],session_id=r.get('session_id'),
            finish_reason=r.get('finish_reason'),events=[e for e in r.get('events',[]) if e.get('type') in ('tool/call','tool/result')]) for r in observer.runs],ensure_ascii=False,indent=2)+'\n')
        h.close_harness()


if __name__=='__main__':main()
