"""Real SDK/native Agent role surfaces and casualty analysis; isolated QA only."""
import argparse
import copy
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid

from tools.qa.historical_operational_fixture import BATTLE, inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--port', type=int, default=18998)
    parser.add_argument('--out', type=Path, default=Path('.cache/qa/runtime-visibility'))
    args = parser.parse_args()
    if not args.live or not 18900 <= args.port <= 18999:
        parser.error('Use --live with an isolated QA port')
    root = args.out; root.mkdir(parents=True, exist_ok=True)
    result = {'passed': False, 'checks': [], 'historical_fit_verified': False}

    def save(name, value):
        (root/(name+'.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2))

    def check(ok, label):
        if not ok:
            raise AssertionError(label)
        result['checks'].append(label); print('PASS', label, flush=True)

    def call(method, path, payload=None):
        request = urllib.request.Request(f'http://127.0.0.1:{args.port}'+path, method=method,
            headers={'Content-Type': 'application/json'},
            data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode())
        try:
            with urllib.request.urlopen(request, timeout=1200) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(str(exc.code)+': '+exc.read().decode()[:2000]) from exc

    def headers():
        rows = []
        for path in (root/'runtime/dsh-home/sessions').rglob('session.v4.jsonl'):
            for line in path.open():
                event = json.loads(line)
                if event.get('type') != 'request/header':
                    continue
                header = event['data']['header']; config = header['config']
                rows.append({'session_id': path.parent.name, 'seq': event['seq'],
                    'tools': [t['name'] for t in header.get('tools', [])],
                    'schema_chars': sum(len(json.dumps(t, ensure_ascii=False)) for t in header.get('tools', [])),
                    'reasoning_effort': config.get('reasoningEffort'), 'max_tokens': config.get('maxTokens')})
        return rows

    def revision(view):
        return {'expected_turn': view['turn'], **{k: view[k] for k in ('revision', 'world_version')}}

    started = time.monotonic()
    baseline = {(r['session_id'], r['seq']) for r in headers()}

    def current_headers():
        return [r for r in headers() if (r['session_id'], r['seq']) not in baseline]

    try:
        check(not call('GET', '/api/health')['build']['restart_required'], 'fresh source API')
        sid = json.loads((root/'combat/result.json').read_text())['session_id']
        before = call('GET', f'/api/sessions/{sid}')
        response = call('POST', f'/api/sessions/{sid}/chat', {'message':
            '必须实际调用get_afsim_observation、get_afsim_changes读取已提交结果。简短表格列出第31师、濑谷支队和坂本支队累计减员、阵亡与负伤；'
            '区分三小时历时与承受火力时长，指出待命不应自动减员、历史近3000为同番号但不同统计窗口，不是本局扣兵目标。不得修改战局。'})
        save('analysis', response)
        check(response['war_state'] == before['war_state'], 'real DSH analysis preserves authoritative casualty ledger')
        check(response['engine_meta']['finish_reason'] == 'completed', 'real DSH casualty analysis completed')
        rows = current_headers(); save('headers-analysis', rows)
        allowed = {'get_afsim_observation', 'get_afsim_changes', 'retrieve_history', 'evaluate_action'}
        check(bool(rows) and all(set(r['tools']) == allowed for r in rows), 'first SDK request exposes exactly four role tools')
        check(all(r['reasoning_effort'] == 'high' and r['max_tokens'] == 65536 for r in rows), 'saved high reasoning and 64K preserved')
        text = response['chat_messages'][-1]['content']
        check(all(str(v) in text for v in (85, 21, 64, 161, 40, 121)), 'model answer contains actual casualty categories for both combatants')

        _, parameters = inputs(); parameters = copy.deepcopy(parameters); parameters['goal']['deadline_turn'] = 30
        auto = call('POST', '/api/sessions', {'scenario': '角色工具隔离与双方决策QA；数值部署为显式估计',
            'battle': BATTLE, 'product_mode': 'historical', 'execution_backend': 'afsim',
            'historical_parameters': parameters, 'persist_roles': False})['session_id']
        initial = call('POST', f'/api/sessions/{auto}/init')
        view = call('GET', f'/api/sessions/{auto}/commands')
        target = next(u for u in view['units'] if u['team'] == 'red')
        proposal = call('POST', f'/api/sessions/{auto}/commands/resolve', {**revision(view),
            'text': '所选单位原地待命，仅下一回合。', 'selected_units': [target['id']]})
        save('proposal', proposal)
        check(proposal['status'] == 'draft' and proposal['orders'][0]['action'] == 'hold', 'actual natural language parser works with zero native tools')
        check(call('GET', f'/api/sessions/{auto}')['war_state'] == initial['war_state'], 'command interpretation remains a draft')
        view = call('GET', f'/api/sessions/{auto}/commands')
        after = call('POST', f'/api/sessions/{auto}/next', {**revision(view), 'batch_id': uuid.uuid4().hex,
            'instruction': '先调用get_afsim_observation读取实际状态。第31师与濑谷支队互相fire，坂本支队hold；双方每个可行动单位都提交明确命令。勿改写历史身份或强制历史损失。'})
        save('planned-turn', after)
        check(not after['war_state']['afsim']['model_skipped'] and len(after['war_state']['afsim']['orders']) == 3,
              'real DSH plans all three actors with restricted tools then native AFSIM executes')
        check(after['war_state']['historical_initial'] == initial['war_state']['historical_initial'], 'real plan preserves source identities')
        rows = current_headers(); save('headers-final', rows)
        check(any(not r['tools'] for r in rows), 'zero-tool role sends no inherited schemas')
        check(all(set(r['tools']) <= allowed for r in rows), 'no scenario or raw MCP schema leaks into decision or analysis')
        result.update(passed=True, analysis_session=sid, planning_session=auto,
            seconds=round(time.monotonic()-started, 2), headers=rows)
        save('result', result)
    except Exception as exc:
        result['error'] = str(exc); save('result', result); raise


if __name__ == '__main__':
    main()
