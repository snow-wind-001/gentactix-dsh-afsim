"""Audit a completed real Native turn from public evidence; never advance it."""
import argparse
import json
import math
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--live', action='store_true')
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--before', type=Path, required=True)
    p.add_argument('--snapshot', type=Path, help='Audit a retained earlier export without querying or advancing the live session')
    p.add_argument('--native-world', type=Path)
    args = p.parse_args()
    if not args.live and not args.snapshot:
        p.error('Use --live for the owned isolated API, or --snapshot for a retained export')
    root = args.root
    info = json.loads((root / 'turn-case.json').read_text())
    if not info['api'].startswith('http://127.0.0.1:19'):
        p.error('Only an owned isolated QA endpoint is allowed')
    out = root / 'completion-review.json'
    if out.exists():
        raise ValueError('Preserve previous evidence')
    from backend import session_store, extensions
    from gentactix import missions, support_dynamics as sd

    def get(path):
        with urlopen(info['api'] + path, timeout=60) as response:
            return json.load(response)

    base = '/api/sessions/' + info['session_id']
    if args.snapshot:
        after = json.loads(args.snapshot.read_text())
    else:
        assert not get(base + '/progress')['active']
        after = get(base + '/export')['session']
    before = json.loads(args.before.read_text())
    session_store.validate(after)
    assert after['id'] == before['id'] == info['session_id']
    assert before['turn_count'] == info['turn'] - 1 and after['turn_count'] == info['turn']
    world, old = after['war_state'], before['war_state']
    assert world['historical_initial'] == old['historical_initial']
    assert world['simulation_clock']['elapsed_seconds'] - old['simulation_clock']['elapsed_seconds'] == info['step_seconds']
    assert len(missions.units(world)) == info['actor_count']
    trace = after['trajectory'][-1]
    assert trace['before'] == old and trace['after'] == world
    assert all(r['finish_reason'] == 'completed' for r in trace['runs'])
    assert after.get('failed_operations', [])[:len(before.get('failed_operations', []))] == before.get('failed_operations', [])
    assert after['command_state']['intent'] == before['command_state']['intent']
    receipts = [r for r in after['command_state']['receipts'] if r['turn'] == info['turn']]
    assert len(receipts) == info['actor_count']
    decisions = [d for d in trace['decisions'] if d.get('source') == 'native_unit_agent']
    assert len(decisions) == info['native_decision_count']
    run_ids = {r['session_id'] for r in trace['runs']}
    for decision in decisions:
        binding = after['command_state']['agent_sessions'][decision['unit_id']]
        assert decision['proposal']['session_id'] == binding['session_id']
        assert binding['session_id'] in run_ids
        assert decision['proposal']['source'] == 'dsh_native_unit_order_tool'
    observer = SimpleNamespace(runs=trace['runs'])
    reports = list(extensions.public_tool_results(observer, 'submit_turn_report'))
    assert len(reports) == 1, 'Exactly one accepted report, not repeated accepted authoring'
    _, reply, evidence = reports[0]
    assert reply['next_action'] == 'final_response'
    engine = next(r for r in trace['runs'] if r['session_id'] == evidence['session_id'])
    end = next(e for e in engine['events'] if e['type'] == 'tool/result'
               and e.get('message', {}).get('toolCallId') == evidence['call_id'])
    assert not any(e['type'] == 'tool/call' and e['seq'] > end['seq'] for e in engine['events'])
    headers = [e for e in engine['events'] if e['type'] == 'request/header']
    ending_headers = [e for e in headers if e['seq'] > end['seq']]
    authoring_headers = [e for e in headers if e['seq'] < end['seq']]
    assert len(ending_headers) == 1 and ending_headers[0]['tools'] == []
    assert any('submit_turn_report' in e['tools'] for e in authoring_headers)
    assert ending_headers[0]['request_config'] == authoring_headers[-1]['request_config']
    if info.get('restored_native_bindings'):
        for unit_id, binding in info['restored_native_bindings'].items():
            assert after['command_state']['agent_sessions'][unit_id]['session_id'] == binding['session_id']
    native = json.loads(args.native_world.read_text()) if args.native_world else None
    cfg = sd.configuration(world)
    ledger = {r['unit']: r for r in world['mission']['ledger']}
    people = 0
    breakdown_shape_differs = False
    for team, unit in missions.units(world):
        prior = next(u for t, u in missions.units(old) if t == team and u['name'] == unit['name'])
        assert unit['historical_unit_id'] == prior['historical_unit_id']
        # Initial generation has no carry marker; effect validation records
        # carried_forward=False. Preserve every ledger field, compare that
        # provenance marker separately rather than calling it a casualty.
        personnel = lambda value: {k: v for k, v in value.items() if k != 'carried_forward'}
        assert personnel(unit['personnel']) == personnel(prior['personnel'])
        physical = lambda e: {k: v for k, v in e.items() if k not in {'carried_forward', 'calculation_source'}}
        assert [physical(e) for e in unit['equipment']] == [physical(e) for e in prior['equipment']]
        people += unit['personnel']['current']
        row = ledger[unit['name']]
        assert row['food_received'] == row['ammo_received'] == row['ammo_spent'] == 0
        assert math.isclose(prior['logistics']['food'] - row['food_spent'], unit['logistics']['food'], abs_tol=1e-9)
        for field in ('lat', 'lng'):
            assert unit[field] == prior[field]
        if native:
            peer = next(u for t, u in missions.units(native) if t == team and u['name'] == unit['name'])
            for field in ('committed', 'current', 'casualties', 'noncombat_losses'):
                assert unit['personnel'][field] == peer['personnel'][field]
            categories = ('killed', 'wounded', 'captured', 'missing', 'unclassified_casualties')
            for field in categories:
                if field in unit['personnel'] and field in peer['personnel']:
                    assert unit['personnel'][field] == peer['personnel'][field]
                elif (field in unit['personnel']) != (field in peer['personnel']):
                    # The legacy DSH ledger may lack category keys. A zero
                    # aggregate is comparable here; do not invent those keys
                    # or claim full breakdown/provenance object equality.
                    breakdown_shape_differs = True
                    assert unit['personnel']['casualties'] == peer['personnel']['casualties'] == 0
                    assert unit['personnel'].get(field, 0) == peer['personnel'].get(field, 0) == 0
            assert [physical(e) for e in unit['equipment']] == [physical(e) for e in peer['equipment']]
            assert math.isclose(unit['logistics']['food'], peer['logistics']['food'], abs_tol=1e-6)
            for field in sd.RECEIPT_FIELDS:
                assert math.isclose(unit['sustainment']['last_receipt'][field], peer['sustainment']['last_receipt'][field], abs_tol=1e-6)
    result = dict(passed=True, session_id=after['id'], turn=after['turn_count'],
                  reviewed_from_snapshot=str(args.snapshot) if args.snapshot else None,
                  operation_id=after['engine_last_meta']['operation_id'],
                  wall_elapsed_ms=after['engine_last_meta']['wall_elapsed_ms'],
                  completed_native_runs=len(trace['runs']), native_unit_decisions=len(decisions),
                  accepted_reports=1, no_tool_calls_after_report=True, original_intent_preserved=True,
                  one_actual_tool_free_completion_request=True,
                  model_reasoning_and_token_policy_unchanged=True,
                  restored_native_bindings_reused=bool(info.get('restored_native_bindings')),
                  earlier_failures_retained=True, personnel=people,
                  food_kg=sum(sd.food_mass(cfg, u) for _, u in missions.units(world)),
                  native_nutrition_and_core_ledger_parity_checked=native is not None,
                  personnel_breakdown_shape_differs=breakdown_shape_differs,
                  historical_calibration=False, full_history_accepted=False,
                  scope='Real committed turn and public protocol/physical accounts; not whole-text semantic or historical acceptance.')
    target = root / ('t' + str(info['turn']) + '-canonical.json')
    encoded = json.dumps(after, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if target.exists():
        assert target.read_text() == encoded
    else:
        target.write_text(encoded)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
