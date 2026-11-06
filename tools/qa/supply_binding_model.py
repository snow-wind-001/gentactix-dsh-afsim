"""Ask the configured model to inspect actual native multi-depot receipts.

Uses existing DSH observation paging; no world or command writes are allowed.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import time
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--native-run', type=Path, required=True)
    args = parser.parse_args()
    if not args.live:
        parser.error('--live required to call the configured model')
    root = Path('.cache/qa/supply-binding-2026-11-01/model') / str(time.time_ns())
    root.mkdir(parents=True)
    for key, suffix in [('SESSION_DIR', 'sessions'), ('TRACE_DIR', 'traces'), ('DSH_HOME', 'dsh-home'),
                        ('DSH_WORKSPACE', 'workspace'), ('ROLE_INDEX', 'roles.json')]:
        os.environ['GENTACTIX_' + key] = str((root / suffix).resolve())
    # Model config is read from the existing encrypted settings; no overrides.
    from backend import harness_engine as h, runtime_bridge, afsim_state
    from backend.main import _native_tool_dispatch
    from gentactix import missions
    world = json.loads((args.native_run / 'combined-split.json').read_text())
    native = json.loads((args.native_run / 'result.json').read_text())
    assert native['passed']
    world['afsim'] = next(c['native'] for c in native['cases'] if c['label'] == 'combined-split')
    session = {'id': 'a123456789ab', 'war_state': world, 'turn_count': 1, 'role_epoch': 0,
               'product_mode': 'synthetic', 'simulation_mode': 'open', 'time_step': '30分钟',
               'execution_backend': 'afsim'}
    frozen = copy.deepcopy(session)
    calls = []

    def dispatch(context, payload):
        if payload.get('tool') != 'get_afsim_observation':
            raise ValueError('QA只读检查只允许现有get_afsim_observation')
        response = _native_tool_dispatch(context, payload)
        calls.append({'args': payload.get('args'), 'result': response})
        return response

    runtime_bridge.register_dispatcher(dispatch)
    result = {'passed': False, 'actual_model': True, 'world_unchanged': False,
              'native_input': str(args.native_run),
              'scope': 'Read-only per-unit bound-depot inspection, not autonomous logistics planning or calibrated history'}
    observer = h.RunObserver('真实DSH多仓库绑定只读核验')
    try:
        original = missions.definition
        spec = world['mission']['definition']
        with patch.object(missions, 'definition', side_effect=lambda identity:
                          copy.deepcopy(spec) if identity == spec['id'] else original(identity)):
            missions.validate(world)
            answer = h._run_brain(
                '只读核对当前6个单位的补给。调用get_afsim_observation，limit=2，从offset=0沿next_offset读完3页，'
                '不要改命令或执行推演。根据每单位supply_binding和mission.ledger回答；不能用同阵营总库存代替绑定仓库。'
                '只返回JSON：{"units":[{"name":"精确单位名","node_id":"实际绑定ID","stock":绑定仓当前工作量库存,'
                '"food_received":当轮粮食到货,"ammo_received":当轮弹药到货}],'
                '"classified_stock_scope":"燃油炮弹等按站点还是阵营归集，请填写工具返回值"}。'
                '没有库存或到货为0时保留0；这些是QA教学工作量，不是历史吨数，不估算未提供值。',
                None, observer=observer, role='chat', native_context=afsim_state.operation_context(session))
        data = h.parse_json_object(answer.final_response)
        rows = data['units']
        assert len(rows) == len({r['name'] for r in rows}) == 6
        actual = {u['name']: u for _, u in missions.units(world)}
        assert {r['name'] for r in rows} == set(actual)
        stocks = {n['id']: n['stock'] for n in world['supply_nodes']}
        receipts = {r['unit']: r for r in world['mission']['ledger']}
        for row in rows:
            unit = actual[row['name']]
            assert row['node_id'] == unit['supply_node_id']
            assert row['stock'] == stocks[unit['supply_node_id']]
            for key in ('food_received', 'ammo_received'):
                assert row[key] == receipts[row['name']][key]
        assert data['classified_stock_scope'] == 'team_pool'
        assert {c['args'].get('offset', 0) for c in calls} >= {0, 2, 4}
        assert session == frozen
        result.update(passed=True, world_unchanged=True, answer=data, engine_meta=observer.meta())
        print('PASS real model:6 exact bindings,3 pages,zero deliveries,team-pool boundary', flush=True)
    except Exception as exc:
        result['error'] = str(exc)
        raise
    finally:
        result['calls'] = calls
        (root / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        (root / 'runs.json').write_text(json.dumps(observer.runs, ensure_ascii=False, indent=2) + '\n')
        h.close_harness()
        print('Evidence:', root, flush=True)


if __name__ == '__main__': main()
