"""Configured real DSH checks event semantics, not a simulated campaign outcome."""
import argparse
import copy
import json
import os
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    if not parser.parse_args().live:
        parser.error('Use --live for the configured real model')
    root = Path('.cache/qa/wanjialing-continuous-2026-10-31/model') / str(time.time_ns())
    root.mkdir(parents=True)
    for key, suffix in [('SESSION_DIR', 'sessions'), ('TRACE_DIR', 'traces'), ('DSH_HOME', 'dsh-home'),
                        ('DSH_WORKSPACE', 'workspace'), ('ROLE_INDEX', 'roles.json')]:
        os.environ['GENTACTIX_' + key] = str(root.resolve() / suffix)
    from gentactix import history_replay
    from tools.upgrade_wanjialing import BATTLE
    from backend import harness_engine as h, runtime_bridge, afsim_state
    from backend.main import _native_tool_dispatch
    pinned = history_replay.pin(BATTLE, version='1.2.0')
    cursor = next(i for i, e in enumerate(pinned['pack']['events']) if e.get('event_key') == 'WJL-Oct8-142-departure')
    session = dict(id='wjl-source-revision-qa', war_state=history_replay.frame_pinned(pinned, cursor),
        turn_count=cursor, battle_choice=BATTLE, execution_backend='narrative', product_mode='analysis',
        simulation_mode='replay', use_rag=False, history=[])
    before = copy.deepcopy(session); calls = []; result = {'passed': False}
    observer = h.RunObserver('万家岭新资料时间与投入范围核验')
    def dispatch(context, payload):
        response = _native_tool_dispatch(context, payload)
        calls.append({'tool': payload.get('tool'), 'args': payload.get('args'), 'response': response})
        return response
    runtime_bridge.register_dispatcher(dispatch)
    result['probe_strategy'] = 'three_bounded_phase_queries'
    result['cases'] = []
    def ask(phase, prompt, expected):
        start = len(calls)
        query = ('实际调用retrieve_history(kind="operations",limit=2' +
            (',phase_id="' + phase + '"' if phase else '') + ')，沿next_args读完该阶段。'
            '读取完整阶段时完全省略query，不要自行添加关键词或使用*。只依据工具回答，不调用变更工具。' + prompt)
        run = h._run_brain(query, None, role='chat', observer=observer,
            native_context=afsim_state.operation_context(session))
        answer = h.parse_json_object(run.final_response)
        result['cases'].append({'phase': phase or 'current', 'answer': answer, 'call_count': len(calls) - start})
        assert answer == expected, answer
        assert session == before
    try:
        ask(None, '142师11时是出击还是首次接敌，记录是全师还是欠一团？是否核过档案原件，有无战术精确坐标？'
            '只返回JSON {"eleven_event":"departure或contact","whole_142":布尔值,'
            '"original_archive_examined":布尔值,"precise_positions_supplied":布尔值}。',
            dict(eleven_event='departure', whole_142=False, original_archive_examined=False, precise_positions_supplied=False))
        ask('oct9_final_orders', '9日发令、要求完成准备、开始攻击各是什么当地钟点？计划截止不代表实际已完成。'
            '只返回JSON {"order":"HH:MM","preparation_deadline":"HH:MM","attack":"HH:MM"}。',
            dict(order='15:00', preparation_deadline='18:00', attack='19:00'))
        ask('oct10_attacks', '10日攻占万家岭是否代表全役结束？是否仍有残敌抵抗？只返回JSON '
            '{"campaign_ended_oct10":布尔值,"residual_combat":布尔值}。',
            dict(campaign_ended_oct10=False, residual_combat=True))
        reads = [c for c in calls if c['tool'] == 'retrieve_history']
        rows = [o for c in reads for o in c['response'].get('operations', [])]
        assert len({o['id'] for o in rows}) == 12, rows
        assert any(c['response'].get('phase_id') == 'oct8_counterattacks' and 'phase_id' not in c['args'] for c in reads)
        assert session == before
        result.update(passed=True, world_unchanged=True, meta=observer.meta())
        print('PASS configured real DSH: partial formation, three distinct times, residual combat and evidence boundary', flush=True)
    finally:
        result['world_unchanged'] = session == before
        result['calls'] = calls
        (root / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
        (root / 'runs.json').write_text(json.dumps(observer.runs, ensure_ascii=False, indent=2))
        h.close_harness()
        print('Evidence:', root, flush=True)


if __name__ == '__main__':
    main()
