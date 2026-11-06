"""Normal DSH skill build, native execution, and DSH-only part-account checks."""
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
args = parser.parse_args()
if not args.live:
    parser.error('Owned isolated API18998 and actual model access require --live')
root = Path('.cache/qa/formation-partitions')
base = 'http://127.0.0.1:18998'
battle = '红军长征-强渡乌江-1935.01.01至1935.01.06'
checks = []


def save(name, value):
    (root / (name + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def call(method, path, value=None):
    request = urllib.request.Request(base + path, method=method, headers={'Content-Type': 'application/json'},
        data=None if value is None else json.dumps(value, ensure_ascii=False).encode())
    try:
        with urllib.request.urlopen(request, timeout=1200) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(str(error.code) + ': ' + error.read().decode()[:2500]) from error


def check(ok, label):
    if not ok:
        raise AssertionError(label)
    checks.append(label)
    save('live-checks', checks)
    print('PASS', label, flush=True)


health = call('GET', '/api/health')
check(not health['build']['restart_required'], 'current API source')
for row in json.loads(Path('.cache/qa/crossing-control/before-final-cold-restart.json').read_text()):
    check(call('GET', '/api/sessions/' + row['session_id'])['war_state'] == row['world'], 'old world restored ' + row['session_id'])

if (root / 'historical-draft.json').exists():
    draft = json.loads((root / 'historical-draft.json').read_text())
else:
    instruction = json.loads(Path('.cache/qa/river-crossing/build-request.json').read_text())['instruction']
    instruction += ('\n另外必须实际通过原生update_scenario_configuration在公共条件配置可选partitions。'
        '这是软件QA分队估计，不是军委纵队历史上曾有5人先遣队。其余所有原要求保持。'
        'partitions.version=formation-partitions-1，groups只含已有父ID lm.red.cmc_column。'
        '该组assumption明确互斥QA计算划分。parts两项：id=main、label=主队、1595人、position27.3138,107.402、'
        'equipment仅transport4其余0，resources五类全0、dispersion_km2=2；'
        'id=advance、label=分遣组、5人、position27.3158,107.402、equipment五类全0、resources五类全0、dispersion_km2=.01。'
        '每项assumption说明不是历史人数/部署。不得增加新的actors键，不把军委纵队再当第三份兵力；'
        '父actor仍1600人和transport4。其余4个父单位不划分。'
        '输入为5个父单位、执行应6个叶单位，参数校验和实际装载AFSIM；总投入红方仍4600人。')
    operation = uuid.uuid4().hex
    save('build-request', {'operation_id': operation, 'instruction': instruction})
    print('BUILD actual DSH historical-units skill with disjoint parts', flush=True)
    draft = call('POST', '/api/historical-scenarios/build', {'battle': battle, 'phase_id': 'follow_on_jan3',
        'instruction': instruction, 'time_step': '30分钟', 'execution_backend': 'afsim', 'operation_id': operation})
    save('historical-draft', draft)
check(draft['validation']['scope'] == 'native_load', 'DSH-built partition configuration actually loaded by AFSIM')
check(len(draft['preview_world']['red_units']) == 3, 'two disjoint CMC parts plus the other red formation; no extra parent')
check(sum(u['personnel']['current'] for u in draft['preview_world']['red_units']) == 4600, 'no duplicated parent personnel')
tool_names = {e.get('name') for run in draft['construction']['runs'] for e in run.get('events', []) if e.get('type') == 'tool/call'}
check({'read_scenario_skill', 'get_scenario_basis', 'update_scenario_configuration'} <= tool_names, 'native DSH skill and staged draft tools used')
identities = json.loads((root / 'session-ids.json').read_text()) if (root / 'session-ids.json').exists() else {}
for engine in ('afsim', 'narrative'):
    if engine not in identities:
        selected = draft
        if engine == 'narrative':
            operation = uuid.uuid4().hex
            save('narrative-validation-request', {'operation_id': operation})
            selected = call('POST', '/api/historical-scenarios/validate', {'parameters': draft['parameters'],
                'parent_draft_id': draft['id'], 'execution_backend': engine, 'operation_id': operation})
            save('narrative-draft', selected)
        created = call('POST', '/api/sessions', {'scenario': '分岸计算分队QA-' + engine, 'battle': battle,
            'product_mode': 'historical', 'execution_backend': engine, 'persist_roles': False, 'use_rag': True,
            'historical_parameters': selected['parameters'], 'scenario_draft_id': selected['id']})
        identities[engine] = created['session_id']
        save('session-ids', identities)
    sid = identities[engine]
    path = '/api/sessions/' + sid
    state = call('GET', path)
    if not state.get('war_state'):
        state = call('POST', path + '/init')
    if not (root / (engine + '-initial.json')).exists():
        save(engine + '-initial', state)
    before = copy.deepcopy(state['war_state'])
    if state['turn_count'] == 0:
        view = call('GET', path + '/commands')
        revision = {'expected_turn': view['turn'], 'revision': view['revision'], 'world_version': view['world_version']}
        orders = [{'unit_id': u['id'], 'action': 'move' if engine == 'afsim' and '分遣组' in u['name'] else 'hold', 'duration': 'next',
                   **({'destination': {'lat': 27.3165, 'lng': 107.402}} if engine == 'afsim' and '分遣组' in u['name'] else {})}
                  for u in view['units']]
        call('PUT', path + '/commands', {**revision, 'orders': orders, 'control_team': 'red', 'director': True,
            'no_fire': True, 'intent': '只执行已确认命令，无补给或交火，不改写历史事实。', 'unit_agents': []})
        view = call('GET', path + '/commands')
        revision = {'expected_turn': view['turn'], 'revision': view['revision'], 'world_version': view['world_version']}
        start = time.monotonic()
        print('TURN', engine, 'actual execution', flush=True)
        state = call('POST', path + '/next', {**revision, 'batch_id': uuid.uuid4().hex,
            'instruction': '按确认队列执行。全局禁止开火，无库存无补给，不减员。AFSIM关闭时：所有6个计算叶单位待命，粮弹值仍是0–100覆盖，'
            'food_after=food_before-2。注意军委主队scale1595/1600，其resource_ledger.food_spent=1.99375；'
            '5人分遣组scale5/1600，其food_spent=.00625；其余未划分单位food_spent=2。delivery和ammo_spent均0。'
            '这些账目由DSH输出，宿主不补写。保留formation_groups与身份，不提交原生余量或伪造AFSIM执行。'})
        save(engine + '-timing', {'elapsed_s': time.monotonic() - start})
        save(engine + '-turn1', state)
    w = state['war_state']
    initial = json.loads((root / (engine + '-initial.json')).read_text())['war_state']
    parts = [u for u in w['red_units'] if u.get('formation_part')]
    check(len(parts) == 2 and sum(u['personnel']['current'] for u in parts) == 1600, engine + ' disjoint personnel remain conserved')
    check(w['historical_initial'] == initial['historical_initial'], engine + ' historical facts unchanged')
    names = {u['name'] for u in parts}
    expected = 2 + (2 * 5 / 1600 if engine == 'afsim' else 0)
    check(abs(sum(r['food_spent'] for r in w['mission']['ledger'] if r['unit'] in names) - expected) < 1e-8,
          engine + ' parent-equivalent food debit without duplicate rations')
    check(not w['engagements'] and all(u['personnel']['casualties'] == 0 for team in ('red','blue') for u in w[team + '_units']), engine + ' no invented combat')
    check(parts[0]['lat'] < 27.3148 < parts[1]['lat'], engine + ' separate bank positions retained')
save('live-result', {'passed': True, 'session_ids': identities, 'checks': checks,
                     'scope': 'explicit QA partition estimates; not an early Wujiang raft-assault reconstruction'})
