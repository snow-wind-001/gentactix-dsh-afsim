"""Check actual unit proposal completion using public calls and request headers."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('export',type=Path)
    parser.add_argument('first_frame',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    if args.output.exists():raise ValueError('Preserve prior completion evidence')
    from backend import extensions
    current=json.loads(args.export.read_text());first=json.loads(args.first_frame.read_text())
    assert current['id']==first['id']
    old={k:v['session_id']for k,v in first['command_state']['agent_sessions'].items()}
    bindings={k:v['session_id']for k,v in current['command_state']['agent_sessions'].items()}
    assert old==bindings and len(bindings)==2
    trace=current['trajectory'][-1];rows=[]
    decisions=[d for d in trace['decisions']if d.get('source')=='native_unit_agent']
    assert len(decisions)==2
    for decision in decisions:
        sid=bindings[decision['unit_id']];assert decision['proposal']['session_id']==sid
        run=next(r for r in trace['runs']if r['session_id']==sid)
        assert run['finish_reason']=='completed'
        observer=SimpleNamespace(runs=[run])
        candidates=list(extensions.public_tool_results(observer,'submit_unit_order'))
        assert len(candidates)==1,'Exactly one accepted unit proposal'
        _,reply,evidence=candidates[0]
        assert reply['next_action']=='final_response'
        end=next(e for e in run['events']if e['type']=='tool/result'and e.get('message',{}).get('toolCallId')==evidence['call_id'])
        assert not any(e['type']=='tool/call'and e['seq']>end['seq']for e in run['events'])
        authoring=[e for e in run['events']if e['type']=='request/header'and e['seq']<end['seq']]
        ending=[e for e in run['events']if e['type']=='request/header'and e['seq']>end['seq']]
        assert any('submit_unit_order'in h['tools']for h in authoring)
        assert len(ending)==1 and ending[0]['tools']==[]
        assert ending[0]['request_config']==authoring[-1]['request_config']
        policy={k:v for k,v in ending[0]['request_config'].items()if k in ('maxTokens','max_tokens','reasoningEffort','reasoning_effort')}
        rows.append(dict(unit_id=decision['unit_id'],sdk_session_id=sid,action=decision['action'],
            accepted_proposals=1,ending_requests=1,ending_tools=[],same_request_policy=True,request_policy=policy,
            run_completed_normally=True,original_binding_retained=True))
    args.output.write_text(json.dumps(dict(passed=True,session_id=current['id'],turn=current['turn_count'],units=rows,
        scope='Actual same-SDK unit proposal completion and normal host commit; not a controlled latency comparison or historical calibration.'),ensure_ascii=False,indent=2)+'\n')
    print('PASS actual Native completion for both original SDK unit sessions at T',current['turn_count'])


if __name__=='__main__':main()
