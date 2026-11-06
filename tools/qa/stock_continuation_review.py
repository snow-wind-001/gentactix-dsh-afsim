"""Replay actual T5 public evidence with the current report guard, read only.

No model call, fabricated tool result, world commit or original evidence edit.
"""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

from backend import dsh_simulation, turn_preview
from gentactix import commands, missions, reporting


ROOT = Path('.cache/qa/stock-continuation-2026-11-03')
SOURCE = Path('.cache/qa/operation-clock-2026-11-03/turn-browser')


def main():
    output = ROOT / 'actual-t5-public-replay.json'
    if output.exists():
        raise SystemExit('Preserve previous evidence')
    before = json.loads((SOURCE / 'authoritative-before.json').read_text())
    after = json.loads((SOURCE / 'authoritative-after.json').read_text())
    original = copy.deepcopy((before, after))
    trace = after['trajectory'][-1]
    observer = SimpleNamespace(runs=trace['runs'])
    run = trace['runs'][-1]
    reports = [json.loads(e['arguments']) for e in run['events']
               if e['type'] == 'tool/call' and e.get('name') == turn_preview.REPORT_TOOL]
    assert len(reports) == 2
    first = reports[0]
    quote = '第90师弹药工作量由28降至5，随队炮弹归零'
    assert quote in first['report']
    before_unit = next(u for u in before['war_state']['red_units'] if u['name'] == '第90师')
    after_unit = next(u for u in after['war_state']['red_units'] if u['name'] == '第90师')
    assert (before_unit['logistics']['ammo'], after_unit['logistics']['ammo'],
            before_unit['formation']['shells'], after_unit['formation']['shells']) == (28, 5, 92, 0)
    issues = reporting.inspect(first['report'], after['war_state'], before['war_state'], turn=5)
    assert not issues, issues
    receipts = [r for r in after['command_state']['receipts'] if r['turn'] == 5]
    native = [r['planned'] for r in receipts if r['source'] == 'native_unit_agent']
    ctx = turn_preview.context(before, commands.prepare(before), native_orders=native,
                               operation_id=after['engine_last_meta']['operation_id'])
    saved_context = copy.deepcopy(ctx)
    events = []
    calls = set()
    for event in run['events']:
        if event['type'] == 'tool/call' and event.get('name') in (turn_preview.TOOL, 'amend_turn_effects'):
            calls.add(event['callId'])
        elif not (event['type'] == 'tool/result'
                  and event.get('message', {}).get('toolCallId') in calls):
            continue
        events.append(dict(seq=event['seq'], type=event['type'],
                           data={k: v for k, v in event.items() if k not in ('seq', 'type', 'session_id')}))
    payload = dict(tool=turn_preview.REPORT_TOOL, session_id=run['session_id'],
                   args=copy.deepcopy(first), preview_events=events)
    accepted = turn_preview.submit_report(ctx, payload)
    assert accepted['ok'], accepted
    contradicted = copy.deepcopy(payload)
    contradicted['args']['report'] = quote.replace('炮弹归零', '炮弹未耗尽')
    denied = turn_preview.submit_report(ctx, contradicted)
    assert not denied['ok'] and any(i['code'] == 'inventory_claim' for i in denied['issues']), denied
    forged = copy.deepcopy(payload)
    forged['args']['preview_hash'] = '0' * 64
    assert not turn_preview.submit_report(ctx, forged)['ok']
    submitted = turn_preview.submitted_report(observer, ctx)
    candidate, proof = turn_preview.resolve(submitted[0], observer, ctx)
    world = dsh_simulation.apply(before['war_state'], candidate, before['time_step'], require_fire_ledger=True)
    assert missions.digest(world) == proof['after_hash'] == missions.digest(after['war_state'])
    assert (before, after) == original and ctx == saved_context
    output.write_text(json.dumps(dict(passed=True, actual_model=False, physical_turn=False,
        session_id=after['id'], turn=5, quote=quote, ammo_before=28, ammo_after=5,
        shells_before=92, shells_after=0, original_first_report=first['report'],
        current_first_report_reply=accepted, contradicted_claim_reply=denied,
        forged_preview_rejected=True, original_final_chain_and_world_hash_preserved=True,
        state_context_and_original_events_unchanged=True,
        scope='Current host revalidation of actual T5 public evidence; no new SDK call or battle commit; '
              'original refused event remains refused and original committed report is not replaced'),
        ensure_ascii=False, indent=2) + '\n')
    print('PASS real T5 original report, bound Native host replay, contradictions and world hash')


if __name__ == '__main__':
    main()
