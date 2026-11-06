"""Frozen phase handoffs: carry committed ledgers, never reset surviving units."""
import copy
from datetime import datetime

from . import missions, historical_operations, sim_clock

LEGACY_VERSION = 'historical-phase-continuity-1'
VERSION = 'historical-phase-continuity-2'


def _key(team, unit):
    return team, unit.get('calculation_unit_id') or unit['historical_unit_id']


def definition(binding):
    if (not isinstance(binding, dict) or set(binding) != {'version', 'source', 'source_hash', 'target'}
            or binding['version'] not in (LEGACY_VERSION, VERSION)):
        raise ValueError('阶段续接缺少冻结前态与目标参数')
    source = binding['source']
    if missions.digest(source) != binding['source_hash']:
        raise ValueError('阶段前态摘要不一致')
    depth = 0
    cursor = source
    archived = set()
    past_historical = {(t,u['historical_unit_id']) for t,u in missions.units(source)}
    while cursor['mission']['definition'].get('phase_continuation'):
        depth += 1
        if depth >= 8:
            raise ValueError('单条阶段链最多8次续接，请先导出复核')
        cursor = cursor['mission']['definition']['phase_continuation']['source']
        archived.update(_key(t,u) for t,u in missions.units(cursor))
        past_historical.update((t,u['historical_unit_id']) for t,u in missions.units(cursor))
    missions.validate(source)
    prior = source['mission']['definition']
    if source['mission']['status'] != 'completed' or not prior.get('historical_calculation'):
        raise ValueError('只可续接已结算的历史参数化阶段')
    target = historical_operations.from_binding(binding['target'])
    if prior.get('fire_dynamics')!=target.get('fire_dynamics'):
        raise ValueError('阶段续接不得改变动态密度火力过程；新规则须显式新建配置，不能重解释旧战局')
    if prior.get('campaign_plan') or target.get('campaign_plan'):
        raise ValueError('持续目标图须在同一会战世界推进；旧相邻阶段续接尚不支持其生命周期，拒绝重置目标进度')
    old_fact = prior['historical_calculation']['initial']
    new_fact = binding['target']['initial']
    if any(old_fact[k] != new_fact[k] for k in ('profile_id', 'version', 'definition_hash')):
        raise ValueError('阶段续接必须来自同一冻结历史档案版本')
    start = binding['target']['parameters']['clock']['start']
    try:
        adjacent = datetime.fromisoformat(start) == datetime.fromisoformat(source['current_time'])
    except ValueError:
        adjacent = False
    if not adjacent:
        raise ValueError('阶段时钟必须相接；间隙须先计算消耗与转移，不能跳时或倒退')
    if binding['version'] == VERSION:
        # Existing v1 checkpoints retain their exact frozen interpretation.
        # New host-created continuations may replace goals, but changing a
        # physical rate would silently revalue the equipment and stocks below.
        old_rules, new_rules = prior['combined_rules'], target['combined_rules']
        changed = sorted(key for key in old_rules.keys() | new_rules.keys()
                         if key not in ('goal_profile', 'required_survivors')
                         and old_rules.get(key) != new_rules.get(key))
        # Legacy physical coefficients include per-turn rates. The same number
        # with a different physical period is not the same resource contract.
        if sim_clock.duration_seconds(prior['time_step']) != sim_clock.duration_seconds(target['time_step']):
            changed.append('time_step')
        if prior.get('fire_accounting')!=target.get('fire_accounting'):
            changed.append('fire_accounting（弹药计量）')
        if changed:
            raise ValueError('阶段续接不得改变物理／保障规则：' + '、'.join(changed)
                             + '；换装、重新标定或计算粒度换算须登记明确的变更与资源账')
    # Normalized food/ammo and sustainment debt cannot change units mid-chain.
    for key in ('support_dynamics', 'supply_distribution', 'supply_schedule', 'air_definition', 'movement_feedback'):
        if prior.get(key) != target.get(key):
            raise ValueError('阶段续接不得重置或换算未登记的模型：' + key)
    if source.get('formation_groups') != target['initial_state'].get('formation_groups'):
        raise ValueError('编组拆合尚需显式重编分配账，不能按父番号复制资源')
    old = {_key(t, u): u for t, u in missions.units(source)}
    new = {_key(t, u): u for t, u in missions.units(target['initial_state'])}
    if len(old) != len(list(missions.units(source))) or len(new) != len(list(missions.units(target['initial_state']))):
        raise ValueError('阶段单位身份重复')
    carried, entered, exited = [], [], []
    dynamic = ('personnel', 'equipment', 'logistics', 'formation', 'sustainment',
               'lat', 'lng', 'hp', 'supply', 'morale', 'crossing')
    for key, unit in new.items():
        if key not in old:
            if key in archived:
                raise ValueError('曾退出范围的单位重新入场须从归档前态补算，不能使用新初态补满')
            hierarchy={u['id']:u['parent_id'] for u in new_fact['definition']['units']}
            def ancestors(identity):
                result=set()
                while hierarchy.get(identity):
                    identity=hierarchy[identity];result.add(identity)
                return result
            past_ids={identity for team,identity in past_historical if team==key[0]}
            identity=unit['historical_unit_id']
            if ancestors(identity)&past_ids or any(identity in ancestors(i) for i in past_ids):
                raise ValueError('上下级编制替换须登记重编分配账，不能作为全新单位补员')
            entered.append({'team': key[0], 'id': key[1], 'name': unit['name'],
                            'basis': '目标阶段已核在场身份；数值沿用其显式估计输入'})
            continue
        previous = old[key]
        if previous.get('crossing',{}).get('status') in ('queued','transit'):
            raise ValueError('未完成渡运须先完成原任务或登记完整舟艇交接，不能重置渡运进度')
        if previous.get('crossing') and any(source['combined_arms']['bridge'].get(k)!=target['initial_state']['combined_arms']['bridge'].get(k)
                for k in ('id','crossing_model','crossing_network')):
            raise ValueError('渡运设施变更须登记任务交接，不能遗失已有渡运账')
        if any(unit.get(k) != previous.get(k) for k in ('type','speed','attack_range','ground_control_radius_km')):
            raise ValueError('同一单位的性能变化须登记换装或重编，不能随阶段隐式升级')
        for field in dynamic:
            if field in previous:
                unit[field] = copy.deepcopy(previous[field])
            else:
                unit.pop(field, None)
        unit['formation'].pop('last_execution', None)
        for field in ('personnel','equipment','position','logistics'):
            unit['parameter_sources'][field] = {'kind':'carried_computed', 'source_hash':binding['source_hash'],
                'source_unit_id':key[1], 'target_reference':copy.deepcopy(unit['parameter_sources'].get(field))}
        if 'last_receipt' in unit.get('sustainment', {}):
            unit['sustainment'].pop('last_receipt')
        if source.get('campaign') and target['initial_state'].get('campaign'):
            from . import campaign
            old_schedule = campaign.scheduled_time(prior['campaign_definition'], previous)
            new_schedule = campaign.scheduled_time(target['campaign_definition'], unit)
            active = campaign.release_seconds(source, previous) == 0
            if ((active and datetime.fromisoformat(new_schedule) > datetime.fromisoformat(start))
                    or (not active and datetime.fromisoformat(new_schedule) != datetime.fromisoformat(old_schedule))):
                raise ValueError('已入场单位不能重新等待，未入场单位须保留实际等待时点')
            actor = copy.deepcopy(source['campaign']['actors'][previous['name']])
            actor.update(active=active, captured_this_turn=0)
            target['initial_state']['campaign']['actors'][unit['name']] = actor
        carried.append({'team': key[0], 'id': key[1], 'name': unit['name'],
                        'current': unit['personnel']['current'], 'casualties': unit['personnel']['casualties']})
    for key, unit in old.items():
        if key not in new:
            exited.append({'team': key[0], 'id': key[1], 'name': unit['name'],
                           'personnel': copy.deepcopy(unit['personnel']),
                           'equipment': copy.deepcopy(unit['equipment']),
                           'logistics': copy.deepcopy(unit['logistics']),
                           'basis': '退出当前计算范围，完整前态冻结保留；不等于阵亡或资源消失'})
    old_nodes = {n['id']: n for n in source['supply_nodes']}
    if set(old_nodes) != {n['id'] for n in target['initial_state']['supply_nodes']}:
        raise ValueError('补给节点改变须登记仓库转移，不能自动新建满库')
    if any(old_nodes[n['id']]['team'] != n['team'] or missions.distance(old_nodes[n['id']], n) > .001
           for n in target['initial_state']['supply_nodes']):
        raise ValueError('仓库位置或阵营变化须登记转移，不能在阶段切换中瞬移')
    target['initial_state']['supply_nodes'] = copy.deepcopy(source['supply_nodes'])
    target['initial_state']['combined_arms']['depots'] = copy.deepcopy(source['combined_arms']['depots'])
    if 'aa_loss_remainder' in source['combined_arms']:
        target['initial_state']['combined_arms']['aa_loss_remainder'] = copy.deepcopy(source['combined_arms']['aa_loss_remainder'])
    for field in ('air_operations', 'combat_reference'):
        if field in source:
            target['initial_state'][field] = copy.deepcopy(source[field])
    bridge = source['combined_arms']['bridge']
    next_bridge = target['initial_state']['combined_arms']['bridge']
    if bridge.get('id') == next_bridge.get('id'):
        target['initial_state']['combined_arms']['bridge'] = copy.deepcopy(bridge)
    target['phase_continuation'] = copy.deepcopy(binding)
    target['initial_state']['phase_handoff'] = {'version': binding['version'],
        'from_phase': old_fact['phase_id'], 'to_phase': new_fact['phase_id'],
        'source_hash': binding['source_hash'], 'carried': carried, 'entered': entered, 'exited': exited,
        'scope': '连续计算分支；继承实际结果，阶段目标重置；不强制历史结果，不自动补员、恢复装备或填满库存'}
    target['id'] = 'HP-' + missions.digest(binding)[:20]
    target['title'] = '连续阶段 · ' + target['title']
    return target


def bind(source, target):
    return {'version': VERSION, 'source': copy.deepcopy(source),
            'source_hash': missions.digest(source), 'target': copy.deepcopy(target)}
