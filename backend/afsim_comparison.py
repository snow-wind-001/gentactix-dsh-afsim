"""Read-only command intervention through the same external motion engine."""
import copy
from gentactix import commands, missions, sim_clock, adjudicator, combat_effects
from . import afsim_world, afsim_rules


def compare(session, record, orders, cancel_check=None, progress=None):
    before, factual = record['before'], record['after']
    from gentactix import crossings
    orders=crossings.comparison_orders(record,orders)
    if before.get('combined_arms') and factual.get('afsim', {}).get('motion_revision', 1) != afsim_world.motion_revision(before):
        raise ValueError('运动模型执行版本已更新；不能将不同版本结果归因为命令差异，请选择同版本新回合做对照')
    if before.get('combined_arms') and factual.get('afsim', {}).get('combat_revision', 1) != combat_effects.reference(before)['combat_revision']:
        raise ValueError('火力模型执行版本已更新；请选择相同持续火力版本的新回合做对照')
    if before.get('combined_arms') and factual['afsim']['combat_profile']['definition_hash'] != combat_effects.reference(before)['definition_hash']:
        raise ValueError('火力参照参数不同；不能将参数变化归因为命令差异')
    if before.get('combined_arms'):
        if factual.get('afsim',{}).get('supply_distribution')!=before['mission']['definition'].get('supply_distribution'):
            raise ValueError('分类粮弹配置不同，不能将规则变化归因为命令差异')
        if factual.get('afsim',{}).get('support_dynamics')!=before['mission']['definition'].get('support_dynamics'):
            raise ValueError('时间保障模型或参数不同，不能将规则变化归因为命令差异')
        if factual.get('afsim',{}).get('supply_schedule')!=before['mission']['definition'].get('supply_schedule'):
            raise ValueError('定时补给配置不同，不能将到货规则变化归因为命令差异')
        from . import afsim_combined
        revisions = {
            'command_control_revision': ('指挥', afsim_combined.COMMAND_CONTROL_REVISION),
            'supply_control_revision': ('补给控制', afsim_combined.SUPPLY_CONTROL_REVISION),
            'intelligence_revision': ('情报时效', afsim_combined.INTELLIGENCE_REVISION),
            'formation_fire_control_revision': ('编组火力控制', afsim_combined.FORMATION_FIRE_CONTROL_REVISION),
        }
        if before['mission']['definition'].get('support_dynamics') is None:
            revisions['legacy_support_revision'] = ('旧式保障', afsim_combined.LEGACY_SUPPORT_REVISION)
        for field, (label, expected) in revisions.items():
            actual = factual['afsim'].get(field)
            if type(actual) is not int:
                raise ValueError(label + '模型版本证据缺失或非法；不能假定旧回合使用当前规则，请选择同版本新回合做对照')
            if actual != expected:
                raise ValueError(label + '模型执行版本已更新；不能将规则变化归因为决策差异，请选择同版本新回合做对照')
    if before.get('mission'):
        missions.validate_orders(before, orders, record['time_step'])
    branch = {**session, 'war_state': copy.deepcopy(before), 'time_step': record['time_step']}
    scene = afsim_world.compile_scene(before, orders, sim_clock.duration_seconds(record['time_step']),native_rules=True)
    positions, evidence = afsim_world.run_scene(branch, scene, cancel_check, progress)
    if cancel_check and cancel_check():
        raise RuntimeError('用户取消只读AFSIM对照')
    observed = afsim_world.apply_observations(before, positions, scene)
    index = {commands.name_of(unit): unit for _, unit in commands.iter_units(observed)}
    actual = [{**order, **({key: index[order['unit']][key] for key in ('lat', 'lng')}
               if order['action'] == 'move' else {})} for order in orders]
    if before.get('mission'):
        if not evidence.get('native_effects'): raise ValueError('AFSIM分支缺少原生规则数据；不回退Python结算')
        alternative=afsim_rules.apply_telemetry(evidence.pop('native_effects'),scene['native_model'],scene,observed)
        alternative['current_time'],alternative['simulation_clock']=sim_clock.target(before,record['time_step'])
        from gentactix import unit_participation
        unit_participation.advance(before,alternative,orders,scene['seconds'],source='afsim_native')
        if alternative['mission']['definition'].get('campaign_plan'):
            missions.evaluate(alternative)
        missions.validate(alternative)
        alternative['combat_assessment']=combat_effects.assess_turn(before,alternative,scene['seconds'],orders,source='afsim_native')
        result = missions.compare_states(before,factual,alternative,actual)
        evidence['effects_source']=afsim_rules.VERSION
    else:
        observed['current_time'], observed['simulation_clock'] = sim_clock.target(before, record['time_step'])
        observed['engagements'] = []
        factual_index = {(team, commands.name_of(unit)): unit for team, unit in commands.iter_units(factual)}
        alternative_index = {(team, commands.name_of(unit)): unit for team, unit in commands.iter_units(observed)}
        metrics = []
        for team, unit in commands.iter_units(before):
            key = (team, commands.name_of(unit)); origin = commands.known_position(unit)
            a = commands.known_position(factual_index[key]); b = commands.known_position(alternative_index[key])
            if origin and a and b:
                distance = lambda point: adjudicator.distance_km((origin['lat'], origin['lng']), (point['lat'], point['lng']))
                av, bv = distance(a), distance(b)
                metrics.append({'metric': team + '/' + key[1] + '位移(km)', 'factual': round(av, 6),
                                'alternative': round(bv, 6), 'delta': round(bv-av, 6)})
        result = {'read_only': True, 'before_hash': commands.fingerprint(before), 'metrics': metrics,
                  'alternative': observed, 'orders': actual}
    result['mode'] = 'controlled_afsim'
    result['external_execution'] = evidence
    result['alternative']['afsim'] = {**evidence, 'phase': 'read_only_counterfactual'}
    result['limitations'] = ['相同决策前状态及命令条件下的AFSIM地理运动对照；不是已证明的历史因果效应。',
        '固定局部演习的消耗与目标由AFSIM执行同版本教学规则；航空任务使用独立教学航空参数；其他场景未添加武器和资源效果模型。']
    return result
