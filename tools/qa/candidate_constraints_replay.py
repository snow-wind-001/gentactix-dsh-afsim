"""Replay old real public candidates and final proof; no runtime/model call."""
import copy
import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from backend import dsh_simulation,turn_preview as p,effect_amendments as a
from gentactix import commands,missions

ROOT=Path('.cache/qa/candidate-constraints-2026-11-03')
OLD=Path('.cache/qa/checkpoint-definitions-2026-11-03')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--source',type=Path,default=OLD);parser.add_argument('--turn',type=int,default=7)
    parser.add_argument('--expected-candidates',type=int,default=13);parser.add_argument('--expected-calls',type=int,default=14);args=parser.parse_args()
    output=args.root/f'actual-t{args.turn}-public-replay.json'
    if output.exists():raise ValueError('Preserve previous evidence')
    before=json.loads((args.source/'turn-before-authoritative.json').read_text())
    after=json.loads((args.source/f'real-ui-t{args.turn}/turn-browser/authoritative-after.json').read_text())
    trace=after['trajectory'][-1];assert trace['turn']==args.turn
    observer=SimpleNamespace(runs=trace['runs'])
    native=[r['planned'] for r in after['command_state']['receipts'] if r['turn']==args.turn and r['source']=='native_unit_agent']
    operation=after['engine_last_meta']['operation_id'];assert len(native)==2
    ctx=p.context(before,commands.prepare(before),native_orders=native,operation_id=operation)
    saved=copy.deepcopy(ctx);rows=[]
    for raw,old_reply,sid,call in a.candidates(observer,ctx):
        original=copy.deepcopy(raw)
        reply=p.execute(ctx,dict(tool=p.TOOL,args=dict(candidate=raw)))
        assert ctx==saved and raw==original
        assert reply['ok']==old_reply['ok']
        if reply['ok']:assert reply['after_hash']==old_reply['after_hash']
        facts=reply.get('calculation_diagnostics')
        if facts:
            assert facts['before_hash']==reply['before_hash'] and facts['candidate_hash']==reply['candidate_hash']
        rows.append(dict(original_call=call,accepted=reply['ok'],old_error=old_reply.get('error'),
            new_error=reply.get('error'),mismatch_count=len(facts['mismatches']) if facts else 0,
            mismatches=facts['mismatches'] if facts else [],unavailable=facts['unavailable'] if facts else []))
    submitted=p.submitted_report(observer,ctx);assert submitted
    value,proof=p.resolve(submitted[0],observer,ctx)
    world=dsh_simulation.apply(before['war_state'],value,before['time_step'],require_fire_ledger=True)
    assert missions.digest(world)==proof['after_hash']==missions.digest(after['war_state'])
    calls={(e.get('session_id'),e.get('seq')) for run in observer.runs for e in run.get('events',[])
        if e.get('type')=='tool/call' and e.get('name') in (p.TOOL,a.AMEND_TOOL)}
    assert len(calls)==args.expected_calls
    assert len(rows)==args.expected_candidates and any(r['mismatch_count']>1 for r in rows if not r['accepted']),(len(rows),[r['mismatch_count'] for r in rows])
    output.write_text(json.dumps(dict(passed=True,actual_model=False,new_physical_turn=False,
        prior_actual_turn=args.turn,candidate_count=len(rows),original_calls=len(calls),calls_without_replayable_candidate=len(calls)-len(rows),old_acceptance_outcomes_preserved=True,
        original_complete_final_world_hash_preserved=True,all_candidates_and_contexts_unchanged=True,
        rows=rows,private_reasoning_read=False,
        scope='Current host replay of retained public candidates and complete final proof; calls without a raw candidate are counted separately. No new model, historical or performance acceptance.'),ensure_ascii=False,indent=2)+'\n')
    print('PASS',len(rows),'replayable real public candidates and original full final hash; first mismatch batch',rows[0]['mismatch_count'],flush=True)


if __name__=='__main__':main()
