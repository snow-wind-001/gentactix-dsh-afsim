"""Structured DSH planning followed by native-MCP AFSIM execution and local rules."""
import copy
import json

from gentactix import anchors, battle_scope, commands, missions, sim_clock, prompts, combat_effects
from . import afsim_state, afsim_world, afsim_rules, harness_engine as h
from . import unit_order_submission


def advance(session, prepared, observer, *, instruction='', briefing='', native_orders=(), cancel_check=None):
    before = session['war_state']
    nodes = anchors.collect_available_nodes(session.get('scenario_input', ''), battle=session.get('battle_choice'))
    battle_scope.validate(before, nodes)
    pairs = commands.resolve_units(session, prepared['state'])
    by_id = {identity: entry for identity, (entry, _) in pairs.items()}
    covered = {item['order']['unit'] for item in prepared['manual']} | {order['unit'] for order in native_orders}
    covered.update(by_id[item['unit_id']]['name'] for item in prepared['blocked'] if item['unit_id'] in by_id)
    covered.update(r['unit'] for r in prepared.get('cancelled_tasks',[]) if not any(x['order']['unit']==r['unit'] for x in prepared['manual']))
    all_covered = all(entry['name'] in covered or not commands.available(unit) for entry, unit in pairs.values())
    native_submit = h.NATIVE_RUNTIME and session.get('agent_mode') == 'native'
    prompt = afsim_state.planning_prompt(session, prepared, instruction, briefing,
        covered_names=covered, native_submit=native_submit) + '\n' + prompts.mode_instruction(session.get('simulation_mode', 'open'))
    proposals, decisions = [], []
    if not all_covered:
        # The authoritative world is external to model memory. Each planning run
        # gets a new native session; journals remain available in the trajectory.
        context = (unit_order_submission.planner_context(session, prepared, covered,
            operation_id=observer.operation_id) if native_submit else afsim_state.operation_context(session))
        for attempt in range(2):
            if cancel_check and cancel_check():
                raise RuntimeError('已取消规划，命令未执行')
            try:
                payload = h.get_ai_response(prompt, role_id=None, observer=observer, native_context=context, cancel_check=cancel_check)
                submitted = unit_order_submission.submitted_planner(observer, context) if native_submit else None
                proposals, decisions = [], []
                if not isinstance(payload, dict) or set(payload) - {'orders'} or not isinstance(payload.get('orders'), list):
                    raise ValueError('AFSIM规划器只能返回orders，不能生成或替换权威战场状态')
                if len(payload['orders']) > len(pairs):
                    raise ValueError('AFSIM规划命令数超过实体数')
                seen = set()
                for draft in payload['orders']:
                    if not isinstance(draft, dict) or set(draft) - {'unit_id', 'action', 'duration', 'destination', 'target_id','air_pool','participation', 'rationale', 'expected_effect'}:
                        raise ValueError('AFSIM规划命令字段非法')
                    identity = draft.get('unit_id')
                    if identity not in pairs or identity in seen:
                        raise ValueError('AFSIM规划引用未知或重复单位ID')
                    seen.add(identity)
                    entry, unit = pairs[identity]
                    if entry['name'] in covered or not commands.available(unit):
                        continue
                    if not str(draft.get('rationale') or '').strip():
                        raise ValueError('AFSIM自主决策缺少公开依据：' + entry['name'])
                    normalized = {key: copy.deepcopy(draft[key]) for key in ('unit_id', 'action', 'destination', 'target_id','air_pool','participation') if key in draft}
                    normalized['duration'] = draft.get('duration', 'next')
                    if normalized['duration'] not in ('next', 'until_arrived') or (normalized['duration'] == 'until_arrived' and normalized.get('action') != 'move'):
                        raise ValueError('AFSIM自主规划持续方式非法')
                    proposals.append(commands.step_order(session, normalized, prepared['state']))
                    decisions.append({'team': entry['team'], 'unit_name': entry['name'], 'action': normalized['action'],
                        'rationale': str(draft.get('rationale') or '')[:600], 'expected_effect': str(draft.get('expected_effect') or '')[:600],
                        **({'proposal':copy.deepcopy(submitted[1])} if submitted else {})})
                missing = [identity for identity, (entry, unit) in pairs.items()
                           if entry['name'] not in covered and commands.available(unit) and identity not in seen]
                if missing:
                    raise ValueError('AFSIM规划遗漏可行动单位，双方均须逐单位提交明确决策（可明确hold）：' +
                                     json.dumps({i: {'team': pairs[i][0]['team'], 'name': pairs[i][0]['name']}
                                                 for i in missing}, ensure_ascii=False))
                break
            except ValueError as exc:
                if attempt:
                    raise
                # A parse exception contains the raw model response. Do not
                # feed that untrusted text back into the next planning run.
                reason = ('AI 返回的 JSON 无法解析：' + exc.diagnostics['reason']
                          if isinstance(exc, h.JSONOutputError) else str(exc)[:1200])
                prompt += ('\n【候选未执行，战局和资源未改动】' + reason +
                    '。这是最后一次校验重试。重新观察必要单位，核对完整ID和可用行动，返回完整orders。'
                    + ('原生规划工具可用时，请调用submit_planner_orders提交完整候选；仅文字确认不能代替提交。'
                       if native_submit else '') +
                    '合法身份：' + json.dumps({identity: entry['name'] for identity, entry in by_id.items()}, ensure_ascii=False))
    proposals.extend(copy.deepcopy(list(native_orders)))
    executed = commands.merge_proposal(session, prepared, proposals)
    return execute_scene(session,executed,observer,cancel_check=cancel_check,prompt=prompt,decisions=decisions,all_covered=all_covered)


def execute_scene(session,executed,observer,*,cancel_check=None,prompt='',decisions=(),all_covered=True,scene=None,world_validator=None):
    """Shared native execution/decoding; diagnostic callers may supply a bound validator."""
    before=session['war_state']
    nodes=anchors.collect_available_nodes(session.get('scenario_input',''),battle=session.get('battle_choice'))
    if world_validator is not None:world_validator(before)
    scene = scene or afsim_world.compile_scene(before, executed, sim_clock.duration_seconds(session['time_step']),native_rules=True)
    positions, evidence = afsim_world.run_scene(session, scene, cancel_check, observer.progress)
    observed = afsim_world.apply_observations(before, positions, scene)
    battle_scope.validate(observed, nodes)
    if cancel_check and cancel_check():
        raise RuntimeError('AFSIM运行后收到取消，结果未提交')
    if session.get('mission_id'):
        if not evidence.get('native_effects'):
            raise ValueError('AFSIM未回传原生规则数据；不能回退Python教学结算')
        after = afsim_rules.apply_telemetry(evidence.pop('native_effects'),scene['native_model'],scene,observed)
        after['current_time'], after['simulation_clock'] = sim_clock.target(before,session['time_step'])
        from gentactix import unit_participation
        unit_participation.advance(before,after,executed,scene['seconds'],source='afsim_native')
        if after['mission']['definition'].get('campaign_plan'):
            missions.evaluate(after)
        (world_validator or missions.validate)(after)
        after['combat_assessment']=combat_effects.assess_turn(before,after,scene['seconds'],executed,source='afsim_native')
        report = missions.report(after)
        report = report.replace('人员、库存与目标由教学规则计算',
            '人员与库存来自AFSIM执行回执，目标图由宿主读取物理结果评分' if after['mission']['definition'].get('campaign_plan')
            else '人员、库存与目标由AFSIM后台执行教学规则计算')
        report += ' '+combat_effects.loss_summary(before,after)
        report += ' '+combat_effects.review_summary(after['combat_assessment'])
        if after.get('combined_arms'):
            bridge=after['combined_arms']['bridge'];models=[u['formation']['last_execution'] for _,u in missions.units(after)]
            report+=f" 多兵种保障：桥梁施工{bridge['progress']}%，完整度{bridge['integrity']}%，本轮通行{bridge['used']}/{bridge['capacity']}批次；防空消耗{sum(x['aa_spent'] for x in models)}发，修复装备{sum(x['repaired'] for x in models)}件，运输到货{sum(x['delivery_tons_milli'] for x in models)/1000:g}吨（教学补给包）。"
        air = after.get('air_operations')
        if air and air['missions']:
            report += ' 航空任务：' + '；'.join(f"{t['requester']}→{t['target']}，{'完成打击' if t['hit'] else '目标脱离中止'}，出动{t['package']}架、损失{t['aircraft_lost']}架，航空油/弹消耗{t['fuel_spent']}/{t['ordnance_spent']}工作单位。" for t in air['missions'])
        effect_source = afsim_rules.VERSION
    else:
        after = observed
        after['current_time'], after['simulation_clock'] = sim_clock.target(before, session['time_step'])
        after['engagements'] = []
        report = f'AFSIM完成{len(positions)}个实体的本轮位置更新，执行{len(executed)}项明确命令；其余单位待命。'
        report += '本模式只计算运动；人员装备和补给账按既有记录保留，未生成武器战损或补给到货。'
        effect_source = 'not_modeled; existing_ledgers_preserved'
    from gentactix import formation_parts
    # This frame's Native receipt supersedes the previous backend's current
    # cache. Before snapshots/trajectory keep its evidence; unit state survives.
    after.pop('dsh_execution',None)
    after['afsim'] = {**evidence, 'effects_source': effect_source,
                      'roster_digest':formation_parts.roster_digest(after),
                      'air_task_count':len(after.get('air_operations',{}).get('missions',[])),
                      'orders': copy.deepcopy(executed),
                      'context_strategy': 'fresh_dsh_planner_with_external_world',
                      'planner_prompt_chars': len(prompt) if not all_covered else 0,
                      'world_chars': len(json.dumps(before, ensure_ascii=False)),
                      'model_skipped': bool(all_covered)}
    return ({'updated_state': after, 'report': report, 'decisions': decisions,
             'external_execution': after['afsim'],
             'source_note': 'AFSIM实际运行及DSH原生MCP调度证据；运动以外效果来源：' + effect_source}, executed, prompt)
