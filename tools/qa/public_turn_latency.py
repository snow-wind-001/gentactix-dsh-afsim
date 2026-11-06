"""Measure a completed turn from exported public event metadata, without text reasoning."""
import argparse
import json
from collections import Counter
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--attempted-turn',type=int,help='Include a rejected next attempt instead of the last committed turn')
    args=parser.parse_args()
    if args.output.exists():parser.error('Preserve earlier evidence')
    session=json.loads(args.session.read_text())
    attempted=session['turn_count'] if args.attempted_turn is None else args.attempted_turn
    committed=session['turn_count']==attempted
    if committed:
        trace=session['trajectory'][-1]
        assert trace['turn']==attempted
    else:
        if session['turn_count']!=attempted-1:parser.error('Expected the committed or immediately rejected next turn')
        trace=next((r for r in reversed(session.get('failed_operations',[]))
                    if r.get('phase')=='next' and r.get('turn')==attempted-1),None)
        if trace is None:parser.error('No retained failed operation for this attempt')
    results=[]
    for run in trace['runs']:
        events=run.get('events',[]);calls={};rows=[];usage=[];seen=set()
        for event in events:
            stamp=(event.get('session_id'),event.get('seq'),event.get('type'))
            if stamp in seen:continue
            seen.add(stamp)
            if event.get('usage'):usage.append(event['usage'])
            if event['type']=='tool/call':
                raw=event.get('arguments','')
                calls[event['callId']]=dict(name=event['name'],time=event.get('time'),
                    arguments_chars=len(raw if isinstance(raw,str) else json.dumps(raw,ensure_ascii=False)))
            elif event['type']=='tool/result':
                message=event.get('message') or {};call=calls.get(message.get('toolCallId'))
                if not call:continue
                text='\n'.join(b.get('text','') for b in message.get('content',[]) if b.get('type')=='text')
                try:reply=json.loads(text)
                except json.JSONDecodeError:reply={}
                start=call['time'];end=event.get('time')
                rows.append(dict(name=call['name'],arguments_chars=call['arguments_chars'],
                    seconds=(end-start)/1000 if type(start) in (int,float) and type(end) in (int,float) else None,
                    ok=reply.get('ok') if isinstance(reply,dict) else None))
        times=[e['time'] for e in events if type(e.get('time')) in (int,float)]
        results.append(dict(run_id=run['id'],session_id=run['session_id'],finish_reason=run['finish_reason'],
            public_event_span_seconds=(max(times)-min(times))/1000,
            paired_tool_seconds_sum=round(sum(r['seconds'] or 0 for r in rows),3),
            tool_counts=dict(Counter(r['name'] for r in rows)),tools=rows,
            model_responses_with_usage=len(usage),
            response_output_tokens_sum=sum(u.get('outputTokens',0) for u in usage),
            largest_reported_total_tokens=max((u.get('totalTokens',0) for u in usage),default=0),
            native_compactions=sum(e['type']=='compaction/end' for e in events)))
    value=dict(session_id=session['id'],turn=session['turn_count'],attempted_turn=attempted,committed=committed,
        prompt_chars=len(trace['prompt']) if isinstance(trace.get('prompt'),str) else None,
        engine_metadata=session.get('engine_last_meta') if committed else None,runs=results,
        public_event_span_seconds_sum=round(sum(r['public_event_span_seconds'] for r in results),3),
        paired_tool_seconds_sum=round(sum(r['paired_tool_seconds_sum'] for r in results),3),
        response_output_tokens_sum=sum(r['response_output_tokens_sum'] for r in results),
        scope='Public timestamps and usage counters only. Tool spans include IPC and validation; remaining time includes model, runtime scheduling and compaction, not isolated model generation or token throughput.',
        private_reasoning_read=False)
    args.output.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:value[k] for k in ('prompt_chars','public_event_span_seconds_sum','paired_tool_seconds_sum','response_output_tokens_sum')},ensure_ascii=False))


if __name__=='__main__':main()
