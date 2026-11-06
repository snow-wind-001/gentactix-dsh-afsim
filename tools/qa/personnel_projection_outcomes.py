"""Summarize terminal public tool I/O, including refusals; never read reasoning."""
import argparse
from collections import Counter
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session', type=Path, help='Typed terminal product export')
    parser.add_argument('output', type=Path)
    parser.add_argument('--turn', type=int, default=2, help='Expected attempted turn, including a noncommitted failure')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Preserve previous evidence')
    if args.turn < 1:
        parser.error('Expected turn must be positive')
    session = json.loads(args.session.read_text())
    if session['turn_count'] == args.turn:
        record = session['trajectory'][-1]
        assert record['turn'] == args.turn
        accepted = True
    else:
        record = session['failed_operations'][-1]
        assert session['turn_count'] == args.turn-1 and record['turn'] == args.turn-1
        accepted = False
    calls = {}
    seen = set()
    rows = []
    counts = Counter()
    for run in record['runs']:
        for event in run.get('events', []):
            sid, seq, kind = (event.get(k) for k in ('session_id', 'seq', 'type'))
            stamp = (sid, seq, kind)
            if stamp in seen:
                continue
            seen.add(stamp)
            if kind == 'tool/call':
                raw = event.get('arguments')
                counts[event.get('name')] += 1
                calls[(sid, event.get('callId'))] = dict(name=event.get('name'),
                    arguments_chars=len(raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)))
            elif kind == 'tool/result':
                message = event.get('message') or {}
                call = calls.get((sid, message.get('toolCallId')))
                if call is None:
                    continue
                text = '\n'.join(b.get('text', '') for b in message.get('content', []) if b.get('type') == 'text')
                try:
                    reply = json.loads(text)
                except json.JSONDecodeError:
                    rows.append(dict(**call, runtime_error=bool(event.get('isError') or message.get('isError')),
                                     result_is_json=False))
                    continue
                if not isinstance(reply, dict):
                    continue
                rows.append(dict(**call, ok=reply.get('ok'),
                    error=reply.get('error'), issues=reply.get('issues'),
                    settlement_version=(reply.get('settlement') or {}).get('version'),
                    listed_units=len((reply.get('settlement') or {}).get('units', []))))
    result = dict(session_id=session['id'], turn=session['turn_count'], committed=accepted,
        runs=[{k: r.get(k) for k in ('id', 'session_id', 'finish_reason', 'rejection', 'event_count', 'output_diagnostics')}
              for r in record['runs']], tool_counts=dict(counts), tool_results=rows,
        compactions=sum(e.get('type') == 'compaction/end' for r in record['runs'] for e in r.get('events', [])),
        private_reasoning_read=False,
        scope='Terminal product trajectory public tool facts only; no semantic or historical accuracy claim')
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(committed=accepted, turn=session['turn_count'], tool_counts=dict(counts),
        compactions=result['compactions'], refusals=[r for r in rows if r.get('ok') is False]), ensure_ascii=False))


if __name__ == '__main__':
    main()
