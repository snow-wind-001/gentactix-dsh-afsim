"""Frozen timed delivery inputs and receipt checks; never execute a shipment."""
import copy
import math
from datetime import datetime

from . import missions, sim_clock, supply, support_dynamics as sd, formation_parts

VERSION = 'scheduled-supply-1'
PHYSICAL_VERSION = 'scheduled-supply-2'
CLASSIFIED = ('fuel_liters', 'spares', 'materials', 'shells', 'aa_rounds')
FIELDS = {'version', 'period_seconds', 'passive_work_per_hour', 'resupply_work_per_hour',
          'convoy_speed_kph', 'loading_hours', 'warehouse_tons_per_hour', 'assumption'}
EVENT_FIELDS = {'seconds', 'kind', 'supply_status', 'position', 'food_received',
                'ammo_received', 'ammo_spent', 'received', 'spent'}


def configuration(world):
    return world.get('mission', {}).get('definition', {}).get('supply_schedule')


def receipt_version(world):
    from . import movement_feedback
    return PHYSICAL_VERSION if movement_feedback.continuous(world) else VERSION


def _unit_fields(world):
    return {'unit','events','nutrition_segments','fuel_timeline'} if receipt_version(world)==PHYSICAL_VERSION else {'unit','events'}


def compact_ledger(ledger,checked):
    """Keep accepted endpoints for observation; summaries are not new evidence."""
    if ledger['version']!=PHYSICAL_VERSION:return copy.deepcopy(ledger)
    return dict(version=PHYSICAL_VERSION,representation='validated-summary-1',units=[
        dict(unit=r['unit'],events=copy.deepcopy(r['events']),
            nutrition_summary=copy.deepcopy(checked[r['unit']]['nutrition']),
            fuel_timeline=copy.deepcopy(r['fuel_timeline'])) for r in ledger['units']])


def _number(value, low=0, high=1e12):
    try:valid=type(value) in (int,float) and low<=value<=high and math.isfinite(value)
    except (OverflowError,TypeError):valid=False
    if not valid:
        raise ValueError('定时补给参数或回执须为有界有限数')


def validate_config(cfg, node_ids=None):
    if not isinstance(cfg, dict) or set(cfg) != FIELDS or cfg['version'] != VERSION:
        raise ValueError('定时补给配置字段或版本非法')
    period = cfg['period_seconds']
    if type(period) is not int or not 60 <= period <= 86400 or period % 10:
        raise ValueError('定时补给周期须为60至86400秒且为10秒的整数倍')
    _number(cfg['passive_work_per_hour'], 0, 1000)
    _number(cfg['resupply_work_per_hour'], cfg['passive_work_per_hour'], 1000)
    _number(cfg['convoy_speed_kph'], .01, 200)
    _number(cfg['loading_hours'], .01, 24)
    if not isinstance(cfg['assumption'], str) or not cfg['assumption'].strip() or len(cfg['assumption']) > 4000:
        raise ValueError('定时补给须说明周期服务、已运行管线的假设及未经历史标定的边界')
    rates = cfg['warehouse_tons_per_hour']
    if (not isinstance(rates, dict) or not rates or len(rates) > 128
            or any(not isinstance(k, str) or not k.strip() for k in rates)):
        raise ValueError('定时补给须逐仓声明每小时装卸吨位')
    if node_ids is not None and set(rates) != set(node_ids):
        raise ValueError('定时补给装卸能力必须覆盖且仅覆盖本局仓库')
    for v in rates.values(): _number(v, 0, 1e6)


def validate_parameters(params,*,node_ids=None):
    cfg = params.get('supply_schedule')
    if cfg is None: return
    validate_config(cfg,node_ids)
    if not params.get('support_dynamics') or not params.get('supply_distribution'):
        raise ValueError('定时补给需要按时耗粮和分类粮弹配置')
    if params['rules'].get('bridge_enabled', True):
        raise ValueError('定时补给v1尚不支持共享渡运容量；须单独验证跨河货运，不得静默跳过设施')
    period = cfg['period_seconds']
    if sim_clock.duration_seconds(params['clock']['time_step']) // period > 96:
        raise ValueError('定时补给每轮最多96次到货；请缩短回合或明确更长的补给周期')


def event_times(world, seconds):
    cfg = configuration(world)
    validate_config(cfg)
    probe=type(seconds) is float and seconds==.001
    if not probe and (type(seconds) is not int or not 0 < seconds <= 31 * 86400):
        raise ValueError('定时补给回合秒数非法')
    start = world.get('simulation_clock', {}).get('elapsed_seconds', 0)
    if type(start) not in (int, float) or not math.isfinite(start) or start < 0 or start != int(start):
        raise ValueError('定时补给缺少有效累计时钟')
    if probe:return [(.001,'settlement')]  # Existing input/template load probe, never a delivery.
    origin=world.get('simulation_clock',{}).get('origin_iso')
    if origin:
        try:
            stamp=datetime.fromisoformat(origin)
            # Civil-time anchor survives adjacent phase branches whose local
            # elapsed clock restarts. No timezone or historical clock is inferred.
            start+=stamp.toordinal()*86400+stamp.hour*3600+stamp.minute*60+stamp.second
        except (ValueError,TypeError):raise ValueError('定时补给日期时钟锚点无效')
    period = cfg['period_seconds']
    first = period - int(start) % period
    times = [(t, 'delivery') for t in range(first, seconds + 1, period)]
    if len(times) > 96: raise ValueError('定时补给每轮超过96次到货')
    return times + [(seconds, 'settlement')]


def validate_state(world):
    cfg = configuration(world)
    if cfg is None:
        if world.get('supply_schedule') is not None:
            raise ValueError('未启用定时补给却存在执行回执')
        return
    validate_config(cfg, [n['id'] for n in world['supply_nodes']])
    spec = world['mission']['definition']
    if (not spec.get('support_dynamics') or not spec.get('supply_distribution')
            or not spec.get('combined_rules') or spec['combined_rules'].get('bridge_enabled', True)):
        raise ValueError('定时补给须配套按时耗粮、分类粮弹及当前支持的陆上通道')
    event_times(world, sim_clock.duration_seconds(spec['time_step']))


def transport_bound(world, unit, position):
    """Read-only tons per service period; no route selection or allocation."""
    cfg = configuration(world); rules = world['mission']['definition']['combined_rules']
    team = next(t for t, u in missions.units(world) if u['name'] == unit['name'])
    node = supply.bound_node(world, team, unit)
    distance = missions.distance(node, position)
    trucks = sum(e['operational'] for e in unit['equipment'] if e['category'] == 'transport')
    ratio = unit['personnel']['current'] / unit['personnel']['committed']
    hours = cfg['period_seconds'] / 3600
    trip = cfg['loading_hours'] + 2 * distance / cfg['convoy_speed_kph']
    return trucks * rules['transport_tons_per_truck'] * ratio * hours / trip


def reference_inputs(world):
    # Campaign release checks need the actual date, not just elapsed seconds.
    # Frozen origin templates already travel in mission.definition.initial_state.
    return {key: copy.deepcopy(world[key]) for key in ('mission', 'current_time', 'simulation_clock',
             'supply_nodes', 'red_units', 'blue_units','combined_arms')}


def _known_cuts(before, rows, orders, after=None, *, only_claimed=False):
    """Necessary bounds from declared positions; never resolve combat deaths.

    A threatened unit with uncertain timed death is not invented as a live
    blocker. A positive final population, or the existing worst-case nutrition
    bound in a non-targeted unit, does prove survival for this check.
    """
    from . import campaign
    from .adjudicator import _blocked_along
    units=missions.units(before);events={r['unit']:r['events'] for r in rows}
    actions={o['unit']:o.get('action','hold') for o in orders}
    targets={o.get('target') for o in orders if o.get('action') in ('fire','bombard','suppress','capture','air_support')}
    finals={u['name']:u for _,u in missions.units(after)} if after is not None else {}
    nutrition=sd.configuration(before)
    for team,unit in units:
        node=supply.bound_node(before,team,unit)
        for index,event in enumerate(events[unit['name']]):
            if event['kind']!='delivery' or only_claimed and event['supply_status']!='未切断':continue
            threats=[]
            for other_team,other in units:
                radius=other.get('ground_control_radius_km',0)
                if other_team==team or radius<=0 or other['personnel']['current']<=0:continue
                if campaign.release_seconds(before,other)>event['seconds']:continue
                final_current=finals.get(other['name'],{}).get('personnel',{}).get('current',0)
                certain=final_current>0
                if not certain and other['name'] not in targets:
                    probe=copy.deepcopy(other);probe['logistics']['food']=0
                    loss=sd.expected(nutrition,probe,actions.get(other['name'],'hold'),event['seconds'])['noncombat_delta']
                    certain=other['personnel']['current']>loss
                if not certain:continue
                position=events[other['name']][index]['position'] if actions.get(other['name'])=='move' else other
                threats.append((other['name'],[position['lat'],position['lng']],radius))
            position=event['position'] if actions.get(unit['name'])=='move' else unit
            cut,blocker,_=_blocked_along([node['lat'],node['lng']],[position['lat'],position['lng']],threats)
            if cut:yield unit['name'],index,event['seconds'],blocker


def _validate_known_control(before, rows, orders, after=None):
    events={row['unit']:row['events'] for row in rows}
    for name,index,when,blocker in _known_cuts(before,rows,orders,after,only_claimed=True):
        if events[name][index]['supply_status']=='未切断':
            raise ValueError(f"{name}在{when:g}秒的直连补给被{blocker}已知控制区切断，不能声明未切断或到货")


def _event_shape(event, expected):
    if (not isinstance(event,dict) or set(event)!=EVENT_FIELDS
            or type(event['seconds']) not in (int,float)
            or (event['seconds'],event['kind'])!=expected):
        raise ValueError('定时补给时点或事件字段与累计时钟不符')
    if event['supply_status'] not in ('未切断','已切断','未知'):
        raise ValueError('定时补给连通状态非法')
    pos=event['position']
    if (not isinstance(pos,dict) or set(pos)!={'lat','lng'}
            or supply.coord([pos['lat'],pos['lng']]) is None):
        raise ValueError('定时补给位置无效')


def service_bound(world, unit, action):
    cfg=configuration(world)
    rate=cfg['resupply_work_per_hour'] if action=='resupply' else cfg['passive_work_per_hour']
    return rate*cfg['period_seconds']/3600*formation_parts.scale(unit)


def _event_position(before, original, event, action, seconds, previous_position, previous_time):
    pos=event['position'];when=event['seconds']
    if action!='move' and missions.distance(original,pos)>.05:
        raise ValueError('定时补给不能为原地单位编造异地收货')
    if action=='move' and missions.distance(original,pos)>missions.move_budget(before,original)+.05:
        raise ValueError('定时补给收货位置超出机动预算')
    if action=='move':
        speed=missions.move_budget(before,original)/seconds
        if (missions.distance(original,pos)>speed*when+.05
                or missions.distance(previous_position,pos)>speed*(when-previous_time)+.05):
            raise ValueError('定时补给收货位置超出该时点机动预算，不能提前用完整回合路程')


def warehouse_bound(world, identity):
    cfg=configuration(world)
    return cfg['warehouse_tons_per_hour'][identity]*cfg['period_seconds']/3600


def cargo_mass(world, food, ammo, received):
    rules=world['mission']['definition']['combined_rules']
    equivalent=food*world['mission']['definition']['supply_distribution']['food_mass_share']
    equivalent+=ammo*(1-world['mission']['definition']['supply_distribution']['food_mass_share'])
    return equivalent*rules['ton_per_supply_unit']+sum(received.get(k,0)*rules['cargo_mass_tons'][k] for k in CLASSIFIED)


def candidate_limits(before, ledger, orders, seconds):
    """Conditional bounds at declared event positions, never an allocation.

    A malformed unit does not hide another unit's independent capacity. Known
    control needs a complete event-position grid; it never guesses a missing
    moving enemy or a targeted enemy's survival. Dependent nutrition remains the
    responsibility of full validate_ledger, including after these facts return.
    """
    from collections import Counter
    constraints=[];unavailable=[]
    def unknown(unit,reason):unavailable.append(dict(unit=unit,reason=reason))
    if (not isinstance(ledger,dict) or set(ledger)!={'version','units'}
            or ledger.get('version')!=receipt_version(before) or not isinstance(ledger.get('units'),list)):
        unknown(None,'定时补给账缺失或格式未知，不能确定事件字段路径')
        return constraints,unavailable
    units={u['name']:(team,u) for team,u in missions.units(before)}
    rows=ledger['units'];counts=Counter(r.get('unit') for r in rows if isinstance(r,dict) and isinstance(r.get('unit'),str))
    times=event_times(before,seconds);actions={o['unit']:o.get('action','hold') for o in orders}
    valid={};warehouses={}
    for index,row in enumerate(rows):
        name=row.get('unit') if isinstance(row,dict) else None
        if not isinstance(name,str) or name not in units or counts[name]!=1:
            unknown(name if isinstance(name,str) else None,'没有唯一登记单位，不能猜测定时事件字段路径');continue
        if set(row)!=_unit_fields(before) or not isinstance(row['events'],list) or len(row['events'])!=len(times):
            unknown(name,'定时事件缺失、重复或多余，不能猜测时点路径');continue
        try:
            original=units[name][1];previous_position=original;previous_time=0
            for event,expected in zip(row['events'],times):
                _event_shape(event,expected)
                _event_position(before,original,event,actions.get(name,'hold'),seconds,previous_position,previous_time)
                previous_position=event['position'];previous_time=event['seconds']
        except (ValueError,KeyError,TypeError) as error:
            unknown(name,str(error));continue
        team,unit=units[name];node=supply.bound_node(before,team,unit)
        valid[name]=(index,row)
        for event_index,event in enumerate(row['events']):
            if event['kind']!='delivery':continue
            prefix=f'/supply_schedule_ledger/units/{index}/events/{event_index}'
            actual_mass=None
            try:
                for key in ('food_received','ammo_received'):_number(event[key])
                received=event['received']
                if (not isinstance(received,dict) or set(received)-set(CLASSIFIED)
                        or any(type(v)is not int or v<0 for v in received.values())):
                    raise ValueError('定时补给分类物资须为已登记的非负整数')
                actual_mass=cargo_mass(before,event['food_received'],event['ammo_received'],received)
                if not math.isfinite(actual_mass):raise ValueError('货运质量不是有限数')
            except (ValueError,KeyError,TypeError,OverflowError) as error:
                unknown(name,'该事件实际货量未知：'+str(error))
            constraints.append(dict(kind='delivery_capacity',unit=name,seconds=event['seconds'],
                event_path=prefix,maximum_each_work=service_bound(before,unit,actions.get(name,'hold')),
                maximum_mass_tons=transport_bound(before,unit,event['position']),actual_mass_tons=actual_mass,
                scope='分别限制food_received与ammo_received及全部接收货物总吨位；最大值不是必须到货量，取决于当前声明位置，不能替代完整预览。'))
            key=(node['id'],event['seconds'])
            shared=warehouses.setdefault(key,dict(kind='warehouse_capacity',source_node_id=node['id'],
                seconds=event['seconds'],maximum_mass_tons=warehouse_bound(before,node['id']),
                delivery_paths=[],scope='同仓同周期所有单位共享上限；不分配或选择任何单位到货量。'))
            shared['delivery_paths'].append(prefix)
    complete=len(valid)==len(units) and len(rows)==len(units)
    constraints.extend({**row,'complete_member_paths':complete} for row in warehouses.values())
    if complete:
        try:cuts=list(_known_cuts(before,rows,orders))
        except (ValueError,KeyError,TypeError) as error:
            unknown(None,'时序控制依赖未确定：'+str(error));cuts=[]
        for name,event_index,when,blocker in cuts:
            index=valid[name][0];prefix=f'/supply_schedule_ledger/units/{index}/events/{event_index}'
            constraints.append(dict(kind='known_route_cut',unit=name,seconds=when,blocker=blocker,
                status_path=prefix+'/supply_status',disallowed_status='未切断',
                allowed_zero_receipt_statuses=['已切断','未知'],
                zero_delivery_paths=[prefix+'/food_received',prefix+'/ammo_received'],
                classified_received_path=prefix+'/received',
                scope='只按当前声明事件位置和现有存活必要界判定；上述粮弹与分类接收值须为0，不生成修订或完整回执。'))
    else:unknown(None,'事件位置网格不完整，不能猜测全体敌军时序控制；独立容量事实仍可读取')
    constraints.sort(key=lambda row:row['kind']!='known_route_cut')
    return constraints,unavailable


def validate_ledger(before, ledger, orders, seconds, *, after=None,work_activity=None):
    """Check chronological gross accounts; never allocate or modify the world.

    Events debit intervals before end-of-interval arrivals. A final settlement
    always follows the last arrival, including at the same clock instant.
    """
    cfg = configuration(before)
    if cfg is None:
        if ledger is not None: raise ValueError('旧模型不得提交定时补给回执')
        return None
    validate_config(cfg, [n['id'] for n in before['supply_nodes']])
    if (not isinstance(ledger, dict) or set(ledger) != {'version', 'units'}
            or ledger['version'] != receipt_version(before) or not isinstance(ledger['units'], list)):
        raise ValueError('必须提交完整定时补给supply_schedule_ledger')
    old = {u['name']: (team, u) for team, u in missions.units(before)}
    rows = ledger['units']; names = [r.get('unit') for r in rows if isinstance(r, dict)]
    if (len(rows) != len(old) or len(names) != len(rows) or any(not isinstance(k,str) for k in names)
            or len(set(names)) != len(names) or set(names) != set(old)):
        raise ValueError('定时补给回执须唯一覆盖双方全部单位')
    times = event_times(before, seconds); actions = {o['unit']: o for o in orders}
    split = before['mission']['definition']['supply_distribution']
    rules = before['mission']['definition']['combined_rules']; nutrition = before['mission']['definition']['support_dynamics']
    nodes = {n['id']: copy.deepcopy(n) for n in before['supply_nodes']}
    pools = {team: {k: 0 for k in CLASSIFIED} for team in ('red','blue')}
    budgets = {(identity,t): 0.0 for identity in nodes for t,kind in times if kind=='delivery'}
    physical=ledger['version']==PHYSICAL_VERSION
    if work_activity is not None and (not physical or not isinstance(work_activity,dict)
            or not work_activity or not set(work_activity)<=set(old)):
        raise ValueError('劳动保障必须绑定物理补给版本及明确的当前单位')
    checked = {}
    for item in rows:
        if set(item) != _unit_fields(before) or not isinstance(item['events'],list) or len(item['events']) != len(times):
            raise ValueError('定时补给事件缺失、重复或多余')
        name = item['unit']; team, original = old[name]; u = copy.deepcopy(original)
        scale = formation_parts.scale(u); node = supply.bound_node(before,team,u)
        action = actions.get(name,{}).get('action','hold'); last = 0
        previous_position=original;previous_time=0
        food = u['logistics']['food']*scale; ammo = u['logistics']['ammo']*scale
        goods = {k:u['formation'][k] for k in CLASSIFIED}
        total = dict(food_received=0.0,ammo_received=0.0,ammo_spent=0.0,delivery=0.0,transport_tons=0.0,
                     received={k:0 for k in CLASSIFIED},spent={k:0 for k in CLASSIFIED if not physical or k!='fuel_liters'})
        receipt = {k:0 for k in sd.RECEIPT_FIELDS}
        intervals=None;fuel=None
        if physical:
            from . import sustainment_intervals, timed_fuel, motion_state
            for event,expected in zip(item['events'],times):
                _event_shape(event,expected)
                received=event['received']
                if (not isinstance(received,dict) or set(received)-set(CLASSIFIED)
                        or any(type(v) is not int or v<0 for v in received.values())):
                    raise ValueError('定时补给分类物资须为已登记的非负整数')
            arrivals=[{k:e[k] for k in ('seconds','kind','food_received')} for e in item['events']]
            intervals=sustainment_intervals.validate(nutrition,original,seconds,item['nutrition_segments'],
                events=arrivals,load_probe=seconds==.001,
                **({'work_activity':work_activity[name]}if work_activity and name in work_activity else {}))
            receipt=intervals['summary']
            credits=[e['received'].get('fuel_liters',0)*motion_state.SCALE if isinstance(e['received'],dict) else None for e in item['events']]
            fuel=timed_fuel.validate(motion_state.fuel_load(original),item['fuel_timeline'],times,
                expected_received_microliters=credits)
        for index,(event,(when,kind)) in enumerate(zip(item['events'],times)):
            _event_shape(event,(when,kind))
            pos=event['position']
            _event_position(before,original,event,action,seconds,previous_position,previous_time)
            previous_position=pos;previous_time=when
            if physical:
                boundary=intervals['events'][index];food=boundary['food_before']
                u['personnel']['current']=boundary['people']
            else:
                u['logistics']['food']=food/scale
                r=sd.expected(nutrition,u,action,when-last);last=when
                food-=r['consumed']
                u['sustainment'].update({k:r[k] for k in ('shortage_hours','noncombat_remainder')})
                u['personnel']['current']-=r['noncombat_delta']
                for key in ('demand','consumed','unmet','noncombat_delta'):receipt[key]+=r[key]
                for key in ('shortage_hours','noncombat_remainder','fatigue_floor'):receipt[key]=r[key]
            for key in ('food_received','ammo_received','ammo_spent'):_number(event[key])
            if event['ammo_spent']>ammo+1e-6:raise ValueError('定时补给不能用后续到货支付此前射击')
            ammo-=event['ammo_spent'];total['ammo_spent']+=event['ammo_spent']
            received,spent=event['received'],event['spent']
            for values in (received,spent):
                if not isinstance(values,dict) or set(values)-set(CLASSIFIED) or any(type(v) is not int or v<0 for v in values.values()):
                    raise ValueError('定时补给分类物资须为已登记的非负整数')
            if physical and 'fuel_liters' in spent:
                raise ValueError('连续机动耗油必须使用微升时间账，不得用整升桶差替代')
            for key in CLASSIFIED:
                used=spent.get(key,0);got=received.get(key,0)
                if used>goods[key]:raise ValueError('定时补给分类物资先消耗后到货，不能透支')
                goods[key]+=got-used;total['received'][key]+=got;pools[team][key]+=got
                if key in total['spent']:total['spent'][key]+=used
            f,a=event['food_received'],event['ammo_received']
            equivalent=f*split['food_mass_share']+a*(1-split['food_mass_share'])
            mass=cargo_mass(before,f,a,received)
            if kind=='settlement' and (f or a or any(received.values())):
                raise ValueError('定时补给轮末结算不得额外配送')
            if mass and (event['supply_status']!='未切断' or not u['personnel']['current']):
                raise ValueError('定时补给断线或无可用人员却声明到货')
            if f>sd.food_capacity(nutrition,original)*scale-food+1e-6 or a>100*scale-ammo+1e-6:
                raise ValueError('定时补给到货超过收货时库存容量')
            work=service_bound(before,original,action)
            if max(f,a)>work+1e-6 or mass>transport_bound(before,original,pos)+1e-6:
                raise ValueError('定时补给超过周期服务或运输吨位上限')
            if kind=='delivery':
                budgets[(node['id'],when)]+=mass
                if budgets[(node['id'],when)]>warehouse_bound(before,node['id'])+1e-6:
                    raise ValueError('定时补给多单位争用超过同仓周期装卸能力')
            for key,amount in (('food',f),('ammo',a)):
                nodes[node['id']]['commodities'][key]-=amount
                if nodes[node['id']]['commodities'][key]<-1e-6:raise ValueError('定时补给仓库重复出货或库存不足')
            food+=f;ammo+=a
            for key,value in (('food_received',f),('ammo_received',a),('delivery',equivalent),('transport_tons',mass)):total[key]+=value
        checked[name]={**total,'source_node_id':node['id'],'nutrition':receipt,'food_after':food/scale,'ammo_after':ammo/scale,
                       'events':copy.deepcopy(item['events']),**({'fuel_timeline':fuel} if physical else {})}
    # Other classified goods are explicitly team pools, not fictitious site stock.
    source=before.get('combined_arms',{}).get('depots') or before.get('_schedule_pools')
    if source:
        for team in pools:
            if any(pools[team][k]>source[team][k] for k in CLASSIFIED):raise ValueError('定时补给分类阵营仓库透支')
    _validate_known_control(before,rows,orders,after)
    return checked


def instruction(world, seconds):
    import json
    cfg=configuration(world)
    if not cfg:return ''
    nutrition=world['mission']['definition']['support_dynamics']
    if receipt_version(world)==PHYSICAL_VERSION:
        from . import sustainment_intervals,timed_fuel
        return ('\n连续机动定时补给回执版本='+PHYSICAL_VERSION+'；配置='+json.dumps(cfg,ensure_ascii=False)+
            '；严格时点='+json.dumps(event_times(world,seconds),ensure_ascii=False)+
            '。supply_schedule_ledger仅含version和units，每个单位仅含unit、events、nutrition_segments、fuel_timeline。'
            'events沿用seconds、kind、supply_status、position:{lat,lng}、food_received、ammo_received、ammo_spent、received、spent；'
            'received中的fuel_liters保持整升，spent禁止fuel_liters，不能用整升桶差表示耗油。'
            'nutrition_segments每段字段='+json.dumps(sustainment_intervals.FIELDS,ensure_ascii=False)+
            '；从0毫秒连续覆盖全轮，单段不超过10000毫秒，并在每次到货时分段；moving_ms为实际移动时间，等待或已到达时间不按行军计粮。'
            '需求=本段静止需求×(1+moving_ms/段毫秒×(move_factor-1))，静止需求采用已配置的按人数或编组粮秣模型；'
            '消耗、缺粮债、非战斗失能余量和疲劳微点必须与同一物理时钟及库存连续，人员不能在后段自行增加。'
            'fuel_timeline以微升计量，仅含version:'+timed_fuel.VERSION+'、unit:microliter、events；每个事件为seconds、kind及'+
            json.dumps(timed_fuel.FIELDS,ensure_ascii=False)+'；每次received_microliters=同事件received.fuel_liters×1000000。'
            '所有消耗先从上次库存扣除，再入本次到货；同秒delivery后有settlement，后者不得到货，也不得支付过去的消耗。'
            '粮食按收货时剩余携行容量限制；可用运输装备、人员、装卸与往返距离共同限制货量；'
            '同仓同周期共用warehouse_tons_per_hour×period_seconds/3600，不得按单位倍增；粮弹从绑定仓库、分类物资从阵营池扣库。'
            '仍存续且已到场敌军的控制区切断直连补给时，必须记录已切断且本次到货为0。'
            '这是现有周期吞吐服务假设，不代表具名车队在途或历史道路、口粮和装备效能已标定。')
    formula=('每段需求=段初可用人数×ration_kg_per_person_day×段小时/24/food_kg_per_work，不乘编组份额；'
        if nutrition['version']==sd.PERSONNEL_VERSION else '每段需求=food_work_per_hour×段小时×编组份额；')
    return ('\n定时补给启用'+json.dumps(cfg,ensure_ascii=False)+'。本轮严格时点(kind=delivery为固定周期到货，settlement为轮末最后结算)='+
        json.dumps(event_times(world,seconds),ensure_ascii=False)+'。提交supply_schedule_ledger={version:"'+VERSION+'",units:[{unit,events:[{seconds,kind,supply_status,position:{lat,lng},food_received,ammo_received,ammo_spent,received:{},spent:{}}]}]}。'
        '各事件先结算距上条事件期间的耗粮、缺粮债、非战斗失能及ammo_spent/分类spent，再记本时点到货。最后settlement总在delivery后，即使秒数相同；它不得到货。不能用未来到货支付早前费用。'
        '本时点失能结算后可用人数为0的单位不能收货；双方先结算同一时点的失能，再检查控制。'
        'position必须对应本时点位置；移动按已过时长和相邻事件间隔限速，不能提前使用全轮路程。'
        '已到场、仍存续敌军的已登记ground_control_radius_km控制区若覆盖绑定仓库至收货点的直连链路，必须声明已切断且到货为0；不能忽略静止或存续的受击敌军，也不能猜测其死亡时刻。'
        '粮秣参数='+json.dumps(world['mission']['definition']['support_dynamics'],ensure_ascii=False)+'。'
        +formula+'move另乘move_factor，消耗=min(需求,段初粮食工作量)。'
        '未供粮小时=段小时×(1-消耗/需求)，供粮小时=段小时-未供粮小时；无可用人员则该段需求与经过小时为0。'
        '恢复后债=max(0,旧shortage_hours-供粮小时×recovery_hours_per_fed_hour)，新债=恢复后债+未供粮小时。'
        '暴露=max(0,新债-incapacity_after_hours)-max(0,恢复后债-incapacity_after_hours)，负荷=旧noncombat_remainder+暴露×committed×incapacity_fraction_per_hour；'
        '新增非战斗失能=min(当段可用人数,floor(负荷+1e-9))，余量=max(0,负荷-floor(负荷+1e-9))；逐段保留债和余量。'
        '疲劳不低于各段floor(min(100,新债×shortage_fatigue_per_hour))，失能不记阵亡。'
        '总sustainment_ledger={version:"'+nutrition['version']+'",units:[{unit,demand,consumed,unmet,shortage_hours,noncombat_remainder,fatigue_floor,noncombat_delta}]}；'
        '需求/消耗/未满足/非战斗新增分段求和，其余取最后段；unit_updates.sustainment提交version、最后债和余量，人员失能及期末粮弹必须对应。'
        'resource_ledger填各事件到货/消耗总和，期末为轮初+总到货-总消耗；容量按各次到货前余额核对，不是只看轮初空余。'
        '每周期每类粮弹上限=本行动work_per_hour×period_seconds/3600×编组份额。运输吨位上限=可用运输单元×单车吨位×初始人员可用比×周期小时/(loading_hours+2×仓到收货地距离/convoy_speed_kph)。'
        '同仓所有单位每周期共用warehouse_tons_per_hour×周期小时；其他分类物资从阵营池扣库，粮弹从各自绑定仓库扣库。这里是已运行周期服务的聚合吞吐假设，不含具名车队在途或历史道路标定。'+sd.deferred_instruction(world))
