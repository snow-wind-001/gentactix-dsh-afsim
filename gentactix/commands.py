"""Wargame orders and receipts. No model transport, Agent scheduler or live writes.

All transitions return detached values. The application owns confirmation and
atomic commits; DSH supplies proposals against the same pre-turn observation.
"""
import copy
import hashlib
import json
import math
import re
import uuid
from functools import wraps

from . import adjudicator, adjudication_lib, missions
from .state import extract_lat_lng, get_unit_field

VERSION = 1
ACTIVE = ('queued', 'executing', 'blocked')
STATUSES = (*ACTIVE, 'completed', 'cancelled', 'expired')
PREPARATION_ACTIONS = ('hold', 'recon', 'restore_comms')
DRAFT_FIELDS = ('id','unit_id','action','duration','destination','target_id','air_pool','end_turn','participation')
IDENTITY_VERSION = 'command-identity-origin-1'
BRANCH_POLICY = 'preserve_semantic_ids_fresh_native_sessions'


def identity_namespace(session):
    """Semantic actor identity can survive a branch; SDK identity never does.

    A branch continues the original command-ID generator so recorded conversion
    handoffs can still be independently replayed. HTTP and Native session IDs
    continue to use the current session, not this semantic namespace.
    """
    value=session.get('command_identity_origin');origin=session.get('branch_origin') or {}
    if not isinstance(origin,dict):raise ValueError('分支来源须为对象')
    if value is None:
        if origin.get('identity_policy')==BRANCH_POLICY:raise ValueError('分支缺少命令身份来源')
        return session['id'],session.get('role_epoch',0)
    if (not isinstance(value,dict) or set(value)!={'version','session_id','role_epoch'}
            or value.get('version')!=IDENTITY_VERSION or not isinstance(value.get('session_id'),str)
            or not re.fullmatch('[a-f0-9]{12}',value['session_id'])
            or type(value.get('role_epoch')) is not int or value['role_epoch']<0
            or not isinstance(origin,dict) or origin.get('identity_policy')!=BRANCH_POLICY
            or origin.get('command_identity_origin')!=value
            or not re.fullmatch('[a-f0-9]{12}',str(origin.get('session_id','')))
            or origin['session_id']==session['id']
            or type(origin.get('source_role_epoch')) is not int
            or origin['source_role_epoch']<value['role_epoch']
            or session.get('role_epoch',0)!=origin['source_role_epoch']+1):
        raise ValueError('分支命令身份来源与运行会话不一致')
    return value['session_id'],value['role_epoch']


def validate_identity_origin(session):
    identity_namespace(session)
    if session.get('command_identity_origin') is None:return
    # Only the current durable state must be after the fork. Historical
    # handoff replay intentionally projects an older command revision while
    # retaining the same immutable semantic namespace.
    origin=session['branch_origin'];cs=session.get('command_state') or {}
    for key,current in [('source_command_revision',cs.get('revision',-1)-1),
            ('source_organization_revision',(session.get('force_organization') or {}).get('revision',0)),
            ('conversion_revision',len((session.get('war_state',{}).get('formation_registry') or {}).get('transactions',[]))),
            ('turn',session.get('turn_count',0))]:
        if type(origin.get(key)) is not int or not 0<=origin[key]<=current:
            raise ValueError('分支身份接续的来源修订或回合非法')


def actor_identity(session,team,name,predecessor=''):
    namespace,epoch=identity_namespace(session)
    suffix=':after:'+predecessor if predecessor else ''
    return uuid.uuid5(uuid.NAMESPACE_URL,f'gentactix:{namespace}:{epoch}:{team}:{name}{suffix}').hex


def readonly_validation(function):
    # Resolve the scope at call time: mission imports can reach this module
    # before missions.py has finished loading its function definitions.
    @wraps(function)
    def wrapped(session,*args,**kwargs):
        with missions.validation_scope(session.get('war_state')):
            return function(session,*args,**kwargs)
    return wrapped


def validate_duration(order, created_turn):
    duration = order.get('duration', 'next')
    if duration not in ('next', 'until_arrived', 'until_turn'):
        raise ValueError('命令持续方式非法')
    if duration == 'until_arrived' and order.get('action') != 'move':
        raise ValueError('到达前持续仅支持移动')
    if duration == 'until_turn':
        if order.get('action') not in PREPARATION_ACTIONS:
            raise ValueError('按回合持续仅支持待命、侦察和恢复联络')
        end = order.get('end_turn')
        if type(created_turn) is not int or type(end) is not int or not created_turn < end <= created_turn + 1000:
            raise ValueError('持续命令end_turn须为未来1至1000回合内的整数截止回合（含该回合）')
    elif 'end_turn' in order:
        raise ValueError('只有until_turn持续命令可以指定end_turn')


class Conflict(ValueError):
    """The user must refresh/reconcile a stale command revision."""


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    allow_nan=False).encode()).hexdigest()


def world_version(session):
    return fingerprint([session['id'], session.get('role_epoch', 0),
                        session.get('turn_count', 0), session.get('war_state')])


def iter_units(world):
    for team in ('red', 'blue'):
        for unit in (world or {}).get(team + '_units', []):
            yield team, unit


def name_of(unit):
    return str(get_unit_field(unit, 'name', '名称', '单位名称', 'unit_name') or '')


def available(unit):
    current = (unit.get('personnel') or {}).get('current')
    if type(current) in (int, float):
        return current > 0
    hp = get_unit_field(unit, 'hp', '兵力', '兵力值')
    return hp is None or (type(hp) in (int, float) and hp > 0)


def position(value):
    if not isinstance(value, dict) or set(value) != {'lat', 'lng'}:
        raise ValueError('目的地必须是地图选定的lat/lng对象')
    lat, lng = value['lat'], value['lng']
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in (lat, lng)) \
            or abs(lat) > 90 or abs(lng) > 180:
        raise ValueError('目的地坐标非法')
    return {'lat': float(lat), 'lng': float(lng)}


def unit_position(unit):
    lat, lng = extract_lat_lng(unit)
    return position({'lat': lat, 'lng': lng})


def known_position(unit):
    try:
        return unit_position(unit) if unit else None
    except ValueError:
        return None


def distance(a, b):
    return adjudicator.distance_km((a['lat'], a['lng']), (b['lat'], b['lng']))


def towards(origin, destination, budget):
    """A deliberate step along the requested great-circle line, not pathfinding."""
    length = distance(origin, destination)
    if length <= budget or length < .000001:
        return copy.deepcopy(destination)
    lat1, lng1, lat2, lng2 = map(math.radians,
                                (origin['lat'], origin['lng'], destination['lat'], destination['lng']))
    bearing = math.atan2(math.sin(lng2-lng1)*math.cos(lat2),
                         math.cos(lat1)*math.sin(lat2)-math.sin(lat1)*math.cos(lat2)*math.cos(lng2-lng1))
    def point(angle):
        lat = math.asin(math.sin(lat1)*math.cos(angle)+math.cos(lat1)*math.sin(angle)*math.cos(bearing))
        lng = lng1 + math.atan2(math.sin(bearing)*math.sin(angle)*math.cos(lat1),
                                math.cos(angle)-math.sin(lat1)*math.sin(lat))
        return {'lat': math.degrees(lat), 'lng': (math.degrees(lng)+540) % 360-180}
    angle=budget/6371
    target=point(angle)
    # The authoritative local metric uses degrees/km, while projection follows
    # a great circle. Clip along that same route rather than exceed the local
    # budget by metres or relax validation for all movement commands.
    if distance(origin,target)>budget:
        low,high=0,angle
        for _ in range(32):
            middle=(low+high)/2
            if distance(origin,point(middle))<=budget:low=middle
            else:high=middle
        target=point(low)
    return target


def state(session):
    stored = session.get('command_state')
    result = copy.deepcopy(stored) if stored is not None else {
        'version': VERSION, 'revision': 0, 'control_team': 'red', 'director': False,
        'no_fire': False, 'intent': '', 'registry': [], 'orders': [], 'archive': [],
        'receipts': [], 'batches': {}, 'unit_agents': []}
    if result.get('version') != VERSION:
        raise ValueError('命令存档版本不支持，原文件应保留')
    known = {(u['team'], u['name']): u for u in result['registry']}
    counts = {}
    names = {}
    for team, unit in iter_units(session.get('war_state')):
        key = (team, name_of(unit))
        counts[key] = counts.get(key, 0) + 1
        names[key[1]] = names.get(key[1], 0) + 1
    for entry in result['registry']:
        entry['present'] = False
    for (team, name), count in counts.items():
        key = (team, name)
        if key not in known or known[key].get('retired'):
            predecessor = known[key]['id'] if key in known else ''
            identity = actor_identity(session,team,name,predecessor)
            entry = {'id': identity, 'team': team, 'name': name}
            result['registry'].append(entry)
            known[key] = entry
        known[key].update(present=True, ambiguous=count != 1 or names[name] != 1 or not name)
    return result


def resolve_units(session, cs=None):
    cs = cs or state(session)
    index = {(e['team'], e['name']): e for e in cs['registry']}
    return {index[(t, name_of(u))]['id']: (index[(t, name_of(u))], u)
            for t, u in iter_units(session.get('war_state'))}


def move_budget(session, unit, team, destination=None):
    world = session['war_state']
    if world.get('mission'):
        from . import movement_feedback
        return movement_feedback.command_budget(world,unit,destination)
    spec = adjudication_lib.resolve(scenario_text=session.get('scenario_input', ''),
                                    battle=session.get('battle_choice'))
    verdict = adjudicator.adjudicate(copy.deepcopy(world), session['time_step'],
        turn=session.get('turn_count', 0), params=spec.explicit)
    match = next((u for u in verdict['units'] if u['name'] == name_of(unit) and u['team'] == team), None)
    return float(match['reach_km']) if match else 0


def rule_version(session):
    mission = session['war_state'].get('mission')
    if mission:
        return mission['version'] + ':' + mission['definition_hash']
    spec = adjudication_lib.resolve(scenario_text=session.get('scenario_input', ''), battle=session.get('battle_choice'))
    return adjudicator.ADJUDICATOR_VERSION + ':' + fingerprint([spec.name, spec.explicit, session['time_step']])


def capabilities(session, unit, team):
    world = session['war_state']
    actions = missions.available_actions(session['war_state']) if session['war_state'].get('mission') else ['hold', 'move']
    if session['war_state'].get('combined_arms'):
        from . import combined_arms,campaign
        actions=combined_arms.actions(session['war_state'],unit,team)
        if not any(other_team!=team and available(other) and campaign.release_seconds(session['war_state'],other)==0 for other_team,other in iter_units(session['war_state'])):
            actions=[a for a in actions if a not in ('fire','bombard','suppress','air_support','capture')]
    if session.get('execution_backend')=='afsim' and 'air_support' in actions:
        from backend import afsim_air
        from . import air_assets
        air=afsim_air.state(session['war_state'])
        explicit=air_assets.world_definition(session['war_state']) is not None
        if not air or (not air_assets.available(session['war_state'],team) if explicit else
                air['assets'][team]['ready'] < afsim_air.CONFIG['package'] or air['assets'][team]['ordnance'] < afsim_air.CONFIG['package'] or air['assets'][team]['fuel'] < afsim_air.CONFIG['package']*afsim_air.CONFIG['fuel_per_aircraft']):
            actions=[a for a in actions if a!='air_support']
    if not session['war_state'].get('mission') and known_position(unit) is None:
        actions = ['hold']
    writable = session.get('simulation_mode', 'open') == 'open'
    terminal = session['war_state'].get('mission', {}).get('status') == 'completed'
    reason = '历史回放仅供查看，请创建开放分支' if not writable else '本局已结算' if terminal else \
        '单位已失去行动能力' if not available(unit) else ''
    weapons={}
    if session['war_state'].get('combined_arms'):
        weapons={'weapon_limits_m':combined_arms.weapon_limits(session['war_state'],unit),
                 'weapon_warnings':combined_arms.weapon_warnings(session['war_state'],unit)}
        process=campaign.definition(session['war_state'])
        if process is not None:
            weapons['arrival']={'status':'staging' if campaign.release_seconds(session['war_state'],unit)>0 else 'active',
                'not_before':campaign.scheduled_time(process,unit,world=session['war_state']),'source':'model_schedule',
                **campaign.schedule_metadata(process,unit,world=session['war_state'])}
            if process['surrender']['enabled']:weapons['capture_range_m']=process['surrender']['range_m']
    from . import air_assets
    if air_assets.world_definition(session['war_state']) is not None:
        weapons['air_pools']=air_assets.available(session['war_state'],team)
    from . import unit_participation
    if unit_participation.supported(world):
        row=unit_participation.unit_view(world,unit,team)
        weapons['participation']={**row,'enabled':not reason and available(unit) and row['status']!='staging',
            'choices':(['withdraw'] if row['status'] in ('deployed','withdrawing') else ['reenter']),
            'source':'host_checked_movement'}
        from . import operation_boundary
        if operation_boundary.configuration(world):weapons['operation_routes']=operation_boundary.choices(world,unit,team)
    from . import movement_feedback
    motion=movement_feedback.limits(world,unit) if world.get('mission') else None
    if motion is not None:weapons['movement_constraints']=motion
    return {'actions': actions, 'enabled': not reason, 'reason': reason, **weapons,
            'move_km': move_budget(session, unit, team), 'movement_basis': ('有效陆地预算：扣通信、疲劳、压制、兵力及燃油约束；道路按目的地另核，渡运还须排队与通路回执，无DEM' if motion is not None else '基础机动预算；已登记直线道路按目的地调整，有限障碍线约束通路；无DEM' if world.get('mission',{}).get('definition',{}).get('terrain_model') else '几何估计，未计算道路通行和高程遮挡'),
            'unsupported': [] if session['war_state'].get('mission') else ['fire', 'resupply', 'recon', 'fortify']}


def view(session):
    cs = state(session)
    roster = []
    from . import resource_readiness,combat_effects
    fire_reference=combat_effects.reference(session['war_state']) if session['war_state'].get('combined_arms') else None
    for identity, (entry, unit) in resolve_units(session, cs).items():
        try:
            pos = unit_position(unit)
        except ValueError:
            pos = None
        roster.append({**entry, 'position': pos, 'type': unit.get('type'),
            'hp': unit.get('hp'), 'personnel': copy.deepcopy(unit.get('personnel')),
            'equipment': copy.deepcopy(unit.get('equipment')), 'attack_range': unit.get('attack_range'),
            'formation': copy.deepcopy(unit.get('formation')),
            'fire_sector': copy.deepcopy(unit.get('fire_sector')),
            'logistics': copy.deepcopy(unit.get('logistics')), 'available': available(unit),
            'capabilities': capabilities(session, unit, entry['team']),
            'controllable': not entry.get('ambiguous') and (cs['director'] or entry['team'] == cs['control_team'])})
        if fire_reference is not None and not session['war_state'].get('history_replay'):
            roster[-1]['fire_resources']=resource_readiness.fire_budget(session['war_state'],unit,reference=fire_reference)
        from .personnel_projection import strength_pct
        strength=strength_pct(unit)
        if strength is not None:roster[-1]['personnel_strength_pct']=strength
    live = {u['id'] for u in roster}
    for entry in cs['registry']:
        if entry['id'] not in live:
            roster.append({**entry, 'position': None, 'available': False, 'controllable': False,
                'capabilities': {'actions': [], 'enabled': False, 'reason': '已退役，仅能查看既往决策与回执',
                    'move_km': 0, 'movement_basis': '当前无位置记录', 'unsupported': []}})
    dto = {k: cs[k] for k in ('version', 'revision', 'control_team', 'director', 'no_fire', 'intent', 'orders', 'unit_agents')}
    return {**dto, 'units': roster, 'world_version': world_version(session),
            'turn': session.get('turn_count', 0), 'epoch': session.get('role_epoch', 0),
            'enabled': session.get('command_state') is not None or session.get('execution_backend') == 'afsim',
            'read_only': session.get('simulation_mode', 'open') != 'open'}


def check_revision(session, expected_turn, revision, expected_world):
    if type(expected_turn) is not int or type(revision) is not int or \
            expected_turn != session.get('turn_count', 0) or revision != state(session)['revision'] or \
            expected_world != world_version(session):
        raise Conflict('战局或命令版本已改变，请刷新并重新校验；原命令未执行')


def assert_writable(session):
    if not session.get('war_state'):
        raise ValueError('请先初始化战局')
    if session.get('simulation_mode', 'open') != 'open':
        raise ValueError('历史回放不能直接执行命令，请创建开放分支')
    if session['war_state'].get('mission', {}).get('status') == 'completed':
        raise ValueError('本局已结算，不能再下令')


def step_order(session, order, cs=None):
    from . import unit_participation
    unit_participation.validate_draft(order)
    cs = cs or state(session)
    if order.get('rule_version') and order['rule_version'] != rule_version(session):
        raise ValueError('命令所用规则已变更，请编辑并重新确认后执行')
    pair = resolve_units(session, cs).get(order['unit_id'])
    if not pair or pair[0].get('ambiguous'):
        raise ValueError('单位不存在、已退役或名称有歧义')
    entry, unit = pair
    if not available(unit):
        raise ValueError('单位已失去行动能力')
    action = order['action']
    if action not in capabilities(session, unit, entry['team'])['actions']:
        if session['war_state'].get('combined_arms') and action in ('fire','bombard','suppress'):
            from . import combined_arms, campaign, ferries
            world = session['war_state']
            if campaign.release_seconds(world, unit) > 0:
                raise ValueError('单位尚未入场或启程，不能执行射击行动')
            boat = ferries.carrier(world, unit['name'])
            if boat and boat['phase'] in ('outbound','unloading'):
                raise ValueError('单位正在舟艇渡运或卸载，抵岸前不能执行射击行动')
            reason = combined_arms.fire_unavailability(world, unit).get(action)
            if reason:
                raise ValueError(reason)
        raise ValueError('当前规则未实现该行动，不能按已执行结算')
    raw = {'unit': entry['name'], 'action': action}
    if 'air_pool' in order:
        if action!='air_support':raise ValueError('只有航空任务可以指定航空资源池')
        raw['air_pool']=order['air_pool']
    if action == 'move':
        destination = position(order.get('destination'))
        budget = move_budget(session, unit, entry['team'], destination)
        origin = unit_position(unit)
        from . import ferries
        ground_distance=ferries.ground_distance(session['war_state'],unit,destination)
        from . import movement_feedback
        boat_only = (movement_feedback.configuration(session['war_state']) is not None
            and ground_distance <= .001 and ferries.route(session['war_state'],unit,destination) is not None)
        if budget <= 0 and not boat_only:
            raise ValueError('当前单位没有可核验的机动预算')
        if order['duration'] == 'next' and ground_distance > budget + .001:
            raise ValueError(f"{entry['name']}（unit_id={order['unit_id']}）：目的地超出本轮预算；"
                f"请求地面距离{ground_distance:.6f} km，当前机动预算{budget:.6f} km，"
                f"当前位置({origin['lat']:.6f},{origin['lng']:.6f})，目的地({destination['lat']:.6f},{destination['lng']:.6f})。"
                '如需前往该远处目标，明确使用duration=until_arrived，宿主只提交本轮可行路段；'
                '否则保留duration=next并选择预算内落点。候选尚未执行，不自动改变决策或放宽预算')
        if session['war_state'].get('mission'):
            spec = session['war_state']['mission']['definition']
            if distance(destination, spec['map_center']) > spec['map_radius_km']:
                raise ValueError('目的地超出局部想定边界')
        # Unconfirmed previews have no durable intent; validate their feasible
        # segment. Confirmed continuous orders retain the same final goal.
        target=(copy.deepcopy(destination) if movement_feedback.continuous(session['war_state'])
                and order['duration']=='until_arrived' and order.get('id') else towards(origin,destination,budget))
        ferry_target=ferries.step_target(session['war_state'],unit,destination,budget)
        if ferry_target is not None:target=ferry_target
        task=unit.get('crossing')
        if task and task['status']!='completed' and order['duration']=='until_arrived':
            previous=next((r for r in reversed(cs.get('receipts',[])) if r.get('unit_id')==order['unit_id']),None)
            if previous and previous.get('command_id')==order.get('id') and previous.get('crossing')==task and distance(origin,task['target'])<=budget+.001:
                target=copy.deepcopy(task['target'])
        raw.update(target)
        participation=unit_participation.request(session,order,destination)
        if participation is not None:raw['participation']=participation
        from . import crossings
        legacy_continuation=bool(task and task['version']==crossings.TASK_VERSION and order.get('created_turn',session['turn_count'])<task['turn'])
        if ((crossings.get_model(session['war_state']) and not legacy_continuation
                or movement_feedback.continuous(session['war_state'])) and order.get('id')):
            raw['intent_id']=order['id']
    if action in ('fire','bombard','suppress','capture') or action == 'air_support' and (session.get('execution_backend')=='afsim' or
            session['war_state'].get('mission',{}).get('definition',{}).get('air_definition') is not None):
        target = resolve_units(session, cs).get(order.get('target_id'))
        if not target or target[0].get('ambiguous') or target[0]['team'] == entry['team']:
            raise ValueError('攻击目标不存在、有歧义或属于己方')
        raw['target'] = target[0]['name']
    if cs['no_fire'] and entry['team'] == cs['control_team'] and action in ('fire', 'air_support','bombard','suppress','demolish'):
        raise ValueError('单位射击命令与全局禁止主动射击限制冲突')
    if session['war_state'].get('mission'):
        missions.validate_orders(session['war_state'], [raw], session['time_step'])
    return raw


@readonly_validation
def replace_queue(session, drafts, *, control_team, director, no_fire, intent):
    assert_writable(session)
    cs = state(session)
    if control_team not in ('red', 'blue') or type(director) is not bool or type(no_fire) is not bool:
        raise ValueError('控制方、导演模式或全局限制不合法')
    if not isinstance(intent, str) or len(intent) > 4000 or not isinstance(drafts, list):
        raise ValueError('全局意图或命令集合不合法')
    cs.update(control_team=control_team, director=director, no_fire=no_fire, intent=intent)
    units = resolve_units(session, cs)
    if len(drafts) > len(units):
        raise ValueError('每个单位每回合最多一项命令')
    orders, seen = [], set()
    old = {o['id']: o for o in cs['orders']}
    for draft in drafts:
        if not isinstance(draft, dict) or set(draft) - set(DRAFT_FIELDS):
            raise ValueError('命令包含不支持的字段')
        identity = draft.get('unit_id')
        pair = units.get(identity)
        if not pair or identity in seen:
            raise ValueError('命令引用未知单位或同一单位重复下令')
        if not director and pair[0]['team'] != control_team:
            raise ValueError('没有该单位的指挥权限；双边控制须显式启用导演模式')
        seen.add(identity)
        duration = draft.get('duration', 'next')
        validate_duration(draft, session['turn_count'])
        from . import unit_participation
        unit_participation.validate_draft(draft)
        old_order = old.get(draft.get('id'))
        if draft.get('id') and (not old_order or old_order['unit_id'] != identity):
            raise ValueError('命令ID不属于当前单位队列')
        order = {**copy.deepcopy(draft), 'id': uuid.uuid4().hex, 'duration': duration,
                 'status': 'queued', 'source': 'human', 'created_turn': session['turn_count'],
                 'rule_version': rule_version(session)}
        if order.get('action') != 'move':
            order.pop('destination', None)
        if order.get('action') not in ('fire','air_support','bombard','suppress','capture'):
            order.pop('target_id', None)
        keys = tuple(k for k in DRAFT_FIELDS if k!='id')
        if old_order and all(old_order.get(k) == order.get(k) for k in keys):
            order = copy.deepcopy(old_order)
        if order.get('status') != 'blocked':
            step_order(session, order, cs)
        orders.append(order)
    for order in cs['orders']:
        if not any(o['id'] == order['id'] for o in orders):
            temporary=order.get('task_context') and any(o['unit_id']==order['unit_id'] and o.get('participation') for o in orders)
            cs['archive'].append({**order, 'status': 'cancelled',
                'reason': '参与状态机动优先；原持续任务等待重新投入' if temporary else '用户编辑或替换队列'})
    cs['orders'] = orders
    if session.get('execution_backend')=='afsim':
        from backend import afsim_air
        afsim_air.validate_reservations(session['war_state'],[step_order(session,o,cs) for o in orders if o.get('status')!='blocked'])
    cs['revision'] += 1
    return cs


def cancel(session, command_id):
    assert_writable(session)
    cs = state(session)
    order = next((o for o in cs['orders'] if o['id'] == command_id), None)
    if order is None:
        raise ValueError('待执行命令不存在')
    cs['orders'].remove(order)
    cs['archive'].append({**order, 'status': 'cancelled', 'reason': '用户取消'})
    cs['revision'] += 1
    return cs


@readonly_validation
def prepare(session):
    cs = state(session)
    from . import force_task_execution
    cs = force_task_execution.prepare(session, cs)
    orders, blocked, expired = [], [], []
    units = resolve_units(session, cs)
    for order in cs['orders']:
        if order['duration'] == 'until_turn' and order['end_turn'] <= session['turn_count']:
            expired.append({**order, 'reason': '持续准备命令已到截止回合，控制权交回规划器'})
            continue
        actor = units.get(order['unit_id'])
        if not actor or not available(actor[1]):
            expired.append({**order, 'reason': '单位已退役或失去行动能力，任务终止'})
            continue
        if order['status'] == 'blocked':
            blocked.append({**order, 'reason': order.get('reason', '任务暂停，请编辑或取消')})
            continue
        try:
            orders.append({'command': copy.deepcopy(order), 'order': step_order(session, order, cs)})
        except ValueError as exc:
            blocked.append({**order, 'reason': str(exc)})
    cancelled=[]
    from . import crossings
    if crossings.get_model(session['war_state']):
        for identity,(entry,unit) in units.items():
            task=unit.get('crossing') or {}
            if task.get('version')!=crossings.BOUND_TASK_VERSION or task['status'] not in ('queued','transit'):continue
            archived=next((o for o in reversed(cs['archive']) if o['id']==task['intent_id'] and o['status']=='cancelled'),None)
            if archived:cancelled.append({'id':archived['id'],'unit_id':identity,'unit':entry['name'],'phase':task['status']})
    result={'state': cs, 'manual': orders, 'blocked': blocked, 'expired': expired,'cancelled_tasks':cancelled,
            'world_version': world_version(session), 'turn': session['turn_count']}
    if crossings.get_model(session['war_state']):result['crossing_inputs']=crossings.order_inputs(session['war_state'],merge_proposal(session,result,[]))
    return result


def merge_proposal(session, prepared, proposal):
    """Manual orders are immutable inputs, never model-editable suggestions."""
    if not isinstance(proposal, list) or any(not isinstance(o, dict) for o in proposal):
        raise ValueError('规划结果缺少合法orders数组')
    cs = prepared['state']
    manual = {x['order']['unit']: x['order'] for x in prepared['manual']}
    cancelled={r['unit']:r['id'] for r in prepared.get('cancelled_tasks',[])}
    held = {e['name'] for e in cs['registry'] if any(o['unit_id'] == e['id'] for o in prepared['blocked'])}
    controlled = {e['name'] for e in cs['registry'] if e['team'] == cs['control_team']}
    result = [copy.deepcopy(o) for o in proposal if o.get('unit') not in manual and o.get('unit') not in held and o.get('unit') not in cancelled]
    if cs['no_fire'] and any(o.get('unit') in controlled and o.get('action') in ('fire', 'air_support','bombard','suppress','demolish') for o in result):
        raise ValueError('自主规划违反全局禁止主动射击限制')
    result.extend(copy.deepcopy(list(manual.values())))
    result.extend({'unit': name, 'action': 'hold'} for name in held)
    result.extend({'unit':name,'action':'hold'} for name in cancelled if name not in manual and name not in held)
    for order in result:
        if order['unit'] in cancelled:order['cancel_crossing']=cancelled[order['unit']]
    return result


def instruction(prepared, native_orders=()):
    return ('\n【不可覆盖的已确认战棋指挥】人工命令与原生单位候选如下。'
        'updated_state必须体现这些hold/move位置；不能擅改目标、发明路线或加成。'
        '受阻单位待命；全局no_fire对当前控制方禁止主动射击。其他损耗仍须如实标为模型估计。'
        '若有crossing_inputs，这是宿主只读的本轮任务初始条件，不是已执行结果：start_work为新任务计算起点；start不能沿用态势中旧已撤销任务的工作量。排队可尚未到目的地，不为履行位置命令伪造通过。\n'
        + json.dumps({'orders': [x['order'] for x in prepared['manual']],
            'native_unit_orders': list(native_orders), 'blocked': prepared['blocked'],
            'cancelled_crossing_tasks':prepared.get('cancelled_tasks',[]),
            **({'crossing_inputs':prepared['crossing_inputs']} if 'crossing_inputs' in prepared else {}),
            'expired': prepared['expired'],
            'control_team': prepared['state']['control_team'], 'no_fire': prepared['state']['no_fire'],
            'intent': prepared['state']['intent']}, ensure_ascii=False))


def verify_open(session, prepared, after, native_orders=()):
    """Verify explicit geometric commands; never silently snap a model's candidate."""
    units = resolve_units(session, prepared['state'])
    old_by_name = {}
    for entry, unit in units.values():
        old_by_name.setdefault(entry['name'], []).append((entry, unit))
    explicit = [x['order'] for x in prepared['manual']] + list(native_orders)
    explicit.extend({'unit': next(e['name'] for e in prepared['state']['registry'] if e['id'] == o['unit_id']),
                     'action': 'hold'} for o in prepared['blocked'])
    explicit.extend({'unit':r['unit'],'action':'hold'} for r in prepared.get('cancelled_tasks',[]) if not any(x['order']['unit']==r['unit'] for x in prepared['manual']))
    after_index = {(t, name_of(u)): u for t, u in iter_units(after)}
    for order in explicit:
        matches = old_by_name.get(order['unit'], [])
        if len(matches) != 1:
            raise ValueError('当前开放规则无法按重名单位核验，须先消除同名')
        entry, prior = matches[0]
        following = after_index.get((entry['team'], entry['name']))
        if not following or not available(following):
            continue  # A confirmed loss ends the task; it cannot transfer to another unit.
        expected = position({k: order[k] for k in ('lat', 'lng')}) if order['action'] == 'move' else known_position(prior)
        actual_position = known_position(following)
        if expected is None or actual_position is None:
            if order['action'] == 'hold' and expected is None and actual_position is None:
                continue
            raise ValueError('待命位置未知或位置记录不连续，不能凭空生成或丢失坐标')
        if distance(actual_position, expected) > .01:
            from . import ferries
            boat=ferries.carrier(session['war_state'],entry['name'])
            if order['action']=='hold' and boat and boat['phase'] in ('outbound','unloading'):continue
            from . import crossings
            if crossings.pending_move(session['war_state'],prior,following,order):continue
            raise ValueError('候选未履行已确认位置命令：' + entry['name'] + '；不拉回坐标，整轮拒收')
    cs = prepared['state']
    if cs['no_fire']:
        controlled = {e['name'] for e in cs['registry'] if e['team'] == cs['control_team']}
        if any(e.get('attacker') in controlled and e.get('attacker_team', cs['control_team']) == cs['control_team']
               for e in after.get('engagements', [])):
            raise ValueError('候选交战违反全局禁止主动射击，整轮拒收')
    result = []
    for entry, prior in units.values():
        following = after_index.get((entry['team'], entry['name']))
        action = '未记录'
        try:
            if following and distance(unit_position(prior), unit_position(following)) > .01:
                action = 'move'
        except ValueError:
            pass
        result.append({'unit': entry['name'], 'action': action})
    # Explicit orders retain their actual action and destination in the receipt.
    by_name = {o['unit']: o for o in result}
    by_name.update({o['unit']: o for o in explicit})
    return list(by_name.values())


def finish(session, prepared, after, *, executed=(), rationales=(), runs=(), instruction=''):
    from . import sustainment
    budget = sustainment.assess(session['war_state'])
    cs = prepared['state']
    next_turn = session['turn_count'] + 1
    current = {o['unit']: o for o in executed}
    reasons = {(d.get('team'), d.get('unit_name')): d for d in rationales if isinstance(d, dict)}
    manual = {x['command']['unit_id']: x for x in prepared['manual']}
    blocked = {o['unit_id']: o for o in prepared['blocked']}
    expired = {o['unit_id']: o for o in prepared['expired']}
    cancelled={r['unit_id']:r for r in prepared.get('cancelled_tasks',[])}
    after_index = {(t, name_of(u)): u for t, u in iter_units(after)}
    receipts, remaining = [], []
    for identity, (entry, unit) in resolve_units(session, cs).items():
        explicit = manual.get(identity)
        stopped = blocked.get(identity)
        actual = current.get(entry['name'])
        following = after_index.get((entry['team'], entry['name']))
        declaration = reasons.get((entry['team'], entry['name']), {})
        source = 'human' if explicit or stopped or identity in cancelled else declaration.get('source', 'model_batch') if actual else 'default_hold'
        native=(following or {}).get('formation',{}).get('last_execution',{}) if after.get('combined_arms') else {}
        native_code=int(native.get('blocked',0)) if native.get('turn')==next_turn else 0
        native_undelivered=(session.get('execution_backend')=='afsim'
                            and native.get('turn')==next_turn and native.get('command_done')==0)
        status, note = 'completed', ''
        if not available(unit):
            status, note, source = 'expired', '单位失能，任务终止，未规划行动', 'unavailable'
        elif stopped:
            status, note = 'blocked', stopped['reason']
            remaining.append({**stopped, 'status': 'blocked'})
        elif not following:
            status, note = 'blocked', '本轮单位退役，持续任务终止'
        elif identity in cancelled and not explicit:
            status='cancelled';note='当前渡运指令已撤销；此前已耗容量不退回'
            if session.get('execution_backend')=='afsim' and native.get('turn')==next_turn and native.get('action')=='未交付':
                status='blocked';note='撤销指令本轮未交付，保留待撤销状态，下轮重试；此前已耗容量不退回'
            if following.get('crossing',{}).get('status')=='transit':note+='；已在通道内，重新下令时须先抵岸'
        elif native_code:
            prefix='AFSIM约束：' if session.get('execution_backend')=='afsim' else '模型回执约束：'
            note=prefix+{1:'桥梁未开放',2:'通行容量不足',3:'目的地不在渡河走廊',4:'实际交付时目标超出射程',5:'目标低于最小射程',6:'弹药不足',7:'炮兵冷却中',
                8:'火力受弹药工作量限制',9:'目标失能后停止动作',10:'燃油限制机动；实际位移与消耗见回执',11:'受降距离或条件在实际执行时未满足',12:'父级共享齐射额度未分配到本分队；轮内不重分配'}.get(native_code,'行动未执行')
            persistent=bool(explicit and explicit['command']['duration']=='until_arrived')
            status='executing' if persistent else 'blocked'
            if persistent:
                if not available(following):
                    status='blocked';note+='；本轮失去行动能力，持续任务终止'
                elif native_code==10 and distance(unit_position(following),explicit['command']['destination'])<=.01:
                    status='completed';note+='；已进入到达容差区'
                else:remaining.append({**explicit['command'],'status':'executing','reason':note+'；下一回合自动重试'})
        elif native_undelivered:
            status, note='blocked','AFSIM本轮命令未交付，不能记为执行完成'
            if after.get('campaign',{}).get('actors',{}).get(entry['name'],{}).get('active') is False:
                note+='；尚未入场或启程'
            if explicit and explicit['command']['duration']=='until_arrived' and available(following):
                remaining.append({**explicit['command'],'status':'executing','reason':note+'；下一回合重试交付'})
        elif explicit and actual and actual.get('action')=='move' and following and following.get('crossing') and distance(unit_position(following),explicit['command']['destination'])>.01:
            from . import crossings
            if crossings.pending_move(session['war_state'],unit,following,actual):
                note='渡运排队或通道行军尚未完成；本轮位置及工作量见渡运回执'
                status='executing' if explicit['command']['duration']=='until_arrived' else 'blocked'
                if status=='executing':remaining.append({**explicit['command'],'status':'executing','reason':note})
        elif explicit and explicit['command']['duration'] == 'until_arrived':
            order = explicit['command']
            if not available(following):
                status, note = 'blocked', '本轮失去行动能力，持续任务终止'
            elif distance(unit_position(following), order['destination']) > .01:
                status, note = 'executing', '本轮仅完成合法一步，目标尚未到达'
                remaining.append({**order, 'status': 'executing'})
        bounded = explicit['command'] if explicit else stopped
        if bounded and bounded.get('duration') == 'until_turn':
            remaining = [o for o in remaining if o['id'] != bounded['id']]
            undelivered = native.get('turn') == next_turn and native.get('command_done') == 0
            if not following or not available(following):
                status, note = 'expired', '单位失去行动能力或退役，持续准备终止'
            elif next_turn >= bounded['end_turn']:
                status = 'expired' if stopped or native_code or undelivered else 'completed'
                note = (note + '；' if note else '') + ('本轮命令未交付；' if undelivered else '') + f"控制期限已达T+{bounded['end_turn']}，后续由新命令或规划器接管"
            else:
                status = 'blocked' if stopped or native_code or undelivered else 'executing'
                note = (note + '；' if note else '') + ('本轮命令未交付；' if undelivered else '') + f"持续准备至T+{bounded['end_turn']}（含），可随时撤销"
                # A delayed native delivery is retried on the next turn. Keep
                # the task active, while the receipt reports this turn's failure.
                queue_status = 'executing' if undelivered and not stopped and not native_code else status
                if queue_status == 'executing' and undelivered:
                    note += '；下一回合重试交付'
                remaining.append({**bounded, 'status': queue_status, 'reason': note})
        if status == 'completed' and actual and actual.get('action') == 'hold' and following:
            from . import ferries
            boat = ferries.carrier(session['war_state'], entry['name'])
            if boat and boat['phase'] in ('outbound', 'unloading'):
                note = '地面自主动作待命；已登船分队继续随艇移动，实际位置与登岸状态见舟艇回执'
        if source == 'human':
            rationale = ('命令暂停，本轮待命：' + note) if stopped else \
                '用户已确认命令，但本轮未交付；未记为执行完成' if native_undelivered else \
                '按用户已确认命令执行；不冒称自主智能体决策'
        elif source == 'default_hold':
            rationale = '未提供行动，按规则待命；没有可核验的自主决策依据'
        else:
            rationale = str(declaration.get('rationale') or '未提供本单位公开依据，不能用总体理由替代')
        old_expired = expired.get(identity)
        timed_expiry = old_expired and old_expired.get('duration') == 'until_turn' and old_expired['end_turn'] <= session['turn_count']
        command = explicit['command'] if explicit else stopped or (None if timed_expiry else old_expired) or cancelled.get(identity)
        receipt = {'id': uuid.uuid4().hex, 'turn': next_turn, 'unit_id': identity,
            **({'task_context':copy.deepcopy(command['task_context'])} if command and command.get('task_context') else {}),
            'team': entry['team'], 'unit_name': entry['name'], 'source': source,
            'command_id': command['id'] if command else None, 'status': status, 'reason': note,
            'planned': copy.deepcopy(explicit['order'] if explicit else actual),
            'action': (actual or {}).get('action', 'hold'), 'rationale': rationale,
            'expected_effect': str(declaration.get('expected_effect') or ''),
            **({'proposal': copy.deepcopy(declaration['proposal'])} if declaration.get('proposal') else {}),
            'before_position': known_position(unit), 'after_position': known_position(following),
            'before_logistics': copy.deepcopy(unit.get('logistics')), 'after_logistics': copy.deepcopy(following.get('logistics')) if following else None,
            **({'decision_context':{**sustainment.decision_context(session['war_state'], unit),
                    'team':entry['team'],
                    'team_hold_food_budget':budget['teams'][entry['team']]['minimum_hold_food'],
                    'team_parent_equivalents':budget['teams'][entry['team']]['parent_equivalents']}}
               if session['war_state'].get('combined_arms') and session['war_state'].get('mission') else {}),
            **({'operator_instruction':instruction} if instruction else {}),
            'before_personnel': copy.deepcopy(unit.get('personnel')), 'after_personnel': copy.deepcopy(following.get('personnel')) if following else None,
            'goal': copy.deepcopy(explicit['command'].get('destination')) if explicit else None,
            'ledger': next((copy.deepcopy(r) for r in after.get('mission', {}).get('ledger', []) if r['unit'] == entry['name']), None),
            'air_tasks': [copy.deepcopy(t) for t in after.get('air_operations',{}).get('missions',[]) if t['requester']==entry['name']],
            **({'crossing':copy.deepcopy(following['crossing'])} if following and following.get('crossing',{}).get('turn')==next_turn else {}),
            'run_ids': [] if source in ('human', 'default_hold', 'unavailable') else
                declaration.get('run_ids', [r['id'] for r in runs]),
            'observation_version': prepared['world_version'],
            'rule_version': rule_version(session),
            'outcome_basis': ('afsim_native_teaching_results' if str(after.get('afsim',{}).get('effects_source','')).startswith('afsim-native-') else
                'afsim_motion_and_teaching_rules' if after.get('mission') else 'afsim_observed_motion_other_effects_unmodeled')
                if session.get('execution_backend') == 'afsim' else 'dsh_model_estimate' if after.get('dsh_execution') else 'deterministic_teaching_rules' if after.get('mission') else
                'position_unknown_other_effects_model_estimated' if known_position(unit) is None and known_position(following) is None else
                'movement_verified_other_effects_model_estimated'}
        receipts.append(receipt)
        if command and status not in ('executing',) and not any(o['id'] == command['id'] for o in remaining) and not (identity in cancelled and not explicit):
            cs['archive'].append({**command, 'status': status, 'reason': note})
    live_ids = set(resolve_units(session, cs))
    for order in prepared['expired']:
        if order['unit_id'] in live_ids:
            if order.get('duration') == 'until_turn' and order['end_turn'] <= session['turn_count']:
                cs['archive'].append({**order, 'status': 'expired'})
            continue
        entry = next(e for e in cs['registry'] if e['id'] == order['unit_id'])
        reason = '单位已退役或不在当前名单，命令终止，不转移给同名新单位'
        cs['archive'].append({**order, 'status': 'expired', 'reason': reason})
        receipts.append({'id': uuid.uuid4().hex, 'turn': next_turn, 'unit_id': entry['id'],
            'team': entry['team'], 'unit_name': entry['name'], 'source': 'unavailable',
            'command_id': order['id'], 'status': 'expired', 'reason': reason, 'planned': copy.deepcopy(order),
            'action': '未执行', 'rationale': reason, 'expected_effect': '', 'run_ids': []})
    if after.get('mission', {}).get('status') == 'completed':
        cs['archive'].extend({**o, 'status': 'expired', 'reason': '本局已结算'} for o in remaining)
        remaining = []
    cs['orders'] = remaining
    for entry in cs['registry']:
        if (entry['team'], entry['name']) not in after_index:
            entry.update(retired=True, retired_turn=next_turn, present=False)
    after_session = {**session, 'war_state': after, 'command_state': cs}
    cs = state(after_session)
    for identity, (entry, unit) in resolve_units(after_session, cs).items():
        if identity in live_ids:
            continue
        receipts.append({'id': uuid.uuid4().hex, 'turn': next_turn, 'unit_id': identity,
            'team': entry['team'], 'unit_name': entry['name'], 'source': 'added_this_turn',
            'status': 'recorded', 'command_id': None, 'planned': None, 'action': '本轮新增',
            'rationale': '回合开始时无此单位；没有独立决策依据，新增数量仍须核对来源',
            'expected_effect': '', 'run_ids': [], 'before_position': None,
            'after_position': {'lat': unit.get('lat'), 'lng': unit.get('lng')}})
    cs['unit_agents'] = [identity for identity in cs['unit_agents'] if any(
        e['id'] == identity and not e.get('retired') and available(after_index.get((e['team'], e['name']), {}))
        for e in cs['registry'])]
    cs['receipts'].extend(receipts)
    from . import force_task_execution
    cs = force_task_execution.finish(session, cs, after, receipts)
    cs['revision'] += 1
    decisions = [{**{k: r[k] for k in ('team', 'unit_name', 'action', 'rationale', 'expected_effect', 'source', 'unit_id', 'run_ids')},
                  **({'proposal': copy.deepcopy(r['proposal'])} if r.get('proposal') else {})}
                 for r in receipts]
    return cs, decisions


def validate_saved(session,*,check_handoff=True):
    validate_identity_origin(session)
    stored = session.get('command_state')
    if stored is None:
        return
    if not isinstance(stored, dict) or stored.get('version') != VERSION:
        raise ValueError('命令状态版本非法')
    if type(stored.get('revision')) is not int or stored['revision'] < 0:
        raise ValueError('命令修订号非法')
    if stored.get('control_team') not in ('red', 'blue') or \
            any(type(stored.get(k)) is not bool for k in ('director', 'no_fire')):
        raise ValueError('命令权限存档非法')
    for key in ('registry', 'orders', 'archive', 'receipts'):
        if not isinstance(stored.get(key), list) or any(not isinstance(x, dict) for x in stored[key]):
            raise ValueError('命令存档结构非法：' + key)
    ids = {r.get('id') for r in stored['registry']}
    if len(ids) != len(stored['registry']) or any(not isinstance(x, str) for x in ids):
        raise ValueError('单位身份存档非法')
    if session.get('command_identity_origin') is not None:
        prior={}
        for row in stored['registry']:
            key=(row.get('team'),row.get('name'));old=prior.get(key)
            if (old and not old.get('retired') or row['id']!=actor_identity(session,*key,old['id'] if old else '')):
                raise ValueError('分支单位身份与原命令命名空间不一致')
            prior[key]=row
    agents = stored.get('unit_agents')
    if not isinstance(agents, list) or any(not isinstance(x, str) or x not in ids for x in agents) or len(set(agents)) != len(agents):
        raise ValueError('单位Agent绑定存档非法')
    if not isinstance(stored.get('intent'), str) or len(stored['intent']) > 4000:
        raise ValueError('全局意图存档非法')
    if any(e.get('team') not in ('red', 'blue') or not isinstance(e.get('name'), str) for e in stored['registry']):
        raise ValueError('单位注册表非法')
    order_ids, unit_ids = set(), set()
    for order in stored['orders']:
        if order.get('unit_id') not in ids or order.get('status') not in ACTIVE \
                or order.get('duration') not in ('next', 'until_arrived', 'until_turn'):
            raise ValueError('队列存档非法')
        if order.get('action') not in missions.ACTIONS or order.get('source') != 'human':
            raise ValueError('队列动作或来源非法')
        if not isinstance(order.get('id'), str) or order['id'] in order_ids or order['unit_id'] in unit_ids:
            raise ValueError('队列存在重复身份')
        order_ids.add(order['id'])
        unit_ids.add(order['unit_id'])
        if order.get('action') == 'move':
            position(order.get('destination'))
        if (order.get('action') in ('fire','bombard','suppress','capture') or order.get('action')=='air_support' and order.get('target_id')) and order.get('target_id') not in ids:
            raise ValueError('队列攻击目标非法')
        validate_duration(order, order.get('created_turn'))
        from . import unit_participation
        unit_participation.validate_draft(order)
    if not isinstance(stored.get('batches'), dict):
        raise ValueError('命令批次存档非法')
    for key, value in stored['batches'].items():
        if not isinstance(key, str) or not isinstance(value, dict) or not isinstance(value.get('input_hash'), str) \
                or type(value.get('turn')) is not int or value['turn'] > session['turn_count']:
            raise ValueError('命令批次引用非法')
    bindings = stored.get('agent_sessions', {})
    if not isinstance(bindings, dict):
        raise ValueError('单位原生会话绑定非法')
    for identity, binding in bindings.items():
        prefix = f"gentactix-unit-{session['id']}-e{session.get('role_epoch', 0)}-{identity}-"
        if identity not in ids or not isinstance(binding, dict) or not isinstance(binding.get('session_id'), str) \
                or not binding['session_id'].startswith(prefix):
            raise ValueError('单位原生会话绑定与战局身份不符')
    from . import force_task_execution
    force_task_execution.validate(session, stored)
    if check_handoff and ('formation_handoffs' in stored or session.get('war_state',{}).get('formation_registry')):
        from . import formation_session
        formation_session.validate_history(session,stored)
    json.dumps(stored, allow_nan=False)


def complete_decisions(before, after, declared, runs, *, replay=False):
    """Complete coverage is explicit even when the model omits a unit's reason."""
    index = {(d.get('team'), d.get('unit_name')): d for d in declared or [] if isinstance(d, dict)}
    result = []
    initial = list(iter_units(before))
    names = {(team, name_of(unit)) for team, unit in initial}
    arrivals = [(team, unit) for team, unit in iter_units(after) if (team, name_of(unit)) not in names]
    for team, unit in initial + arrivals:
        name = name_of(unit)
        d = copy.deepcopy(index.get((team, name)))
        if d is None:
            d = {'team': team, 'unit_name': name, 'action': '未记录',
                 'rationale': '本轮未提供该单位的公开决策依据', 'source': 'missing', 'run_ids': []}
        else:
            d.update(source='model_reconstruction' if replay else 'model_batch', run_ids=[r['id'] for r in runs])
        if replay:
            d['history_refs'] = []  # Retrieval context alone does not prove a historical command.
        if (team, name) not in names:
            d.update(source='added_this_turn', action='本轮新增', rationale='回合开始时无此单位，未进行独立决策', run_ids=[])
        result.append(d)
    return result
