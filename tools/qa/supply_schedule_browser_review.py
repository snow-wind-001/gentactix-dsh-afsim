"""Read-only review of retained actual frontend timed-supply responses."""
import json
from pathlib import Path


def main():
    from gentactix import missions, sim_clock, supply_schedule
    root = Path('.cache/qa/supply-schedule-2026-11-01')
    data = json.loads((root / 'browser-responses.json').read_text())
    response = data['next']
    assert response['status'] == 'finished' and response['http'] == 200
    # A browser JSON round-trip erases the distinction between 8 and 8.0.
    # Use the canonical durable checkpoint for definition fingerprints and
    # independently compare its numerical content with the UI responses.
    saved = json.loads((root / 'browser' / 'sessions' / (data['initial']['session_id'] + '.json')).read_text())['session']
    prior, final = saved['last_war_state'], saved['war_state']
    assert prior == data['initial']['war_state']
    assert final == response['body']['war_state']
    missions.validate(prior)
    missions.validate(final)
    assert data['initial']['turn_count'] == 0 and response['body']['turn_count'] == 1
    assert sim_clock.duration_seconds(data['initial']['time_step']) == 21600
    assert final['simulation_clock']['elapsed_seconds'] == 21600
    assert final['afsim']['effects_source'] == 'afsim-native-teaching-1'
    assert final['afsim']['model_skipped'] is True
    assert final['mission']['definition']['supply_schedule']['period_seconds'] == 1800
    receipt = final['supply_schedule']['ledger']
    summary = supply_schedule.validate_ledger(prior, receipt, final['afsim']['orders'], 21600)
    assert len(receipt['units']) == 3
    for row in receipt['units']:
        assert len(row['events']) == 13
        assert [e['seconds'] for e in row['events'] if e['kind'] == 'delivery'] == list(range(1800, 21601, 1800))
    old = {u['historical_unit_id']: u for _, u in missions.units(prior)}
    assert set(old) == {u['historical_unit_id'] for _, u in missions.units(final)}
    for _, unit in missions.units(final):
        previous = old[unit['historical_unit_id']]
        for key in ('committed', 'current', 'casualties', 'noncombat_losses'):
            assert unit['personnel'][key] == previous['personnel'][key]
        old_equipment = {e['category']: e for e in previous['equipment']}
        assert set(old_equipment) == {e['category'] for e in unit['equipment']}
        for equipment in unit['equipment']:
            for key in ('committed', 'operational', 'damaged', 'destroyed'):
                assert equipment[key] == old_equipment[equipment['category']][key]
        row = summary[unit['name']]
        assert abs(unit['logistics']['food'] - row['food_after']) < 1e-6
        assert abs(unit['logistics']['ammo'] - row['ammo_after']) < 1e-6
    construction = data['validated']['construction']
    result = {'passed': True, 'actual_model_generation': construction['source'] == 'dsh_native_skill',
              'generation_stages': len(construction['stages']), 'generation_updates': len(construction['draft_updates']),
              'actual_frontend_advance': True, 'actual_afsim': True, 'units': 3, 'elapsed_seconds': 21600,
              'receipt_events': 39, 'typed_period_seconds': 1800,
              'personnel_equipment_unchanged_for_hold': True,
              'scope': 'Three historical identities with generated estimates manually edited and revalidated; bilateral holds were queued through the API, advance clicked through actual UI. Not historical calibration or autonomous decisions.'}
    (root / 'browser-turn-review.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
