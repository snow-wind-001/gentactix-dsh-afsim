"""Operation participation over the existing physical roster and stock accounts.

Only checked movement changes participation. Rear units retain actual positions,
remain targetable and keep paying the selected backend's sustainment costs.
"""
import copy
import math
import re

VERSION = 'unit-participation-1'
BOUNDARY_VERSION = 'unit-participation-2'
REQUEST_VERSION = 'unit-participation-request-1'
STATUSES = {'staging', 'deployed', 'withdrawing', 'reserve', 'returning', 'offmap'}
LABELS = {'staging':'待入场', 'deployed':'在场作战', 'withdrawing':'退出途中',
          'reserve':'后方待命', 'returning':'重新投入途中', 'offmap':'场外待命'}
OFFENSIVE = {'fire', 'bombard', 'suppress', 'capture', 'air_support', 'sabotage', 'accept'}
ARRIVAL_KM = .01  # Same arrival tolerance as the ordinary command queue.


def _index(world):
    from . import missions, force_organization
    return {force_organization.leaf_key(team, u):(team,u) for team,u in missions.units(world)}


def _key(world, unit):
    from . import missions,force_organization
    team=next(t for t,u in missions.units(world) if u is unit or u['name']==unit['name'])
    return force_organization.leaf_key(team,unit)


def initialize(world):
    from . import operation_boundary
    if not operation_boundary.configuration(world):return
    state=dict(version=BOUNDARY_VERSION,definition_hash=world['mission']['definition_hash'],turn=0,elapsed_seconds=0,
        actors={i:dict(team=t,name=u['name'],status='deployed' if _released(world,u) else 'staging',
            pending=None,transition_count=0,status_since=0,last_transition=None) for i,(t,u) in _index(world).items()},last_changes=[])
    _seal(state);world['unit_participation']=state


def supported(world):
    spec=world.get('mission',{}).get('definition',{})
    return bool(spec.get('combined_rules') and spec.get('campaign_plan'))


def _fields(value, fields, label):
    if not isinstance(value,dict) or set(value)!=set(fields):raise ValueError(label+'字段缺失或越界')


def _number(value, maximum, label):
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=maximum:
        raise ValueError(label+'须为有界非负数')


def _point(value):
    from . import commands
    return commands.position(value)


def _released(world, unit):
    from . import campaign
    return campaign.release_seconds(world,unit)==0


def unit_view(world, unit, team=None):
    from . import operation_boundary
    boundary=operation_boundary.configuration(world)
    identity=_key(world,unit);row=(world.get('unit_participation') or {}).get('actors',{}).get(identity)
    status=row['status'] if row else ('deployed' if _released(world,unit) else 'staging')
    alive=(unit.get('personnel') or {}).get('current',0)>0
    return dict(entity_id=identity,status=status,label=LABELS[status],
        readiness='available' if alive else 'disabled',
        targetable=bool(alive and _released(world,unit)),
        controls_objectives=bool(alive and status not in ('reserve','returning','staging','offmap')
            and (not boundary or operation_boundary.inside(boundary,unit))),
        pending=copy.deepcopy(row['pending']) if row else None,
        transition_count=row['transition_count'] if row else 0,
        **({'conversion_origin':copy.deepcopy(row['conversion_origin']),
            'last_transition':copy.deepcopy(row['last_transition']),
            'transition_count_scope':'本执行身份创建后的物理转换次数；前身计数单独保留，不相加'}
            if row and row.get('conversion_origin') else {}),
        **({'operation_zone':'inside' if operation_boundary.inside(boundary,unit) else 'outside'} if boundary else {}),
        scope=('场外指明确作战区之外，仍在同一物理世界，保留真实位置与资源，可受远程打击；不是退役或瞬移。' if boundary else
            '后方仍在会战世界中，保留实际位置与全部账目，可受远程打击；不是隐身、瞬移或补满。'))


def in_operation(world, unit):
    from . import operation_boundary
    boundary=operation_boundary.configuration(world)
    if boundary and not operation_boundary.inside(boundary,unit):return False
    if 'unit_participation' not in world:return True
    row=(world.get('unit_participation') or {}).get('actors',{}).get(_key(world,unit))
    return row is None or row['status'] not in ('reserve','returning','staging','offmap')


def validate_draft(order):
    """The public command carries intent; only the host creates a request ID."""
    if 'participation' not in order:return
    if order['participation'] not in ('withdraw','reenter'):
        raise ValueError('参与方式只支持withdraw或reenter')
    if order.get('action')!='move' or order.get('duration','next')!='until_arrived':
        raise ValueError('退出/重返须使用move且duration=until_arrived，不能仅修改标签')


def request(session,order,destination):
    """Preserve the final goal, independently of this turn's clipped move leg."""
    validate_draft(order)
    if 'participation' not in order:return None
    import uuid
    from . import missions
    identity=order.get('id') or uuid.uuid5(uuid.NAMESPACE_URL,missions.digest([
        session['id'],session.get('role_epoch',0),session['turn_count'],order['unit_id'],
        order['participation'],destination])).hex
    return dict(version=REQUEST_VERSION,id=identity,kind=order['participation'],destination=copy.deepcopy(destination))


def _request(value):
    _fields(value,{'version','id','kind','destination'},'参与状态请求')
    if value['version']!=REQUEST_VERSION or not isinstance(value['id'],str) or not re.fullmatch('[a-f0-9]{32}',value['id']):
        raise ValueError('参与状态请求版本或身份非法')
    if value['kind'] not in ('withdraw','reenter'):raise ValueError('参与状态请求仅支持withdraw/reenter')
    _point(value['destination'])


def check_order(world, order):
    if 'unit_participation' not in world and 'participation' not in order:return
    from . import missions
    unit=next((u for _,u in missions.units(world) if u['name']==order.get('unit')),None)
    if unit is None:raise ValueError('参与状态请求引用未知单位')
    from . import operation_boundary
    boundary=operation_boundary.configuration(world)
    row=(world.get('unit_participation') or {}).get('actors',{}).get(_key(world,unit))
    if row and row['status'] in ('reserve','returning','offmap') and order.get('action') in OFFENSIVE:
        raise ValueError('单位处于'+LABELS[row['status']]+'；请先以机动命令完成重新投入，不能直接派发进攻动作')
    request=order.get('participation')
    if request is None:
        operation_boundary.check_order(world,unit,None,order)
        return
    _request(request)
    team=next(t for t,u in missions.units(world) if u is unit)
    operation_boundary.check_order(world,unit,team,order)
    if not supported(world):raise ValueError('退出/重返须先绑定多兵种与宿主会战目标图，旧几何想定不启用此能力')
    if order.get('action')!='move':raise ValueError('退出/重返必须附于实际移动命令，不能直接修改状态')
    if not _released(world,unit):raise ValueError('部队尚未入场，不能把未来参考变成当前撤出或返场单位')
    if unit['personnel']['current']<=0:raise ValueError('失能单位不能凭参与状态命令恢复行动')
    destination=request['destination'];spec=world['mission']['definition']
    if missions.distance(destination,spec['map_center'])>spec['map_radius_km']:
        raise ValueError('退出/重返目的地须位于当前会战世界内，不虚构场外路线')
    pending=row['pending'] if row else None
    if pending and pending['id']==request['id']:
        if any(pending[k]!=request[k] for k in ('kind','destination')):raise ValueError('同一参与请求不能改写方向或目标')
        return
    base=pending['origin_status'] if pending else row['status'] if row else 'deployed'
    if (request['kind']=='withdraw' and base!='deployed') or (request['kind']=='reenter' and base not in ('reserve','offmap')):
        raise ValueError('退出/重返请求与当前参与状态不一致')
    if missions.distance(unit,destination)<=ARRIVAL_KM:
        raise ValueError('退出/重返须明确实际机动目的地，不能在原地改标签冒充移动')


def _seal(value):
    from . import missions
    value['state_hash']=missions.digest({k:v for k,v in value.items() if k!='state_hash'})


def validate_state(world):
    from . import missions
    value=world.get('unit_participation')
    if value is None:
        from . import operation_boundary
        if operation_boundary.configuration(world):raise ValueError('作战区边界缺少唯一参与实体登记')
        return
    if not supported(world):raise ValueError('参与状态缺少已绑定的会战规则')
    _fields(value,{'version','definition_hash','turn','elapsed_seconds','actors','last_changes','state_hash'},'参与状态登记')
    from . import operation_boundary
    boundary=operation_boundary.configuration(world)
    if (value['version']!=(BOUNDARY_VERSION if boundary else VERSION) or value['definition_hash']!=world['mission']['definition_hash']
            or value['turn']!=world['mission']['turn'] or value['elapsed_seconds']!=world['simulation_clock']['elapsed_seconds']
            or value['state_hash']!=missions.digest({k:v for k,v in value.items() if k!='state_hash'})):
        raise ValueError('参与状态与定义、世界时钟或摘要不一致')
    index=_index(world);_fields(value['actors'],index,'唯一实体登记')
    for identity,row in value['actors'].items():
        _fields(row,{'team','name','status','pending','transition_count','status_since','last_transition'}|
            ({'conversion_origin'} if 'conversion_origin' in row else set()),'实体参与状态')
        team,unit=index[identity]
        from . import formation_continuity
        if row.get('conversion_origin')!=formation_continuity.actor_origin(world,unit,team):
            raise ValueError('参与状态前身来源与已登记转换不一致')
        if row['team']!=team or row['name']!=unit['name'] or row['status'] not in STATUSES:
            raise ValueError('参与状态身份或状态非法')
        if row['status']=='offmap' and (not boundary or operation_boundary.inside(boundary,unit)):
            raise ValueError('场外状态须有实际作战区外位置及明确边界')
        if boundary and row['status'] in ('deployed','reserve') and not operation_boundary.inside(boundary,unit):
            raise ValueError('作战区外实体不能伪称在场或区内后方待命')
        if type(row['transition_count']) is not int or row['transition_count']<0:raise ValueError('参与状态计数非法')
        _number(row['status_since'],value['elapsed_seconds'],'参与状态时点')
        pending=row['pending']
        if pending is not None:
            _fields(pending,{'id','kind','destination','origin_status','origin_position','issued_turn'},'在途参与请求')
            _request(dict(version=REQUEST_VERSION,**{k:pending[k] for k in ('id','kind','destination')}))
            _point(pending['origin_position'])
            if pending['origin_status'] not in ('deployed','reserve','offmap') or type(pending['issued_turn']) is not int or not 0<=pending['issued_turn']<value['turn']:
                raise ValueError('参与请求起点或时序非法')
        if row['status'] in ('withdrawing','returning') and (pending is None or pending['kind']!=('withdraw' if row['status']=='withdrawing' else 'reenter')):
            raise ValueError('在途参与状态缺少匹配请求')
        transition=row['last_transition']
        if transition is not None:
            _fields(transition,{'from','to','at_seconds','source','request_id','position'},'参与状态回执')
            if transition['from'] not in STATUSES or transition['to']!=row['status'] or transition['source'] not in ('afsim_native','dsh_model_estimate'):
                raise ValueError('参与状态回执来源或状态非法')
            _number(transition['at_seconds'],value['elapsed_seconds'],'参与回执时点');_point(transition['position'])
    if not isinstance(value['last_changes'],list) or len(value['last_changes'])>len(index):raise ValueError('参与变化集非法')
    for change in value['last_changes']:
        if not isinstance(change,dict) or change.get('entity_id') not in index or change!={'entity_id':change['entity_id'],**value['actors'][change['entity_id']]['last_transition']}:
            raise ValueError('参与变化与实体回执不一致')


def advance(before, after, orders, seconds, *, source):
    """Settle participation from checked movement; never alter physical accounts."""
    from . import missions, ferries
    validate_state(before)
    from . import operation_boundary
    operation_boundary.validate_motion(before,after,orders)
    requests=[o for o in orders if o.get('participation')]
    if not requests and 'unit_participation' not in before:return
    if source not in ('afsim_native','dsh_model_estimate'):raise ValueError('参与状态须标明所选过程后端')
    if (after['mission']['turn']!=before['mission']['turn']+1 or
            after['simulation_clock']['elapsed_seconds']-before['simulation_clock']['elapsed_seconds']!=seconds):
        raise ValueError('参与状态必须与真实物理时钟逐轮结算')
    for order in requests:check_order(before,order)
    old_index=_index(before);new_index=_index(after)
    if set(old_index)!=set(new_index):raise ValueError('参与状态不能增删或替换物理实体')
    previous=before.get('unit_participation');elapsed=after['simulation_clock']['elapsed_seconds']
    state=copy.deepcopy(previous) if previous else dict(version=BOUNDARY_VERSION if operation_boundary.configuration(before) else VERSION,definition_hash=before['mission']['definition_hash'],
        actors={i:dict(team=team,name=u['name'],status='deployed' if _released(before,u) else 'staging',
            pending=None,transition_count=0,status_since=before['simulation_clock']['elapsed_seconds'],last_transition=None)
            for i,(team,u) in old_index.items()})
    if previous is None and before.get('formation_registry'):
        from . import formation_continuity
        for identity,(team,unit) in old_index.items():
            origin=formation_continuity.actor_origin(before,unit,team)
            if origin is not None:state['actors'][identity]['conversion_origin']=origin
    state.update(turn=after['mission']['turn'],elapsed_seconds=elapsed,last_changes=[])
    by_name={o['unit']:o for o in orders}
    for identity,(_,unit) in new_index.items():
        row=state['actors'][identity];prior_status=row['status'];pending=row['pending'];old_unit=old_index[identity][1]
        order=by_name.get(unit['name'],{});request=order.get('participation');request_id=None
        if request:
            request_id=request['id']
            if not pending or pending['id']!=request_id:
                base=pending['origin_status'] if pending else row['status']
                pending=dict(**{k:copy.deepcopy(request[k]) for k in ('id','kind','destination')},origin_status=base,
                    origin_position={k:old_unit[k] for k in ('lat','lng')},issued_turn=before['mission']['turn'])
            row['pending']=pending
            native=unit.get('formation',{}).get('last_execution',{})
            delivered=source!='afsim_native' or native.get('turn')==after['mission']['turn'] and native.get('command_done')==1 and native.get('action')=='move'
            boat=ferries.carrier(after,unit['name'])
            transit=bool(boat and boat['phase'] in ('outbound','unloading') or unit.get('crossing',{}).get('status') in ('queued','transit'))
            reached=delivered and not transit and unit['personnel']['current']>0 and missions.distance(unit,pending['destination'])<=ARRIVAL_KM
            if reached:
                outside=bool(operation_boundary.configuration(after) and not operation_boundary.inside(operation_boundary.configuration(after),unit))
                row.update(status=('offmap' if outside else 'reserve') if pending['kind']=='withdraw' else 'deployed',pending=None)
            elif delivered and missions.distance(unit,pending['origin_position'])>1e-6:
                row['status']='withdrawing' if pending['kind']=='withdraw' else 'returning'
        elif pending:
            request_id=pending['id'];row.update(status=pending['origin_status'],pending=None)
            if operation_boundary.configuration(after):
                outside=not operation_boundary.inside(operation_boundary.configuration(after),unit)
                if outside:row['status']='offmap'
                elif row['status']=='offmap':row['status']='reserve'
        elif row['status']=='staging' and _released(after,unit):row['status']='deployed'
        if row['status']!=prior_status:
            row['transition_count']+=1;row['status_since']=elapsed
            row['last_transition']=dict(**{'from':prior_status,'to':row['status']},at_seconds=elapsed,
                source=source,request_id=request_id,position={k:unit[k] for k in ('lat','lng')})
            state['last_changes'].append(dict(entity_id=identity,**copy.deepcopy(row['last_transition'])))
    _seal(state)
    prior_after=after.get('unit_participation')
    if prior_after is not None and prior_after!=previous and prior_after!=state:
        raise ValueError('执行后端不能直接改写宿主参与状态')
    # Validate detached state before exposing any change to the candidate.
    candidate={**after,'unit_participation':state};validate_state(candidate)
    after['unit_participation']=state


def instruction(world):
    if not supported(world):return ''
    from . import operation_boundary
    return (('本局存在operation_boundary：作战区外仍在同一物理世界。跨界须沿get_afsim_observation(detail=true，按所选单位阵营返回通路)中本方登记直线通路，先到区内点再退出，到达区外点为offmap；返场到区内点才恢复。不能以普通移动隐式跨界，或自行修改参与登记。' if operation_boundary.configuration(world) else '')+
        '\n【参与状态】participation随明确move命令原样传递，包含version/id/kind/destination；'
        '宿主按实际到达结算退出或重返，不提交unit_participation；operation_participation只读，不放入unit_updates。后方待命仍耗粮、保持伤损并可被攻击；'
        '后方单位不能直接进攻。普通移动不自动退出；历史日期不触发参与状态。')
