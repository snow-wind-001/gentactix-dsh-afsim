"""Versioned, opt-in teaching missions. Pure transitions; no network or live writes.

Coordinates, inventories and coefficients in these local exercises are explicit
teaching assumptions, not reconstructions of historical tactical dispositions.
"""
import copy
import hashlib
import json
import math
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from . import adjudicator, sim_clock, resource_accounts

DATA = Path(__file__).resolve().parent / 'missions.json'
VERSION = 'teaching-rules-1'
ACTIONS = ('hold', 'move', 'fire', 'resupply', 'sabotage', 'repair', 'conceal', 'air_support', 'accept',
           'bombard','suppress','fortify','build_bridge','demolish','repair_equipment','recon','restore_comms','capture')
_VALIDATED_WORLD=ContextVar('gentactix_readonly_validated_world',default=None)
_PREPARED_LEGALITY=ContextVar('gentactix_prepared_legality_world',default=None)


@contextmanager
def _prepared_validation(world):
    """Internal detached command inspection, never physics/commit admission."""
    validate(world,allow_prepared=True)
    before=digest(world);token=_PREPARED_LEGALITY.set(world)
    try:yield
    finally:
        _PREPARED_LEGALITY.reset(token)
        if digest(world)!=before:raise ValueError('候选命令检查不得改变物理世界')


@contextmanager
def validation_scope(world):
    """Reuse validation only during one synchronous, read-only preparation.

    This is not a persistent cache or an execution context. A distinct candidate
    always validates normally; scope exit verifies the original input digest.
    """
    cached=_VALIDATED_WORLD.get()
    if not world or not world.get('mission') or cached is not None and cached[0] is world:
        yield
        return
    before=digest(world);token=_VALIDATED_WORLD.set([world,before,False])
    try:
        yield
    finally:
        _VALIDATED_WORLD.reset(token)
        try:unchanged=digest(world)==before
        except (ValueError,TypeError):unchanged=False
        if not unchanged:raise ValueError('只读命令校验期间战局输入发生变化，候选不得执行或提交')


def catalog(*, include_combined=False):
    values=json.loads(DATA.read_text(encoding='utf-8'))['missions']
    if include_combined:
        from . import combined_arms
        values+=combined_arms.catalog()
    return values


def definition(identity):
    if identity.startswith('CA-'):
        from . import combined_arms
        return combined_arms.definition(identity)
    for item in catalog():
        if item['id'] == identity:
            return copy.deepcopy(item)
    raise ValueError('未知局部想定')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def units(world):
    return [(team, u) for team in ('red', 'blue') for u in world[team + '_units']]


def distance(a, b):
    return adjudicator.distance_km((a['lat'], a['lng']), (b['lat'], b['lng']))


def move_budget(world, unit, destination=None):
    spec = world['mission']['definition']
    if spec.get('historical_calculation') or spec.get('historical_synthetic'):
        amount = unit['speed'] * sim_clock.duration_seconds(spec['time_step']) / 3600 / spec['geometry']['terrain_factor']
    else:
        amount = spec['rules']['move_km']
    from . import terrain_process
    return amount * (.5 if unit['logistics']['food'] < 4 else 1) * terrain_process.road_factor(world,unit,destination)


def initial(identity, *, configuration=None):
    if configuration is not None:
        from . import combined_arms
        spec = combined_arms.configure(identity, configuration)
    else:
        spec = definition(identity)
    return from_definition(spec)


def from_definition(spec):
    """Initialize a validated static or self-contained historical input definition."""
    world = copy.deepcopy(spec['initial_state'])
    world['mission'] = {'id': spec['id'], 'version': VERSION, 'definition_hash': digest(spec),
                        'definition': spec, 'turn': 0, 'status': 'active', 'winner': None,
                        'reason': '', 'progress': 0, 'network': 100, 'organization': 100,
                        'accepted': False, 'ledger': [], 'last_orders': []}
    sim_clock.initialize(world)
    from . import unit_participation
    unit_participation.initialize(world)
    from . import campaign_lifecycle
    campaign_lifecycle.initialize(world)
    from . import campaign_plan
    campaign_plan.initialize(world)
    if spec.get('combined_rules'):
        from . import combat_effects, suppression_state
        if 'suppression_state' in combat_effects.reference(world):
            for _,unit in units(world):unit['formation'].setdefault(suppression_state.FIELD,0)
        from . import movement_feedback, motion_state
        if movement_feedback.continuous(world):
            for _,unit in units(world):
                for field in motion_state.FIELDS:unit['formation'].setdefault(field,0)
    world['mission']['initial_hash'] = digest(world)
    validate(world)
    return world


def validate(world,*,allow_prepared=False):
    # This private scope validated this exact detached input on entry and
    # verifies its digest on exit. It never populates the normal-world cache.
    prepared=_PREPARED_LEGALITY.get()
    if prepared is not None and prepared is world:return True
    cached=_VALIDATED_WORLD.get()
    if world.get('formation_registry') and not allow_prepared:
        from . import formation_runtime
        formation_runtime.validate_world(world)
    if cached is not None and cached[0] is world and cached[2]:
        return True
    from . import formation_registry
    formation_registry.validate(world)
    if world.get('formation_registry'):
        from . import formation_continuity
        formation_continuity.validate(world)
    from . import split_supply,supply_schedule
    supply_schedule.validate_state(world)
    split_supply.validate_state(world)
    from . import support_dynamics
    support_dynamics.validate_state(world)
    from . import unit_participation
    unit_participation.validate_state(world)
    mission = world['mission']
    spec = mission['definition']
    if spec.get('combined_rules'):
        from . import combined_arms
        combined_arms.validate(world)
    if mission['version'] != VERSION or digest(spec) != mission['definition_hash']:
        raise ValueError('教学规则版本或想定摘要不一致')
    if str(mission['id']).startswith('HP-'):
        from . import phase_continuity, historical_operations
        expected = phase_continuity.definition(spec.get('phase_continuation'))
        historical_operations.validate_identity(world)
    elif str(mission['id']).startswith('HS-'):
        from . import synthetic_history, historical_operations
        expected = synthetic_history.from_binding(spec.get('historical_synthetic'))
        historical_operations.validate_identity(world)
    elif str(mission['id']).startswith('HO-'):
        from . import historical_operations
        expected = historical_operations.from_binding(spec.get('historical_calculation'))
        historical_operations.validate_identity(world)
    else:
        expected = definition(mission['id'])
    if 'synthetic_configuration' in spec and not spec.get('historical_synthetic'):
        from . import combined_arms
        expected = combined_arms.configure(mission['id'], spec['synthetic_configuration'])
    if spec != expected:
        raise ValueError('想定定义与已安装版本不一致，不能静默修改规则')
    from . import formation_parts
    formation_parts.validate(world)
    from . import campaign
    campaign.validate_state(world)
    from . import campaign_plan
    from . import campaign_lifecycle
    campaign_lifecycle.validate_state(world)
    campaign_plan.validate_state(world)
    from . import mission_termination
    if type(mission['turn']) is not int or mission['turn']<0 or (not mission_termination.objective_driven(spec) and mission['turn']>spec['deadline_turn']):
        raise ValueError('想定回合非法')
    if mission['status'] not in ('active', 'completed'):
        raise ValueError('目标状态不合法')
    baseline = {(t, u['name']): u for t, u in formation_registry.reference(world)}
    if {(t, u['name']) for t, u in units(world)} != set(baseline):
        raise ValueError('编组身份丢失或被替换')
    node_ids = [n.get('id') for n in world['supply_nodes']]
    if (any(not isinstance(identity, str) or not identity.strip() for identity in node_ids)
            or len(set(node_ids)) != len(node_ids)):
        raise ValueError('补给仓库身份缺失或重复')
    for node in world['supply_nodes']:
        if type(node.get('stock')) not in (int, float) or not math.isfinite(node['stock']) or node['stock'] < 0:
            raise ValueError('补给点库存非法')
    if [(n['id'], n['team']) for n in world['supply_nodes']] != [(n['id'], n['team']) for n in spec['initial_state']['supply_nodes']]:
        raise ValueError('补给点丢失')
    for field in ('network', 'organization'):
        if type(mission[field]) not in (int, float) or not math.isfinite(mission[field]) or not 0 <= mission[field] <= 100:
            raise ValueError('目标状态值非法')
    seen = set()
    for team, u in units(world):
        from . import supply
        supply.bound_node(world, team, u)
        if u['name'] in seen:
            raise ValueError('编组名称必须唯一')
        seen.add(u['name'])
        original = baseline[(team, u['name'])]
        if u.get('formation',{}).get('motorized') != original.get('formation',{}).get('motorized'):
            raise ValueError('单位初始机动方式不能在回合内改写')
        if any(u.get(k) != original.get(k) for k in ('type', 'speed', 'attack_range', 'supply_node_id','ground_control_radius_km')):
            raise ValueError('固定编组的兵种、性能或补给绑定被修改')
        if any(type(u.get(k)) not in (int, float) or not math.isfinite(u[k]) for k in ('lat', 'lng')):
            raise ValueError('单位坐标非法')
        if u['personnel']['committed'] != original['personnel']['committed'] or [(e['name'], e['committed']) for e in u['equipment']] != [(e['name'], e['committed']) for e in original['equipment']]:
            raise ValueError('初始投入基数被修改')
        p = u['personnel']
        if any(type(p[k]) is not int or p[k] < 0 for k in ('committed', 'current', 'casualties', 'noncombat_losses')):
            raise ValueError('人员计数非法')
        if p['committed'] != p['current'] + p['casualties'] + p['noncombat_losses']:
            raise ValueError('人员账不守恒')
        from . import combat_effects
        combat_effects.validate_personnel(p)
        for e in u['equipment']:
            if any(type(e[k]) is not int or e[k] < 0 for k in ('committed', 'operational', 'damaged', 'destroyed')):
                raise ValueError('装备计数非法')
            if e['committed'] != e['operational'] + e['damaged'] + e['destroyed']:
                raise ValueError('装备账不守恒')
        for key in ('food', 'ammo'):
            if type(u['logistics'][key]) not in (int, float) or not math.isfinite(u['logistics'][key]) or not 0 <= u['logistics'][key] <= 100:
                raise ValueError('补给库存非法')
        if distance(u, spec['map_center']) > spec['map_radius_km']:
            raise ValueError('单位离开局部想定边界')
    if not allow_prepared and cached is not None and cached[0] is world:
        cached[2]=True
    return True


def available_actions(world):
    profile = world['mission']['definition']['profile']
    if profile=='combined':
        result=['hold','move','fire','resupply','conceal','air_support',
            'bombard','suppress','fortify','build_bridge','demolish','repair_equipment','recon','restore_comms']
        from . import campaign
        if campaign.definition(world) and campaign.definition(world)['surrender']['enabled']:result.append('capture')
        return result
    extra = {'rail': ['sabotage', 'repair'], 'underground': ['conceal'],
             'air': ['air_support'], 'reception': ['accept']}.get(profile, [])
    actions = ['hold', 'move', 'fire', 'resupply'] + extra
    if profile == 'reception':
        after_ceasefire = world['mission']['turn'] >= world['mission']['definition']['ceasefire_turn']
        actions.remove('fire' if after_ceasefire else 'accept')
    return actions


ORDER_GUIDANCE = (
    'move附lat/lng，fire附target（敌方单位名）；其余命令不附坐标。'
    'move不能超过max_move_km，food<4时上限减半；fire目标须在本轮开始时attack_range米以内且ammo>=3，每次扣3弹药工作单位。'
    '不要将移动后坐标用于本轮射击距离。resupply增加本单位库存但仅连通时有效。')


def order_guidance(world):
    if world['mission']['definition'].get('combined_rules'):
        from . import combined_arms
        guidance = combined_arms.GUIDANCE
        if world['mission']['definition'].get('fire_accounting'):
            guidance += '本配置采用classified-indirect-1：通用工作量只代表fire直射轻武器弹药；bombard/suppress仅按实际分类炮弹消耗，不额外扣直射工作量。无炮弹、无可用炮兵或无人员仍不能炮击；不改变装填、目标、射程或运输约束。'
        if world['combined_arms']['bridge'].get('crossing_model'):
            from . import crossings
            guidance = crossings.instruction(world) + guidance.split('。',1)[1]
        if not world['mission']['definition']['combined_rules'].get('bridge_enabled', True):
            guidance = '本场景未绑定桥梁约束，不使用施工、拆除或固定桥梁经线限制。' + guidance.split('。',1)[1]
        if world['mission']['definition'].get('historical_calculation'):
            guidance = '历史单位身份固定，当前数量与性能按已声明计算参数运行，不能冒充史实实到或武器标定。' + guidance
        if world['mission']['definition'].get('campaign_definition'):
            guidance += '本局存在分批入场；等待部队只能hold/resupply/restore_comms/recon，不能提前交战或被选为目标。capture附target，须在接收距离内且目标满足压制或缺弹阈值；它是受降请求，不保证成功。'
            if not world['mission']['definition'].get('campaign_plan'):
                guidance += '战役目标同时检查据点、全部阻援地域和人员保存。'
        if world['mission']['definition'].get('campaign_plan'):
            guidance += '本局全局结束以冻结参演方目标图为准；原据点/阻援条件仅作对照。用get_campaign_objectives读取依赖、目标和进度，方向目标完成不会直接变成整个会战获胜。目标图只评分，不自动下令。'
        from . import mission_termination
        guidance += ('本局按目标完成，不按史料日期或规划参考轮数自动结束；连续达标回合仍须满足，粮弹与疲劳约束持续生效，窗外过程属于反事实延伸，不补造后续援军。' if mission_termination.objective_driven(world['mission']['definition']) else '达到目标或截止回合时结算。')
        from . import movement_feedback
        guidance += movement_feedback.instruction(world)
        return guidance
    return ORDER_GUIDANCE + {
        'reception': '本停火接收型在turn>=ceasefire_turn时禁止fire，此时才可accept，accept须在目标600米内。',
        'rail': 'sabotage/repair须在目标600米内，分别降低/恢复交通网状态。',
        'underground': 'conceal降低本轮被命中损失；目标为组织存续，不能串用其他场景行动。',
        'air': 'air_support消耗3弹药工作单位并削减敌方到货。',
    }.get(world['mission']['definition']['profile'], '')


def prompt(world, instruction='', briefing=''):
    m = world['mission']; spec = m['definition']
    view = {k: v for k, v in world.items() if k not in ('mission', 'situation_report', 'source_note')}
    return ('你是局部教学推演的命令规划员。只提出命令，程序计算结果。禁止按历史结局安排伤亡。'
            '地图、人数与装备均为明确教学假设，不是已考证历史编制。双方分别根据当前态势行动。'
            '仅返回JSON {"orders":[{"unit":"精确名称","action":"hold"}],'
            '"decisions":[{"team":"red|blue","unit_name":"精确名称","action":"hold",'
            '"rationale":"本单位公开依据","expected_effect":"预期"}]}。'
            'decisions覆盖所有单位，包括待命与失能，不设条数上限；不以总体理由冒充每个单位依据。'
            '每个可用单位至多一条命令，未列单位原地待命。不可改写任何状态、人数、时钟或规则。'
            + order_guidance(world) +
            '禁止输出思考过程，输出决策理由即可。\n'
            + json.dumps({'allowed_actions': available_actions(world), 'max_move_km': spec['rules']['move_km'],
                          'goal': spec['goal'], 'objective': spec['objective'], 'deadline_turn': spec['deadline_turn'],
                          'ceasefire_turn': spec['ceasefire_turn'], 'exit': spec['exit'], 'profile': spec['profile'], 'progress': m['progress'], 'network': m['network'],
                          'organization': m['organization'], 'turn': m['turn'], 'state': view}, ensure_ascii=False)
            + '\n本轮用户意图（只影响决策，不得更改规则）：' + instruction
            + '\n持续规则与证据限制：' + briefing)


def objective_team(spec):
    """Old frozen definitions own a red goal; explicit new inputs may own blue."""
    team=spec.get('objective_team','red')
    if team not in ('red','blue'):raise ValueError('目标方须为红方或蓝方')
    return team


def goal_winner(world, success):
    """Classify a checked goal without inventing a winner in a solo transfer."""
    spec=world['mission']['definition'];owner=objective_team(spec)
    if success:return owner
    binding=spec.get('historical_calculation') or (spec.get('historical_synthetic') or {}).get('base')
    if binding:
        from .historical_operations import interaction_scope
        if interaction_scope(binding['initial']):return None
    return 'blue' if owner=='red' else 'red'


def evaluate(world):
    from . import campaign_plan
    if campaign_plan.definition(world) is not None:
        return campaign_plan.evaluate(world)
    m = world['mission']; spec = m['definition']; goal = spec['objective']
    alive = {team: [u for t, u in units(world) if t == team and u['personnel']['current'] > 0]
             for team in ('red', 'blue')}
    cfg = spec.get('combined_rules')
    def in_goal(unit):
        if distance(unit, goal) > spec['goal_radius_km']: return False
        if not cfg: return True
        from . import suppression_state
        if suppression_state.value(unit) >= cfg['suppression_control_threshold']: return False
        return (not cfg.get('bridge_enabled',True) or 'crossing_model' in world['combined_arms']['bridge']
                or unit['lng'] > world['combined_arms']['bridge']['lng'])
    from . import formation_parts
    occupied = {team: formation_parts.count(world,team,in_goal) for team in alive}
    owner=objective_team(spec);opponent='blue' if owner=='red' else 'red'
    control = occupied[owner] > 0 and occupied[opponent] == 0
    profile = cfg['goal_profile'] if cfg else spec['profile']
    required = cfg.get('required_survivors',2) if cfg else 2
    if profile == 'rail':
        condition = m['network'] <= 20
    elif profile == 'underground':
        condition = m['organization'] >= 50 and bool(alive[owner])
    elif profile == 'delay':
        condition = formation_parts.count(world,owner,lambda u:True) >= required and not any(distance(u, spec['exit']) <= .6 for u in alive[opponent])
    elif profile == 'breakout':
        condition = formation_parts.count(world,owner,lambda u:distance(u,spec['exit'])<=.6,whole=True) >= required
    elif profile == 'crossing':
        condition = (formation_parts.count(world,owner,lambda u:(u.get('crossing',{}).get('status')=='completed' or formation_parts.prepositioned(world,u)) and in_goal(u),whole=True) >= required
                     and occupied[opponent]==0)
    elif profile == 'reception':
        condition = m['accepted']
    else:
        condition = control
    from . import campaign
    operation = campaign.assess(world)
    if operation is not None:
        world['campaign']['objective'] = operation
        delay_goal=campaign.delay_assess(world)
        condition = delay_goal['condition'] if delay_goal is not None else all(operation.values())
    m['progress'] = m['progress'] + 1 if condition else 0
    m['metrics'] = {'red_available': sum(u['personnel']['current'] for u in alive['red']),
                    'blue_available': sum(u['personnel']['current'] for u in alive['blue']),
                    'red_in_goal': occupied['red'], 'blue_in_goal': occupied['blue'],
                    'network': m['network'], 'organization': m['organization'], 'condition': condition}
    if operation is not None:m['metrics']['campaign'] = dict(operation)
    from . import mission_termination
    success,terminal=mission_termination.outcome(spec,m['turn'],m['progress'],condition,bool(alive[owner]),
        wait_until_deadline=operation is not None or profile in ('underground','delay'))
    if terminal:
        m.update(status='completed', winner=goal_winner(world,success),
                 reason='程序目标达成' if success else (('红方' if owner=='red' else '蓝方')+'无可用人员' if not alive[owner] else '截止回合目标未达成'))
    return m


def validate_orders(before, orders, time_step,*,validator=None):
    """Validate command legality without producing a simulated candidate state."""
    (validator or validate)(before)
    if before['mission']['status'] != 'active':
        raise ValueError('本局已结束，请重新初始化或建立分支')
    spec = before['mission']['definition']
    if sim_clock.duration_seconds(time_step) != sim_clock.duration_seconds(spec['time_step']):
        raise ValueError('固定局部想定必须使用其版本规定的回合跨度')
    if not isinstance(orders, list) or len(orders) > len(units(before)):
        raise ValueError('命令必须为数组且不超过编组数')
    old = {u['name']: (team, u) for team, u in units(before)}
    commands = {}
    for order in orders:
        if not isinstance(order, dict) or order.get('unit') not in old:
            raise ValueError('命令引用未知编组')
        name = order['unit']; team, u = old[name]; action = order.get('action')
        from . import campaign
        campaign.check_order(before,order)
        from . import crossings
        crossings.check_order(before,order)
        from . import terrain_process
        terrain_process.check_order(before,order)
        from . import unit_participation
        unit_participation.check_order(before,order)
        if name in commands or u['personnel']['current'] <= 0 or action not in available_actions(before):
            raise ValueError('重复命令、无可用人员或当前规则不支持该行动')
        if spec.get('combined_rules'):
            from . import combined_arms
            combined_arms.validate_order(before,order)
        if action == 'move':
            pos = {k: order.get(k) for k in ('lat', 'lng')}
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in pos.values()):
                raise ValueError('移动坐标非法')
            from . import movement_feedback
            limit = movement_feedback.command_budget(before,u,pos)
            from . import ferries
            persistent_goal=movement_feedback.continuous(before) and 'intent_id' in order
            if (not persistent_goal and ferries.ground_distance(before,u,pos) > limit + .001
                    or distance(pos, spec['map_center']) > spec['map_radius_km']):
                raise ValueError('移动超过本轮机动或地图边界')
        if action == 'air_support' and order.get('target'):
            target = old.get(order['target'])
            if not target or target[0] == team or target[1]['personnel']['current'] <= 0:
                raise ValueError('航空打击目标无效')
        if action == 'fire' and not spec.get('combined_rules'):
            target = old.get(order.get('target'))
            if not target or target[0] == team or target[1]['personnel']['current'] <= 0:
                raise ValueError('射击目标无效')
            if distance(u, target[1]) * 1000 > u['attack_range'] + 1 or u['logistics']['ammo'] < 3:
                raise ValueError('射击目标超距或弹药不足')
            if spec['profile'] == 'reception' and before['mission']['turn'] >= spec['ceasefire_turn']:
                raise ValueError('停火后禁止射击')
        if action in ('sabotage', 'repair', 'accept') and distance(u, spec['objective']) > .6:
            raise ValueError('任务行动须在目标600米内')
        if action == 'accept' and before['mission']['turn'] < spec['ceasefire_turn']:
            raise ValueError('尚未到达本想定的接收窗口')
        if action == 'air_support' and not order.get('target') and u['logistics']['ammo'] < 3:
            raise ValueError('支援资源不足')
        commands[name] = copy.deepcopy(order)
    return commands


def advance(before, orders, time_step):
    """Legacy teaching executor and independent oracle for native-engine tests."""
    commands = validate_orders(before, orders, time_step)
    if before['mission']['definition'].get('combined_rules'):
        raise ValueError('团级多兵种模型须由AFSIM执行，不支持Python回退')
    if any(o['action']=='air_support' and o.get('target') for o in commands.values()):
        raise ValueError('目标航空打击须由AFSIM后台执行，不能回退旧教学结算')
    spec = before['mission']['definition']
    old = {u['name']: (team, u) for team, u in units(before)}
    candidate = copy.deepcopy(before); m = candidate['mission']; m['turn'] += 1
    candidate['current_time'], candidate['simulation_clock'] = sim_clock.target(before, time_step)
    sim_clock.enforce_step(before, candidate, time_step)
    new = {u['name']: (team, u) for team, u in units(candidate)}
    candidate['engagements'] = []
    geom = adjudicator.adjudicate(before, time_step, params=spec['geometry'])
    supply = {u['name']: u['supply'] for u in geom['units']}
    damage = {name: 0 for name in new}; logs = []; network_delta = 0
    pressure = {team: any(old[n][0] != team and o['action'] == 'air_support' for n, o in commands.items())
                for team in ('red', 'blue')}
    for name, (team, u) in new.items():
        prior = old[name][1]; action = commands.get(name, {}).get('action', 'hold')
        if prior['personnel']['current'] <= 0:
            continue
        from .supply import bound_node
        depot = bound_node(candidate, team, u)
        delivered = 0
        if supply.get(name) == '未切断' and depot['stock'] > 0:
            rate = 8 if action == 'resupply' else 2
            if pressure[team]: rate //= 2
            if spec['profile'] == 'rail' and team == 'blue' and before['mission']['network'] <= 20: rate = 0
            delivered = min(rate, depot['stock'], 100 - u['logistics']['food'], 100 - u['logistics']['ammo'])
            depot['stock'] -= delivered
        food_cost = resource_accounts.food_demand(action)
        ammo_cost = 3 if action in ('fire', 'air_support') else 0
        u['logistics']['food'] = max(0, prior['logistics']['food'] + delivered - food_cost)
        u['logistics']['ammo'] = max(0, prior['logistics']['ammo'] + delivered - ammo_cost)
        if u['logistics']['food'] == 0:
            lost = min(2, u['personnel']['current'])
            u['personnel']['current'] -= lost; u['personnel']['noncombat_losses'] += lost
        if action == 'move':
            u.update({k: commands[name][k] for k in ('lat', 'lng')})
        elif action == 'fire':
            target = commands[name]['target']; victim = old[target][1]
            cover = .4 if commands.get(target, {}).get('action') == 'conceal' else spec['rules']['cover']
            damage[target] += max(1, round(spec['rules']['damage'] * prior['personnel']['current'] / prior['personnel']['committed'] * cover))
            candidate['engagements'].append({'attacker': name, 'attacker_team': team,
                'attacker_pos': [prior['lat'], prior['lng']], 'lat': victim['lat'], 'lng': victim['lng'],
                'type': '教学规则交战', 'description': '根据固定系数计算，不代表历史杀伤率'})
        elif action == 'sabotage': network_delta -= 40
        elif action == 'repair': network_delta += 25
        elif action == 'accept': m['accepted'] = team == 'red' or m['accepted']
        logs.append({'unit': name, 'action': action, 'supply_status': supply.get(name, '未知'),
                     'source_node_id': depot['id'],
                     'delivery': delivered, 'food_spent': min(food_cost, prior['logistics']['food'] + delivered),
                     'ammo_spent': ammo_cost, 'food_after': u['logistics']['food'], 'ammo_after': u['logistics']['ammo']})
    m['network'] = max(0, min(100, m['network'] + network_delta))
    # Resolve damage simultaneously, so JSON order cannot decide who fires first.
    for name, amount in damage.items():
        u = new[name][1]; loss = min(amount, u['personnel']['current'])
        u['personnel']['current'] -= loss; u['personnel']['casualties'] += loss
        e = u['equipment'][0]; destroyed = min(e['operational'], loss // 8)
        e['operational'] -= destroyed; e['destroyed'] += destroyed
        u['hp'] = round(100 * u['personnel']['current'] / u['personnel']['committed'], 2)
        u['supply'] = min(u['logistics']['food'], u['logistics']['ammo'])
    if spec['profile'] == 'underground':
        hidden = sum(o['action'] == 'conceal' and old[n][0] == 'red' for n, o in commands.items())
        m['organization'] = max(0, min(100, m['organization'] - 15 + 5 * hidden))
    m['ledger'] = logs; m['last_orders'] = list(commands.values())
    evaluate(candidate); validate(candidate)
    return candidate


def report(world):
    m = world['mission']
    delivery=sum(x['delivery'] for x in m['ledger'])
    supply=(f"粮食到货{sum(x['food_received'] for x in m['ledger']):g}、弹药到货{sum(x['ammo_received'] for x in m['ledger']):g}工作量，运输质量当量{delivery:g}。"
            if m['definition'].get('supply_distribution') else f"补给到货合计{delivery:g}工作单位。")
    graph=world.get('campaign_plan')
    progress=(f"红方总目标连续达标{graph['side_progress']['red']}轮，蓝方总目标连续达标{graph['side_progress']['blue']}轮。"
              if graph else f"目标连续满足{m['progress']}轮。")
    return (f"本轮执行{len(m['last_orders'])}项命令，"+supply+
            f"红方可用人员{m['metrics']['red_available']}人，蓝方{m['metrics']['blue_available']}人。"+
            progress + (m['reason'] if m['status'] == 'completed' else '目标尚未结束。')
            + '人员、库存与目标由教学规则计算；参数未作史实校准。')


def counterfactual(before, factual, orders, time_step):
    """Same fixed pre-state and coefficients, only the order set changes."""
    alternative = advance(before, orders, time_step)
    return compare_states(before,factual,alternative,orders)


def compare_states(before, factual, alternative, orders):
    """Summarize already computed states, without executing either branch."""
    def measures(world):
        result = {'目标连续满足轮数': world['mission']['progress'],
                  '交通完好度': world['mission']['network'], '组织存续值': world['mission']['organization']}
        if world.get('campaign_plan'):
            graph=world['campaign_plan'];definition=world['mission']['definition']['campaign_plan']
            result['会战目标图已结算']=int(graph['resolution']!='active')
            for team,label in (('red','红方'),('blue','蓝方')):
                result[label+'方向目标已达成数']=sum(graph['nodes'][n['id']]['status']=='completed' for n in definition['nodes'] if n['team']==team)
                result[label+'总目标满足']=int(graph['outcomes'][team])
                result[label+'总目标连续达标回合']=graph['side_progress'][team]
        for team, label in (('red', '红方'), ('blue', '蓝方')):
            roster = world[team + '_units']
            result[label + '可用人员'] = sum(u['personnel']['current'] for u in roster)
            result[label + '可用装备'] = sum(e['operational'] for u in roster for e in u['equipment'])
            from . import formation_parts
            result[label + '粮食库存'] = sum(u['logistics']['food']*formation_parts.scale(u) for u in roster)
            result[label + '弹药库存'] = sum(u['logistics']['ammo']*formation_parts.scale(u) for u in roster)
            if world.get('combined_arms',{}).get('bridge',{}).get('crossing_model'):
                result[label+'完成渡运编组']=sum(u.get('crossing',{}).get('status')=='completed' for u in roster)
                result[label+'当前任务已服务工作量']=round(sum(u.get('crossing',{}).get('served_work',0) for u in roster),6)
            if factual.get('combined_arms') and alternative.get('combined_arms'):
                from . import motion_state
                for key,title in (('fuel_liters','地面燃油(升)'),('spares','备件'),('shells','炮弹'),('aa_rounds','防空弹药')):
                    result[label+title]=sum(motion_state.fuel_value(u) if key=='fuel_liters' and motion_state.present(u) else u['formation'][key] for u in roster)
                result[label+'平均疲劳']=round(sum(motion_state.fatigue_value(u) if motion_state.present(u) else u['formation']['fatigue'] for u in roster)/len(roster),2)
                result[label+'平均压制']=round(sum(u['formation']['suppression'] for u in roster)/len(roster),2)
            if factual.get('air_operations') and alternative.get('air_operations'):
                pool=world['air_operations']['assets'][team]
                for key,title in (('ready','可用飞机'),('destroyed','损失飞机'),('sorties','累计架次'),('ordnance','航空弹药'),('fuel','航空燃油')):
                    result[label+title]=pool[key]
        if factual.get('combined_arms') and alternative.get('combined_arms'):
            bridge=world['combined_arms']['bridge']
            for k,label in (('progress','桥梁施工进度'),('integrity','桥梁完整度'),('used','桥梁当轮使用容量')):result[label]=bridge[k]
            if bridge.get('crossing_model'):
                for k,label in (('used_work','本轮编组渡运工作量'),('cargo_work','本轮物资渡运工作量')):result[label]=bridge.get('crossing_receipt',{}).get(k,0)
        return result
    a, b = measures(factual), measures(alternative)
    return {'mode': 'controlled_mission', 'read_only': True,
            'before_hash': digest(before), 'definition_hash': before['mission']['definition_hash'],
            'metrics': [{'metric': k, 'factual': a[k], 'alternative': b[k], 'delta': b[k]-a[k]} for k in a],
            'orders': copy.deepcopy(orders), 'alternative': alternative,
            'scope': '从同一决策前快照按同一版本教学规则重算，仅改变命令。',
            'limitations': ['固定系数下的局部教学反事实；不是历史因果效应或实战杀伤率估计。']}
