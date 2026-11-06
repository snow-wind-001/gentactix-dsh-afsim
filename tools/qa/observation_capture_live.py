"""Replay saved orders in native AFSIM, then verify real DSH compact/detail reads."""
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
    parser.add_argument('--trace', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    if not args.live:
        parser.error('Use --live for native execution and a real model call')
    root = Path('.cache/qa/observation-review-2026-10-29/live') / str(time.time_ns())
    root.mkdir(parents=True)
    for key, suffix in [('SESSION_DIR', 'sessions'), ('TRACE_DIR', 'traces'),
                        ('DSH_HOME', 'dsh-home'), ('DSH_WORKSPACE', 'workspace'), ('ROLE_INDEX', 'roles.json')]:
        os.environ['GENTACTIX_' + key] = str(root.resolve() / suffix)
    os.environ['GENTACTIX_LLM_CONFIG'] = str(args.config.resolve())
    from backend import afsim_world, afsim_rules, afsim_state, runtime_bridge, harness_engine as h
    from backend.main import _native_tool_dispatch
    from gentactix import missions, sim_clock, combat_effects
    trace = json.loads(args.trace.read_text())
    before, orders = trace['before'], trace['external_execution']['orders']
    original = copy.deepcopy(before)
    result = {'passed': False, 'scope': 'saved-order native replay and read-only real DSH; not historical calibration'}
    responses = []

    def dispatch(context, payload):
        response = _native_tool_dispatch(context, payload)
        responses.append({'tool': payload.get('tool'), 'args': payload.get('args'),
            'ok': response.get('ok'), 'chars': len(json.dumps(response, ensure_ascii=False)),
            'ids': [u['id'] for u in response.get('units', [])],
            'detail': response.get('observation_detail'), 'error': response.get('error')})
        return response

    runtime_bridge.register_dispatcher(dispatch)
    policy = h.role_policy('chat')
    assert policy['reasoning_effort'] == 'high' and policy['max_tokens'] == 65536
    try:
        scene = afsim_world.compile_scene(before, orders, 1800, native_rules=True)
        with patch.object(missions, 'advance', side_effect=AssertionError('No Python combat executor')):
            positions, evidence = afsim_world.run_scene({}, scene)
            world = afsim_rules.apply_telemetry(evidence.pop('native_effects'), scene['native_model'], scene,
                afsim_world.apply_observations(before, positions, scene))
        world['current_time'], world['simulation_clock'] = sim_clock.target(before, '30分钟')
        world['afsim'] = evidence
        world['combat_assessment'] = combat_effects.assess_turn(before, world, 1800, orders, source='afsim_native')
        missions.validate(world)
        assert before == original
        # Presentation/projection changes must not change any native outcome.
        for team in ('red', 'blue'):
            for a, b in zip(world[team+'_units'], trace['after'][team+'_units']):
                for field in ('name', 'personnel', 'equipment', 'lat', 'lng'):
                    assert a[field] == b[field], (a['name'], field)
        captured = [u for u in world['combat_assessment']['units'] if (u['turn_captured'] or 0) > 0]
        assert len(captured) == 1 and captured[0]['order_interruption'] == 'captured_before_execution'
        assert 'fire_receipt_missing' not in captured[0]['issues']
        result['native'] = {k: evidence[k] for k in ('returncode', 'status', 'artifact', 'entity_count', 'wall_ms')}
        (root/'world.json').write_text(json.dumps(world, ensure_ascii=False, indent=2))
        (root/'loss-summary.txt').write_text(combat_effects.loss_summary(before, world))
        print('PASS native replay, identical personnel/equipment/positions and classified capture', flush=True)

        session = {'id': 'capture-readonly-qa', 'war_state': world, 'turn_count': world['mission']['turn'],
            'time_step': '30分钟', 'execution_backend': 'afsim', 'history': [], 'trajectory': [], 'use_rag': False}
        original_session = copy.deepcopy(session)
        observer = h.RunObserver('紧凑观测与受降分类只读验收')
        prompt = ('只读验收。先用get_afsim_observation默认紧凑模式，从offset=0、limit=16分页读完全部登记单位。'
            '找出本轮被俘的部队，对它按detail_query读取完整单位来源，确认省略来源不是没有来源。'
            '不要下命令、不要试算、不要调用其他工具。不复制完整态势。最终只返回JSON：'
            '{"current_time":"当前时间","registered_units":登记总数,"captured_this_turn":本轮被俘合计,'
            '"capture_unit":"部队名称","capture_interruption":"该部射击是否执行及证据，简短说明",'
            '"detail_evidence":"完整字段中投入人员估计口径，60字内","historical_fit_verified":是否已通过历史标定}。')
        answer = h._run_brain(prompt, None, observer=observer, role='chat',
            native_context=afsim_state.operation_context(session))
        parsed = h.parse_json_object(answer.final_response)
        expected_ids = {u['id'] for u in afsim_state.observation(session, {'limit': 16})['units']}
        expected_ids.update(u['id'] for u in afsim_state.observation(session, {'offset': 16, 'limit': 16})['units'])
        compact_ids = {i for r in responses if r['detail'] == 'compact' for i in r['ids']}
        assert compact_ids == expected_ids
        assert any(r['detail'] == 'full_unit_detail' and len(r['ids']) == 1 for r in responses)
        assert parsed['registered_units'] == len(expected_ids)
        assert parsed['captured_this_turn'] == sum(r['turn_captured'] or 0 for r in world['combat_assessment']['units'])
        assert parsed['current_time'] == world['current_time'] and parsed['historical_fit_verified'] is False
        assert parsed['capture_unit'] == captured[0]['name']
        assert session == original_session
        result.update(passed=True, world_unchanged=True, answer=parsed, tools=responses, engine_meta=observer.meta())
        print('PASS real DSH compact pages and one-unit detail, unchanged world', flush=True)
    finally:
        h.close_harness()
        (root/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
        Path('.cache/qa/observation-review-2026-10-29/live-latest.txt').write_text(str(root))
        print(str(root), flush=True)


if __name__ == '__main__':
    main()
