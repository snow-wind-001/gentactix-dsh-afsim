"""Audit the accepted full22 UI branch using public SDK tools and typed exports."""
import argparse
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import urllib.request

from backend import afsim_state, dsh_simulation, turn_preview
from backend.extensions import public_tool_results
from gentactix import commands, missions, movement_feedback, personnel_projection
from gentactix import reporting
from .unit_order_retry_audit import audit


ROOT = Path('.cache/qa/personnel-projection-2026-11-02')


def save(path, value):
    if path.exists():
        raise ValueError('Preserve earlier evidence: ' + str(path))
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--directory', type=Path, default=ROOT / 'real-ui-t2')
    parser.add_argument('--before', type=Path, default=ROOT / 'branch-pre-advance.json')
    parser.add_argument('--api-root',default='http://127.0.0.1:19227')
    args = parser.parse_args()
    if not args.live:
        parser.error('--live required to read the owned terminal QA API')
    directory = args.directory
    terminal = json.loads((directory / 'result.json').read_text())
    if not terminal.get('passed'):
        raise ValueError('Original real UI turn did not pass; preserve failure')
    sid = terminal['session_id']
    import re
    if not re.fullmatch(r'http://127\.0\.0\.1:\d+',args.api_root):
        parser.error('Owned local QA API required')
    url = args.api_root+'/api/sessions/' + sid
    with urllib.request.urlopen(url + '/progress') as response:
        if json.load(response)['active']:
            raise ValueError('Do not snapshot an in-flight operation')
    before = json.loads(args.before.read_text())
    with urllib.request.urlopen(url + '/export') as response:
        after = json.load(response)['session']
    save(directory / 'authoritative-before.json', before)
    save(directory / 'authoritative-after.json', after)
    result = audit(directory, authoritative_before=directory / 'authoritative-before.json',
                   authoritative_after=directory / 'authoritative-after.json')
    trace = after['trajectory'][-1]
    observer = SimpleNamespace(runs=trace['runs'])
    previews = [r for tool in (turn_preview.TOOL,'amend_turn_effects')
                for r in public_tool_results(observer,tool)]
    assert previews, 'Missing successful actual preview'
    operations={r[1]['operation_id'] for r in previews}
    assert len(operations)==1, 'Successful previews cross operation boundaries'
    operation = operations.pop()
    receipts = [r for r in after['command_state']['receipts'] if r['turn'] == after['turn_count']]
    assert len(receipts) == 22
    native_orders = [r['planned'] for r in receipts if r['source'] == 'native_unit_agent']
    ctx = turn_preview.context(before, commands.prepare(before), native_orders=native_orders,
                               operation_id=operation)
    submitted = turn_preview.submitted_report(observer, ctx)
    assert submitted, 'Missing actual Native report proposal'
    candidate, proof = turn_preview.resolve(submitted[0], observer, ctx)
    assert proof['settlement_version'] == 'turn-settlement-3'
    world = dsh_simulation.apply(before['war_state'], candidate, before['time_step'], require_fire_ledger=True)
    assert missions.digest(world) == missions.digest(after['war_state']) == proof['after_hash']
    summary = reporting.turn_settlement_summary(world, before['war_state'])
    assert missions.digest(summary) == proof['settlement_hash']
    orders = [dict(r['planned'], unit=r['unit_name'], action=r['action']) for r in receipts]
    motion = movement_feedback.validate_transition(before['war_state'], world, orders, 3600,
                                                  source='dsh_model_estimate')
    assert motion == world['dsh_execution']['movement']
    display, screen = reporting.render(candidate['report'], world, before['war_state'], turn=after['turn_count'])
    assert not screen['issues'], screen['issues']
    committed_screen = trace['guards']['report']
    assert committed_screen['status'] == 'screened', committed_screen['issues']
    stable = copy.deepcopy(after)
    by_name = {}
    offset = 0
    while True:
        view = afsim_state.observation(after, dict(limit=16, offset=offset, detail=True))
        by_name.update({u['name']: u for u in view['units']})
        offset = view['next_offset']
        if offset is None:
            break
    assert len(by_name) == 22
    for _, unit in missions.units(world):
        assert by_name[unit['name']]['personnel_strength_pct'] == personnel_projection.strength_pct(unit)
        assert f'人员保有率{personnel_projection.strength_pct(unit):g}%' in display
    assert after == stable, 'Readonly projection mutated accepted session'
    result.update(preview_proof=proof, settlement_version=summary['version'],
                  preview_listed_units=len(summary['units']), preview_total_units=summary['total_units'],
                  preview_unlisted_units=summary['unlisted_units'], all22_observed=True,
                  current_report_screen=screen['status'], readonly_world_unchanged=True,
                  committed_report_screen=committed_screen['status'],
                  actual_movement_rechecked=True,
                  scope=f'Real full22 branch T{after["turn_count"]} public tool proof, accounts, motion and readonly personnel views; '
                        'preview still lists16/22, not complete narrative, backend equivalence or history acceptance')
    save(directory / 'audit.json', result)
    print(f'PASS actual full22 T{after["turn_count"]} v3 preview/report proof, accounts, motion and personnel projection')


if __name__ == '__main__':
    main()
