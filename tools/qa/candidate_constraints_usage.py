"""Check actual public model edits against the preceding conditional facts."""
import json
import argparse
import math
from pathlib import Path
from types import SimpleNamespace

from backend import turn_preview as p,effect_amendments as a
from gentactix import commands,missions

ROOT=Path('.cache/qa/candidate-constraints-2026-11-03')


def at(value,path):
    for part in path.lstrip('/').split('/'):
        part=part.replace('~1','/').replace('~0','~')
        value=value[int(part)] if isinstance(value,list) else value[part]
    return value


def same(actual,expected):
    if type(actual) in (int,float) and type(expected) in (int,float):return math.isclose(actual,expected,rel_tol=0,abs_tol=1e-6)
    return actual==expected


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',nargs='?')
    parser.add_argument('--root',type=Path,default=ROOT);parser.add_argument('--turn',type=int,default=8);args=parser.parse_args()
    root=args.root;output=root/(args.output or f'actual-t{args.turn}-diagnostic-usage.json')
    if output.exists():raise ValueError('Preserve previous evidence')
    before=json.loads((root/'turn-before-authoritative.json').read_text())
    after=json.loads((root/f'real-ui-t{args.turn}/turn-browser/authoritative-after.json').read_text());assert after['turn_count']==args.turn
    observer=SimpleNamespace(runs=after['trajectory'][-1]['runs'])
    native=[r['planned'] for r in after['command_state']['receipts'] if r['turn']==args.turn and r['source']=='native_unit_agent']
    ctx=p.context(before,commands.prepare(before),native_orders=native,operation_id=after['engine_last_meta']['operation_id'])
    rows=list(a.candidates(observer,ctx));batches=[]
    for index,(raw,reply,_,call) in enumerate(rows):
        facts=reply.get('calculation_diagnostics')
        if not facts or not facts['mismatches']:continue
        assert reply['ok'] is False and facts['complete_validation'] is False
        assert facts['candidate_hash']==reply['candidate_hash']==missions.digest(raw)
        assert facts['before_hash']==missions.digest(before['war_state'])
        assert facts['operation_id']==ctx['turn_preview']['operation_id']
        assert index+1<len(rows)
        following=rows[index+1][0];matches=[];unmatched=[]
        for fact in facts['mismatches']:
            try:
                # Identity at the original row must be retained; matching a
                # numeric value on another unit is not evidence of application.
                parts=fact['path'].split('/')
                row_path='/'.join(parts[:4] if parts[1] in ('resource_ledger','sustainment_ledger','fire_ledger') else parts[:3])
                selector='unit_name' if parts[1]=='decisions' else 'unit'
                assert at(following,row_path)[selector]==fact['unit']
                destination=matches if same(at(following,fact['path']),fact['expected']) else unmatched
            except (ValueError,KeyError,IndexError,TypeError,AssertionError):destination=unmatched
            destination.append(fact['path'])
        batches.append(dict(source_call=call,count=len(facts['mismatches']),matched_next_candidate=matches,
                            not_matched_or_dependencies_changed=unmatched))
    assert batches and sum(len(x['matched_next_candidate']) for x in batches)>0
    output.write_text(json.dumps(dict(passed=True,actual_model=True,physical_turn=args.turn,scope='Public generated edits match observed facts; no private reasoning or controlled causal/latency claim',
        readonly_failed_replies_preserved=True,world_candidate_operation_bindings_verified=True,
        batches=batches,total_facts=sum(x['count'] for x in batches),
        matching_paths_in_next_candidate=sum(len(x['matched_next_candidate']) for x in batches)),ensure_ascii=False,indent=2)+'\n')
    print('PASS observed facts',sum(x['count'] for x in batches),'matching next candidate paths',sum(len(x['matched_next_candidate']) for x in batches),flush=True)


if __name__=='__main__':main()
