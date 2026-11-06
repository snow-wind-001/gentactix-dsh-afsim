"""Opt-in catalog import/execution check with explicit, nonhistorical QA inputs.

Uses the ordinary API and actual native DSH/AFSIM integration. No response mocks,
state repairs, or Python combat executor. This is not historical calibration.
"""
import argparse
import copy
import json
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

IDS = ('AJ01-shanghai', 'AJ02-taiyuan', 'AJ08-changsha1', 'AJ09-changsha2',
       'AJ10-changsha3', 'AJ11-kunlun', 'AJ12-ichigo', 'AJ13-hengyang',
       'AJ14-hundred', 'AJ16-counter1944', 'AJ17-cheqiao', 'AJ19-burma', 'AJ20-reception')
NOTE = ('QA输入：人数、投入比例、两列相距约220米的部署、装备、时钟、库存和规则为显式计算假设，'
        '不代表历史实到量、真实射界、史实交战时长或已标定战损。')
OUT = Path('.cache/qa/catalog-expansion/live')
BASE = 'http://127.0.0.1:18998'


def call(method, path, value=None):
    req = urllib.request.Request(BASE + path, method=method,
        data=None if value is None else json.dumps(value, ensure_ascii=False).encode(),
        headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=1200) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'{path}: HTTP{exc.code}: ' + exc.read().decode()[:2500]) from exc


def save(name, value):
    (OUT / (name + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def parameters(basis):
    from tools.qa.historical_operational_fixture import inputs
    from gentactix import historical_operations
    p = copy.deepcopy(basis['configuration_template'])
    _, sample = inputs()
    center = basis['geographic_scope']['center']
    definition = basis['initial']['definition']
    index = {u['id']: u for u in definition['units']}
    offsets = {'red': 0, 'blue': 0}
    for identity in p['actors']:
        u = index[identity]
        team = u['team']
        sign = -1 if team == 'red' else 1
        actor = copy.deepcopy(next(iter(sample['actors'].values())))
        actor.update(personnel=2000 if team == 'red' else 1800,
            position={'lat': center['lat'] + sign * .001, 'lng': center['lng'] + offsets[team] * .0006},
            attack_range_m=800, assumption=NOTE)
        actor['equipment'].update(armor=0, artillery=0, engineer=0, transport=8)
        actor['formation'].update(motorized=False, shells=120, materials=0, fuel_liters=1000)
        if u['role'] == 'support':
            actor.update(personnel=120, type='炮兵', attack_range_m=800)
            # Keep artillery beyond its declared 300 m minimum indirect range.
            actor['position']['lat'] = center['lat'] + sign * .006
            actor['equipment']['artillery'] = 4
            actor['formation']['role'] = 'support'
        offsets[team] += 1
        p['actors'][identity] = actor
    p['clock'].update(start=basis['execution_window']['start'], time_step='30分钟', assumption=NOTE)
    p['area'].update(center=copy.deepcopy(center), radius_km=5, terrain_factor=1, assumption=NOTE)
    p['rules'].update(required_survivors=1, convoy_km_per_turn=10, motorized=False)
    p['support'] = copy.deepcopy(sample['support'])
    for team, sign in (('red', -1), ('blue', 1)):
        p['support'][team].update(position={'lat': center['lat'] + sign * .02, 'lng': center['lng']}, assumption=NOTE)
    p['facility'].update(**center)
    p['goal'].update(objective=copy.deepcopy(center), exit={'lat': center['lat'] - .04, 'lng': center['lng']},
        radius_km=.05, deadline_turn=8, required_turns=1, required_survivors=1,
        description='QA局部任务；验证导入和命令效果，不代表全战役胜负。', assumption=NOTE)
    p['assumptions'] = NOTE
    historical_operations.initial(basis['initial'], p)  # Validate; never advance.
    return p


def revision(view):
    return {'expected_turn': view['turn'], 'revision': view['revision'], 'world_version': view['world_version']}


def advance(sid, instruction):
    view = call('GET', f'/api/sessions/{sid}/commands')
    return call('POST', f'/api/sessions/{sid}/next', {**revision(view), 'batch_id': uuid.uuid4().hex,
        'instruction': instruction})


def fire_orders(view):
    targets = {t: next(u for u in view['units'] if u['team'] != t) for t in ('red', 'blue')}
    return [{'unit_id': u['id'], 'action': 'bombard' if '炮兵' in u['name'] else 'fire',
             'target_id': targets[u['team']]['id'], 'duration': 'next'}
            for u in view['units']]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--automatic', action='store_true', help='Also use actual DSH planning and read-only native observation')
    parser.add_argument('--resume', action='store_true', help='Keep completed sessions; rerun only missing or revised source versions')
    args = parser.parse_args()
    if not args.live:
        parser.error('Use --live against the owned isolated API18998')
    OUT.mkdir(parents=True, exist_ok=True)
    health = call('GET', '/api/health')
    assert not health['build']['restart_required']
    argv = Path(f"/proc/{health['build']['pid']}/cmdline").read_bytes().split(b'\0')
    assert argv[1] == b'.cache/qa/ww2-phases/launch.py', 'Only the owned isolated API'
    result = json.loads((OUT / 'result.json').read_text()) if args.resume else {'scope': NOTE, 'profiles': []}
    result['passed'] = False
    result.pop('error', None)
    try:
        from gentactix import historical_initial
        catalog = {r['profile_id']: r['battle'] for r in historical_initial.catalog() if r['status'] == 'profiled'}
        for identity in IDS:
            battle = catalog[identity]
            print('START', identity, flush=True)
            basis = call('GET', '/api/historical-scenarios/basis?battle=' + urllib.parse.quote(battle))
            assert basis['ready'], basis['error']
            previous = next((r for r in result['profiles'] if r['id'] == identity), None)
            if previous:
                old = call('GET', '/api/sessions/' + previous['session_id'])['war_state']['historical_initial']
                if old['definition'] == basis['initial']['definition']:
                    print('KEEP', identity, previous['session_id'], flush=True)
                    continue
                result.setdefault('superseded_attempts', []).append(previous)
                result['profiles'].remove(previous)
            p = parameters(basis)
            save(identity + '-parameters', p)
            created = call('POST', '/api/sessions', {'scenario': '目录局部导入QA：' + NOTE,
                'battle': battle, 'historical_parameters': p, 'product_mode': 'historical',
                'simulation_mode': 'open', 'execution_backend': 'afsim', 'persist_roles': False})
            sid = created['session_id']
            first = call('POST', f'/api/sessions/{sid}/init')
            save(identity + '-initial', first)
            world = first['war_state']
            assert world['afsim']['entity_count'] == len(p['actors'])
            assert {u['historical_unit_id'] for t in ('red', 'blue') for u in world[t + '_units']} == set(p['actors'])
            view = call('GET', f'/api/sessions/{sid}/commands')
            call('PUT', f'/api/sessions/{sid}/commands', {**revision(view),
                'orders': fire_orders(view), 'control_team': 'red', 'director': True,
                'no_fire': False, 'unit_agents': [], 'intent': NOTE})
            started = time.monotonic()
            after = advance(sid, '双方按已确认命令交火；只由AFSIM原生计算，不填充历史必达损失。')
            save(identity + '-turn1', after)
            current = after['war_state']
            assert current['historical_initial'] == world['historical_initial']
            units = [u for t in ('red', 'blue') for u in current[t + '_units']]
            assert all(u['personnel']['committed'] == sum(u['personnel'][k] for k in ('current', 'casualties', 'noncombat_losses')) for u in units)
            losses = {t: sum(u['personnel']['casualties'] for u in current[t + '_units']) for t in ('red', 'blue')}
            assert all(n > 0 for n in losses.values()), losses
            assert current['engagements'] and current['afsim']['model_skipped']
            result['profiles'].append({'id': identity, 'session_id': sid, 'phase': p['phase_id'],
                'entities': len(p['actors']), 'losses': losses, 'seconds': round(time.monotonic() - started, 3)})
            save('result', result)
            print('PASS', identity, sid, losses, flush=True)
        if args.automatic:
            sid = next(r['session_id'] for r in result['profiles'] if r['id'] == 'AJ01-shanghai')
            before = call('GET', f'/api/sessions/{sid}')['war_state']
            view = call('GET', f'/api/sessions/{sid}/commands')
            call('PUT', f'/api/sessions/{sid}/commands', {**revision(view), 'orders': [],
                'control_team': 'red', 'director': False, 'no_fire': False, 'unit_agents': [],
                'intent': '实际DSH为双方全部已绑定历史单位独立规划；不改变来源或计算参数。'})
            print('START actual DSH two-sided planner', sid, flush=True)
            following = advance(sid, '开放推演QA：双方各自决策，当前都在有效射程，应继续交火；必须覆盖双方全部单位。'
                '只提交命令，不写伤亡或挪动源事实；海军陆战队是地面编组，不是舰艇。')
            save('actual-dsh-turn', following)
            w = following['war_state']
            assert not w['afsim']['model_skipped']
            assert len(w['afsim']['orders']) == len(before['red_units'] + before['blue_units'])
            assert w['historical_initial'] == before['historical_initial']
            unchanged = copy.deepcopy(w)
            print('START actual DSH read-only observer', sid, flush=True)
            answer = call('POST', f'/api/sessions/{sid}/chat', {'message':
                '只读复核，请实际调用get_afsim_observation和get_afsim_changes。列出本轮双方单位行动、人员当前/累计伤亡、'
                '交火记录和补给变化；说明哪些是原生计算，哪些是QA估计，哪些缺史料，不要称作完整淞沪复现。不得下命令或修改主局。'})
            save('actual-dsh-review', answer)
            assert answer['engine_meta']['finish_reason'] == 'completed'
            assert answer['war_state'] == unchanged == call('GET', f'/api/sessions/{sid}')['war_state']
            result['actual_dsh_session'] = sid
        result['passed'] = True
        save('result', result)
    except Exception as exc:
        result['error'] = str(exc)
        save('result', result)
        raise


if __name__ == '__main__':
    main()
