"""Continue the catalog's explicitly estimated local battle; no Python turns."""
import argparse
import copy
import json
from pathlib import Path

from tools.qa.catalog_expansion_live import call, fire_orders, revision, advance


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--live', action='store_true')
    if not p.parse_args().live:
        p.error('Use --live against owned API18998 and the catalog QA allowlist')
    root = Path('.cache/qa/catalog-expansion/sustained'); root.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(Path('.cache/qa/catalog-expansion/live/result.json').read_text())
    assert manifest['passed']
    sid = next(r['session_id'] for r in manifest['profiles'] if r['id'] == 'AJ10-changsha3')
    path = '/api/sessions/' + sid
    health = call('GET', '/api/health')
    assert not health['build']['restart_required']
    argv = Path(f"/proc/{health['build']['pid']}/cmdline").read_bytes().split(b'\0')
    assert argv[1] == b'.cache/qa/ww2-phases/launch.py'
    result = {'passed': False, 'session_id': sid, 'scope': 'explicit QA ground inputs, not historical casualties', 'turns': []}
    def save(name, value):
        (root / (name + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    try:
        initial = call('GET', path)
        frozen = copy.deepcopy(initial['war_state']['historical_initial'])
        assert initial['turn_count'] >= 1
        for turn in range(2, 9):
            current = call('GET', path)
            if current['turn_count'] >= turn:
                continue
            assert current['turn_count'] == turn - 1
            view = call('GET', path + '/commands')
            call('PUT', path + '/commands', {**revision(view), 'orders': fire_orders(view),
                'control_team': 'red', 'director': True, 'no_fire': False, 'unit_agents': [],
                'intent': 'QA双方持续交火，维持原始估计和补给约束，不能填充历史伤亡配额。'})
            before = current['war_state']
            following = advance(sid, '按已确认的双方fire命令继续。弹药、通信与压制按原生结果约束；不续发无限弹药，不按历史总数扣人。')
            save('turn' + str(turn), following)
            after = following['war_state']
            assert following['turn_count'] == turn
            assert after['historical_initial'] == frozen
            assert after['simulation_clock']['elapsed_seconds'] == 1800 * turn
            previous = {u['name']: u for t in ('red', 'blue') for u in before[t + '_units']}
            rows = []
            for team in ('red', 'blue'):
                for u in after[team + '_units']:
                    personnel = u['personnel']; old = previous[u['name']]['personnel']
                    assert personnel['committed'] == sum(personnel[k] for k in ('current', 'casualties', 'noncombat_losses'))
                    assert personnel['casualties'] >= old['casualties']
                    assert all(n >= 0 for n in u['logistics'].values() if isinstance(n, (int, float)))
                    last = u['formation']['last_execution']
                    rows.append({'name':u['name'], 'team':team, 'current':personnel['current'],
                        'casualties':personnel['casualties'], 'killed':personnel.get('killed'),
                        'ammo':u['logistics']['ammo'], 'fire_cycles':last.get('fire_cycles'),
                        'active_fire_s':last.get('active_fire_s'), 'fire_stop_reason':last.get('fire_stop_reason')})
            result['turns'].append({'turn':turn,'time':after['current_time'],'units':rows})
            save('result', result)
            print('PASS T'+str(turn), after['current_time'], [(r['current'],r['casualties'],r['ammo'],r['fire_cycles']) for r in rows], flush=True)
        end = call('GET', path)
        assert end['war_state']['simulation_clock']['elapsed_seconds'] == 14400
        assert end['war_state']['mission']['status'] == 'completed'
        assert all(sum(u['personnel']['casualties'] for u in end['war_state'][team + '_units']) > 5 for team in ('red','blue'))
        main = copy.deepcopy(end['war_state'])
        view = call('GET', path + '/commands')
        red = next(u for u in view['units'] if u['team'] == 'red')
        counterfactual = call('POST', path + '/commands/compare', {**revision(view), 'turn':1,
            'orders':[{'unit_id':red['id'],'action':'hold','duration':'next'}]})
        save('counterfactual', counterfactual)
        alternative = counterfactual['alternative']
        assert sum(u['personnel']['casualties'] for u in alternative['blue_units']) == 0
        assert call('GET',path)['war_state'] == main
        result.update(passed=True, counterfactual_main_unchanged=True,
            elapsed_seconds=14400, historical_calibration_passed=False,
            assessment=end['war_state'].get('combat_assessment'))
        save('result', result)
    except Exception as exc:
        result['error'] = str(exc);save('result', result);raise


if __name__ == '__main__':
    main()
