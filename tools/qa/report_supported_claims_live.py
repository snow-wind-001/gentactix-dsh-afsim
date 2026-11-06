"""Fresh isolated combat reports through normal APIs; no model fixtures."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import time

from gentactix import reporting
from tools.qa import operation_boundary_live as flow

ROOT = Path('.cache/qa/report-supported-claims-2026-11-02')


def save(path, value):
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def check_original_worlds():
    original = Path('.cache/qa/operation-boundary-2026-11-02')
    rows = []
    for path in (original/'frontend-post-turn.json', original/'narrative/turn-12.json'):
        old = json.loads(path.read_text())
        current = flow.call('GET', '/sessions/'+old['session_id'])
        assert current['war_state'] == old['war_state']
        rows.append(dict(session_id=old['session_id'], turn=current['turn_count'], world_unchanged=True))
    save('original-qa-worlds.json', rows)


def run(engine):
    flow.ROOT = ROOT
    case = flow.create(engine)
    initial = copy.deepcopy(case['initial']['war_state'])
    base = '/sessions/'+case['session_id']
    flow.orders(case, combat=True)
    result = dict(passed=False, engine=engine, session_id=case['session_id'], actual_api=True,
                  actual_model=engine == 'narrative', historical_calibration=False)
    started = time.monotonic()
    try:
        print('Executing fresh actual combat:', engine, case['session_id'], flush=True)
        after = flow.advance(case, 'new report guard')
        trace = flow.call('GET', base+'/traces/1')['record']
        save(engine+'/trace.json', trace)
        world = after['war_state']
        saved = copy.deepcopy(world)
        shooters = [u for team in ('red', 'blue') for u in world[team+'_units']
                    if u['name'] in ('第159师', '日军第106师团')]
        assert after['turn_count'] == 1 and world['simulation_clock']['elapsed_seconds'] == 21600
        assert len(shooters) == 2 and all(u['logistics']['ammo'] == 0 for u in shooters)
        assert all(u['personnel']['casualties'] > 0 for u in shooters)
        assert len(world['red_units'])+len(world['blue_units']) == 6
        public = after['history'][0]
        assert '随队库存（模型工作量）' in public and '弹药0' in public
        audit = trace['guards']['report']
        named = '第159师与日军第106师团的随队弹药工作量耗尽。'
        assert not reporting.inspect(named, world, initial, turn=1)
        assert reporting.inspect('全军弹药耗尽。', world, initial, turn=1)
        if engine == 'narrative':
            assert world['dsh_execution']['fire_ledger']['source'] == 'dsh_model_estimate'
            assert 'DSH过程估计，非AFSIM遥测' in public and '末发' in public
        else:
            assert after['afsim']['model_skipped'] and after['afsim']['returncode'] == 0
            assert 'DSH过程估计，非AFSIM遥测' not in public
        assert world == saved
        check_original_worlds()
        # Counterexample checks are read-only; never replace a saved live report.
        result.update(passed=True, seconds=round(time.monotonic()-started, 3),
                      issue_codes=[r['code'] for r in audit['issues']], report_status=audit['status'],
                      world_hash=digest(world), report_hash=digest(public),
                      shooters=[dict(name=u['name'], stock=u['logistics'], personnel=u['personnel']) for u in shooters],
                      full_prose_semantically_verified=False, original_worlds_unchanged=True)
    finally:
        save(engine+'/result.json', result)
    print('PASS', engine, 'actual combat/report, 6 units; report audit:', result['issue_codes'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('engine', choices=['afsim', 'narrative'])
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--name', default='', help='Fresh named evidence folder; preserve earlier actual runs')
    args = parser.parse_args()
    if not args.live:
        parser.error('Use --live for actual backend/model calls')
    if args.name:
        if not args.name.replace('-', '').isalnum():
            parser.error('Name must contain letters, numbers or hyphens')
        ROOT = ROOT / args.name
    run(args.engine)
