"""Rebuild command receipts from immutable live traces, without changing a run.

Checks current receipt projection against actual native command delivery. This
is not a model/native rerun and does not upgrade the source run's acceptance.
"""
import argparse
import copy
import json
from pathlib import Path

from gentactix import commands, missions


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    results=[]
    for path in sorted((args.run/'traces').rglob('turn-*.json')):
        trace=json.loads(path.read_text());context=trace.get('command_context')
        if not context or not trace.get('after'):continue
        before=trace['before'];after=trace['after'];original=copy.deepcopy((before,after))
        turn=trace['turn'];s={'id':'c01234567890','role_epoch':0,'war_state':before,
            'turn_count':turn-1,'time_step':trace['time_step'],
            'simulation_mode':'open','execution_backend':'afsim'}
        view=commands.view(s);by_name={u['name']:u for u in view['units']}
        drafts=[]
        for item in context['manual']:
            stored=item['command'];draft={k:copy.deepcopy(stored[k]) for k in
                ('action','duration','end_turn','destination') if k in stored}
            draft['unit_id']=by_name[item['order']['unit']]['id']
            if item['order'].get('target'):draft['target_id']=by_name[item['order']['target']]['id']
            drafts.append(draft)
        policies={k:context['policies'][k] for k in ('control_team','director','no_fire','intent')}
        s['command_state']=commands.replace_queue(s,drafts,**policies)
        prepared=commands.prepare(s)
        state,_=commands.finish(s,prepared,after,executed=after['mission']['last_orders'],
            rationales=trace['decisions'],runs=trace['runs'])
        native={u['name']:u['formation']['last_execution'] for _,u in missions.units(after)}
        rows=[]
        for receipt in state['receipts']:
            execution=native[receipt['unit_name']]
            assert execution['turn']==turn
            if execution['command_done']==0:
                assert receipt['status']!='completed',(turn,receipt['unit_name'])
                rows.append({'unit':receipt['unit_name'],'planned_action':receipt['action'],
                    'status':receipt['status'],'reason':receipt['reason'],'native_command_done':0})
        assert (before,after)==original,'Read-only receipt projection changed the world'
        results.append({'turn':turn,'native_artifact':after['afsim']['artifact'],
            'receipt_count':len(state['receipts']),'undelivered':rows,'passed':True})
    assert results,'No completed live traces to review'
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps({'scope':'read-only receipt projection over existing native evidence',
        'model_calls':0,'native_reruns':0,'passed':True,'turns':results},ensure_ascii=False,indent=2))
    print(json.dumps({'turns':len(results),'receipts':sum(x['receipt_count'] for x in results),
        'undelivered':sum(len(x['undelivered']) for x in results),'passed':True},ensure_ascii=False))


if __name__=='__main__':main()
