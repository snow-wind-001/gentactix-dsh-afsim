"""Normal confirmed hold commands aboard actual native/model transport worlds."""
import argparse
import copy
import json
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--live', action='store_true')
parser.add_argument('--engine', choices=('afsim', 'narrative'), required=True)
args = parser.parse_args()
if not args.live:
    parser.error('Owned isolated API18998 and actual execution require --live')
root = Path('.cache/qa/ferry-model')
sid = json.loads((root / 'session-ids.json').read_text())[args.engine]
base = 'http://127.0.0.1:18998/api/sessions/' + sid


def call(method, path='', value=None):
    request = urllib.request.Request(base + path, method=method, headers={'Content-Type': 'application/json'},
        data=None if value is None else json.dumps(value, ensure_ascii=False).encode())
    try:
        with urllib.request.urlopen(request, timeout=1200) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(str(error.code) + ': ' + error.read().decode()[:2500]) from error


def save(name, value):
    (root / (args.engine + '-' + name + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


checks = []
for turn in range(2, 7 if args.engine == 'afsim' else 4):
    current = call('GET')
    assert current['turn_count'] >= 1, 'Start from the actual committed first voyage'
    if current['turn_count'] < turn:
        assert current['turn_count'] == turn - 1
        before = copy.deepcopy(current['war_state'])
        view = call('GET', '/commands')
        revision = {'expected_turn': view['turn'], 'revision': view['revision'], 'world_version': view['world_version']}
        call('PUT', '/commands', {**revision,
            'orders': [{'unit_id': u['id'], 'action': 'hold', 'duration': 'next'} for u in view['units']],
            'control_team': 'red', 'director': True, 'no_fire': True, 'unit_agents': [],
            'intent': 'QA已登船后的地面待命，舟艇仍正常到岸卸载及空艇返回；不改变史实来源。'})
        view = call('GET', '/commands')
        revision = {'expected_turn': view['turn'], 'revision': view['revision'], 'world_version': view['world_version']}
        print('TURN', args.engine, turn, 'all hold aboard', flush=True)
        start = time.monotonic()
        current = call('POST', '/next', {**revision, 'batch_id': uuid.uuid4().hex,
            'instruction': '全部单位执行已确认hold；已登船分队仍随艇按冻结speed_mps航行，抵达出口后卸载再空艇返航。'
            '仅取消地面推进不会使载客船瞬停、取消已完成登船、退还容量或提前登陆；未登船主队留在原岸。'
            '船速.5m/s、装卸各10秒，连续使用上轮实际船位。单位crossing保持既有served_work，last_work=0，'
            '只有实际抵岸并卸载才completed与exited；舟艇landed才trips加1，未发生阶段转换时events为空。'
            'remaining_s只计装卸等待，航行和返航为0。crossing_receipt used_work=0,cargo_work=0,budget_work=250。'
            'DSH独立时按当前数值自行估计并提交完整combined_arms.bridge.ferry_state和crossing_receipt，不冒称原生。'
            '本轮均hold，food覆盖各下降2，food_spent=2乘初始人员scale；delivery、ammo_spent及分类received/spent为0。'
            '无交火、增援、船员或仓库货运，人员装备守恒；未知史实仍未知，战报只写本轮。'})
        save('continue-turn' + str(turn), current)
        save('continue-timing' + str(turn), {'elapsed_s': time.monotonic() - start})
        assert current['war_state']['historical_initial'] == before['historical_initial']
    if current['turn_count'] != turn:
        continue  # Existing later committed rounds are not replaced/replayed.
    world = current['war_state']
    boat = world['combined_arms']['bridge']['ferry_state']['boats'][0]
    part = next(u for u in world['red_units'] if u.get('formation_part', {}).get('part_id') == 'advance')
    main = next(u for u in world['red_units'] if u.get('formation_part', {}).get('part_id') == 'main')
    assert sum(u['personnel']['current'] for u in world['red_units']) == 4600
    assert main['lat'] == 27.3138 and main['lng'] == 107.402
    assert world['current_time'] == f'1935-01-03 12:0{turn}'
    assert not world['engagements'] and all(u['personnel']['casualties'] == 0 for team in ('red','blue') for u in world[team+'_units'])
    if turn == 2:
        assert boat['phase'] == 'outbound' and boat['trips'] == 0
        assert abs(part['lat'] - boat['lat']) < .00001
        view = call('GET', '/unit-decisions')
        receipt = next(r for r in view['items'] if r['turn'] == turn and r['unit_name'] == part['name'])
        assert receipt['action'] == 'hold' and '随艇' in receipt['reason']
    if turn == 3:
        assert boat['phase'] == 'returning' and boat['passenger'] is None and boat['trips'] == 1
        assert abs(part['lat'] - 27.3151) < .00001 and part['crossing']['status'] == 'completed'
        assert any(e['phase'] == 'landed' for e in world['combined_arms']['bridge']['ferry_state']['events'])
    if turn >= 5:
        assert boat['phase'] == 'idle' and abs(boat['lat'] - 27.3145) < .00001 and boat['trips'] == 1
        assert abs(part['lat'] - 27.3151) < .00001
    checks.append(f'T{turn}: actual transport, hold control, clock and parent ledger consistent')
    print('PASS', checks[-1], flush=True)
save('continue-results', {'passed': True, 'checks': checks,
    'scope': 'normal API explicit QA estimates; not historical battle calibration'})
