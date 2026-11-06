"""Opt-in real API / real DSH command lifecycle on sourced Wujiang identities.

Uses the previously DSH-built, natively loaded draft, revalidates slower QA
capacity through the normal API, and never edits existing worlds or source facts.
"""
import argparse, copy, json, time, urllib.request, urllib.error, uuid
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--live', action='store_true')
p.add_argument('--engine', choices=['afsim', 'narrative'], required=True)
p.add_argument('--prepare-only', action='store_true')
p.add_argument('--continuation-turn', type=int, default=2, choices=range(2, 9))
a = p.parse_args()
if not a.live:
    p.error('Real isolated API and model access require --live')
root = Path('.cache/qa/crossing-control')
base = 'http://127.0.0.1:18998'

def save(name, value):
    (root / (a.engine + '-' + name + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

def call(method, path, value=None):
    req = urllib.request.Request(base + path, method=method, headers={'Content-Type': 'application/json'}, data=None if value is None else json.dumps(value, ensure_ascii=False).encode())
    try:
        with urllib.request.urlopen(req, timeout=1200) as f:
            return json.load(f)
    except urllib.error.HTTPError as e:
        raise RuntimeError(str(e.code) + ': ' + e.read().decode()[:3000])

def state():
    return call('GET', f'/api/sessions/{sid}')

def view():
    v = call('GET', f'/api/sessions/{sid}/commands')
    return (v, {k: v[k] for k in ('revision', 'world_version')} | {'expected_turn': v['turn']})

def check(ok, label):
    if not ok:
        raise AssertionError(label)
    checks.append(label)
    save('checks', checks)
    print('PASS', a.engine, label, flush=True)
checks = []
health = call('GET', '/api/health')
check(not health['build']['restart_required'], 'current API source')
idsfile = root / (a.engine + '-session.json')
if idsfile.exists():
    sid = json.loads(idsfile.read_text())['session_id']
else:
    draft = json.loads(Path('.cache/qa/river-crossing/historical-draft.json').read_text())
    params = copy.deepcopy(draft['parameters'])
    params['facility']['crossing_model']['throughput_work_per_hour'] = 1000
    params['goal']['deadline_turn'] = 10
    op = uuid.uuid4().hex
    save('validation-request', {'operation_id': op})
    selected = call('POST', '/api/historical-scenarios/validate', {'parameters': params, 'parent_draft_id': draft['id'], 'execution_backend': a.engine, 'operation_id': op})
    save('draft', selected)
    result = call('POST', '/api/sessions', {'scenario': '乌江渡运指挥生命周期QA-' + a.engine, 'battle': '红军长征-强渡乌江-1935.01.01至1935.01.06', 'product_mode': 'historical', 'execution_backend': a.engine, 'use_rag': True, 'persist_roles': False, 'historical_parameters': selected['parameters'], 'scenario_draft_id': selected['id']})
    sid = result['session_id']
    save('session', result)
current = state()
if not current.get('war_state'):
    current = call('POST', f'/api/sessions/{sid}/init')
if not (root / (a.engine + '-initial.json')).exists():
    save('initial', current)
initial = json.loads((root / (a.engine + '-initial.json')).read_text())
v, _ = view()
actor = next((u for u in v['units'] if u['team'] == 'red' and '军委' in u['name']))

def queue(reissue=False):
    v, revision = view()
    orders = []
    for u in v['units']:
        old = next((o for o in v['orders'] if o['unit_id'] == u['id']), None)
        order = {'unit_id': u['id'], 'action': 'move' if u['id'] == actor['id'] else 'hold', 'duration': 'until_arrived' if u['id'] == actor['id'] else 'next'}
        if u['id'] == actor['id']:
            order['destination'] = {'lat': 27.3158, 'lng': 107.402}
        if old and (not (reissue and u['id'] == actor['id'])):
            order['id'] = old['id']
        orders.append(order)
    return call('PUT', f'/api/sessions/{sid}/commands', {**revision, 'control_team': 'red', 'director': True, 'no_fire': True, 'orders': orders, 'unit_agents': []})
if current['turn_count'] == 0:
    queue()
continuation = a.continuation_turn
for turn in range(current['turn_count'] + 1, continuation + 3):
    if a.prepare_only and turn > 2:
        break
    if turn == continuation + 1:
        before = state()
        v, revision = view()
        old = next((o for o in v['orders'] if o['unit_id'] == actor['id']), None)
        if old:
            call('DELETE', f"/api/sessions/{sid}/commands/{old['id']}", revision)
        check(state()['war_state'] == before['war_state'], 'cancel queue does not rewrite physical world')
        v, revision = view()
        call('PUT', f'/api/sessions/{sid}/commands', {**revision, 'control_team': 'red', 'director': True, 'no_fire': True, 'unit_agents': [], 'orders': [{'unit_id': u['id'], 'action': 'hold', 'duration': 'next'} for u in v['units'] if u['id'] != actor['id']]})
    elif turn == continuation + 2:
        queue(reissue=True)
    elif 1 < turn <= continuation:
        queue()
    _, revision = view()
    instruction = '执行已确认命令，不自主改目标、开火或补给。所有未知历史数值保持来源快照不变。本局渡运吞吐为1000工作量/小时、每轮30分钟，容量500；还需扣除抵达入口和通道行军的有效时间。同一命令保留原任务served_work，last_work只能是本轮新增；未完成整建制服务留在入口。有cancelled_crossing_tasks且没有新移动命令时，显式提交status=cancelled、served_work原值、last_work=0、events=[]。重新下令后的任务身份由宿主确定，新任务从0服务，不能继承已撤销任务进度；不自行输出intent_id/cancel_crossing。AFSIM关闭时必须逐项更新双方收支：move耗粮4、hold耗粮2，无库存在delivery=0，不扣弹药，无战斗不减员。combined_arms.bridge.crossing_receipt的used_work为当轮所有任务last_work之和，cargo_work=0，budget_work=500；不把旧进度再次算入本轮。'
    save('turn' + str(turn) + '-request', {'revision': revision, 'instruction': instruction})
    print('RUN', a.engine, 'turn', turn, flush=True)
    start = time.monotonic()
    try:
        current = call('POST', f'/api/sessions/{sid}/next', {**revision, 'batch_id': uuid.uuid4().hex, 'instruction': instruction})
    except Exception as exc:
        save('turn' + str(turn) + '-error', {'error': str(exc), 'elapsed_s': time.monotonic() - start})
        raise
    save('turn' + str(turn), current)
    save('turn' + str(turn) + '-timing', {'elapsed_s': time.monotonic() - start})
    w = current['war_state']
    task = next((u for u in w['red_units'] if u['name'] == actor['name']))['crossing']
    check(w['historical_initial'] == initial['war_state']['historical_initial'], 'T' + str(turn) + ' source facts unchanged')
    check(not w['engagements'] and all((u['personnel']['casualties'] == 0 for t in ('red', 'blue') for u in w[t + '_units'])), 'T' + str(turn) + ' no fake combat losses')
    if turn <= continuation:
        check(task['status'] == 'queued' and 0 < task['last_work'] <= 500, 'T' + str(turn) + ' real service without teleporting')
        if turn > 1:
            prior = json.loads((root / (a.engine + '-turn'+str(turn-1)+'.json')).read_text())['war_state']['red_units'][0]['crossing']
            check(task['intent_id'] == prior['intent_id'] and abs(task['served_work'] - prior['served_work'] - task['last_work']) < 0.003, 'same confirmed intent carries work')
    elif turn == continuation + 1:
        prior = json.loads((root / (a.engine + '-turn'+str(turn-1)+'.json')).read_text())['war_state']['red_units'][0]['crossing']
        check(task['status'] == 'cancelled' and task['last_work'] == 0 and (task['served_work'] == prior['served_work']), 'cancel receipt preserves prior debit without new service')
    else:
        prior = json.loads((root / (a.engine + '-turn'+str(turn-1)+'.json')).read_text())['war_state']['red_units'][0]['crossing']
        check(task['intent_id'] != prior['intent_id'] and task['status'] == 'queued' and (0 < task['served_work'] <= 500) and (abs(task['served_work'] - task['last_work']) < 0.003), 'new intent at same destination starts fresh')
save('result', {'passed': True, 'session_id': sid, 'turn': state()['turn_count'], 'checks': checks, 'scope': 'explicit estimated post-bridge phase; not whole Wujiang acceptance'})
