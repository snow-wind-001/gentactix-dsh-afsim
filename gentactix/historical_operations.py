"""Bind actual historical IDs to explicit calculation inputs, without transitions.

Facts remain frozen and separate. Existing mission guards and native WSF rules
own execution; this module never imports a teaching scenario or computes losses.
"""
import copy
import calendar
from datetime import datetime, timedelta
import json
import math
import re
from pathlib import Path
from . import historical_initial, combined_arms, missions, sim_clock, battle_scope, anchors, air_assets
from .unit_types import classify_unit

FORMAT = 'historical-operation-1'
SOURCE = '具名历史单位参数化输入；缺载数值、部署和武器效能为显式估计，不是历史实到量或真实战损标定'
FORMATION_FIELDS = {'role','fatigue','suppression','entrenchment','dispersion_km2','protection',
                    'fuel_liters','spares','materials','shells','aa_rounds','reload_remaining',
                    'intel_age_min','intel_confidence','signal'}
ACTOR_FIELDS = {'personnel','equipment','position','type','speed','attack_range_m',
                'ground_control_radius_km','logistics','formation','assumption'}


def _fields(value, expected, message):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(message)


def _text(value, message):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(message)


def _number(value, low=0, high=100000000, integer=False, *, label=None):
    if (type(value) not in ((int,) if integer else (int,float)) or not math.isfinite(value)
            or not low <= value <= high):
        detail='' if label is None else f'（{label} 允许范围{low:g}至{high:g}；收到{repr(value)[:100]}）'
        raise ValueError('参数须为有界有限数值，整数计数不能使用布尔值或小数'+detail)


def _point(value):
    _fields(value, {'lat','lng'}, '部署须为明确的十进制度lat/lng')
    _number(value['lat'], -90, 90); _number(value['lng'], -180, 180)


def aviation_partition(snapshot, force_scope='phase'):
    """Select nonoverlapping aviation IDs; campaign presence stays an estimate."""
    if force_scope not in ('phase','campaign'):raise ValueError('未知航空编制范围')
    historical_initial.restore(snapshot)
    units={u['id']:u for u in snapshot['definition']['units']};candidates=set()
    for unit in units.values():
        if unit['role']!='aviation':continue
        if force_scope=='campaign':
            if any(p['status'] in ('reported_present','campaign_participant') for p in unit['presence']):
                candidates.add(unit['id'])
            continue
        status=next((p['status'] for p in unit['presence'] if p['phase_id']==snapshot['phase_id']),'unverified')
        if status in ('later_participant','outside_scope'):continue
        if status!='reported_present':
            raise ValueError('历史海空单位本阶段参战尚未核定，不能绑定航空资源：'+unit['id'])
        candidates.add(unit['id'])
    parents=set()
    for identity in candidates:
        parent=units[identity]['parent_id']
        while parent:
            if parent in candidates:parents.add(parent)
            parent=units[parent]['parent_id']
    return [identity for identity in units if identity in candidates-parents]


def _air_ids(snapshot,parameters):
    scope=parameters.get('campaign_scope')
    return aviation_partition(snapshot,'campaign' if isinstance(scope,dict) and not scope.get('window') else 'phase')


def _air_definition(snapshot, parameters, *, _frozen=False):
    ids=_air_ids(snapshot,parameters)
    if not ids:
        if 'aviation' in parameters:raise ValueError('当前阶段没有已核定航空部队，不能迁入其他想定飞机')
        return None
    inputs=parameters.get('aviation')
    _fields(inputs,ids,'航空参数必须覆盖本阶段不重叠航空部队，不能漏配或虚构航空部队')
    units={u['id']:u for u in snapshot['definition']['units']};pools={}
    for identity in ids:
        p=inputs[identity];unit=units[identity]
        _fields(p,{'initial','entry','rules','assumption'}|({'availability'} if 'availability' in p else set()),
                '航空计算字段非法；身份、阵营、来源由冻结档案绑定')
        scope=parameters.get('campaign_scope')
        if scope and not scope.get('window') and not _frozen:
            if 'availability' not in p:raise ValueError('会战航空累计参战身份须显式声明可用时段，不能默认开局到场')
            from . import air_availability
            air_availability.validate(p['availability'])
            start=air_availability.timestamp(parameters['clock']['start'])
            end=air_availability.timestamp(scope['planning_end'])
            if not start<=air_availability.timestamp(p['availability']['start'])<end:
                raise ValueError('会战航空估计入场时间须位于本次规划范围内；事实参战时点仍未知')
        pools[identity]={**copy.deepcopy(p),'name':unit['name'],'team':unit['team'],
            'historical_unit_id':identity,'evidence':copy.deepcopy(unit['evidence'])}
    value={'format':air_assets.FORMAT,'pools':pools};air_assets.validate_definition(value)
    return value


def partition(snapshot, force_scope='phase', *, window=None):
    historical_initial.restore(snapshot)
    if force_scope == 'campaign':
        from . import campaign_scope
        return campaign_scope.select(snapshot,window)
    if window is not None:raise ValueError('会战窗口须使用会战编制范围')
    if force_scope != 'phase':raise ValueError('未知编制范围')
    rows = snapshot['definition']['units']
    attendance = {u['id']: next((r['status'] for r in u['presence']
                                if r['phase_id'] == snapshot['phase_id']), 'unverified') for u in rows}
    excluded={'later_participant','outside_scope'}
    aviation_partition(snapshot)
    unsupported = [u['id'] for u in rows if u['role']=='naval' and attendance[u['id']] not in excluded]
    if unsupported:
        raise ValueError('历史海空单位尚需独立资源模型绑定，不能静默丢弃：'+', '.join(unsupported))
    units = {u['id']:u for u in rows}
    candidates = {u['id'] for u in rows if u['role'] in ('formation','support')
                  and attendance[u['id']] not in excluded}
    uncertain = [u['name'] for u in rows if u['id'] in candidates
                 and attendance[u['id']] != 'reported_present']
    if uncertain:
        raise ValueError('当前阶段参战尚未核定，不能把累计参战名单自动部署到场：'
                         + '、'.join(uncertain[:8]) + ('等' if len(uncertain) > 8 else ''))
    parents = set()
    for identity in candidates:
        parent = units[identity]['parent_id']
        while parent:
            if parent in candidates: parents.add(parent)
            parent = units[parent]['parent_id']
    selected = candidates - parents
    phase=next(p for p in snapshot['definition']['phases'] if p['id']==snapshot['phase_id'])
    interaction=phase.get('interaction')
    if interaction:
        if not selected or {units[i]['team'] for i in selected} != set(interaction['active_teams']):
            raise ValueError('非接敌转移的在场单位超出声明范围或为空，不能静默丢弃对手')
    elif {units[i]['team'] for i in selected} != {'red','blue'}:
        raise ValueError('现有历史档案缺少双方可绑定的战斗单位，不能把指挥机关当作步兵')
    return [u['id'] for u in rows if u['id'] in selected]


def objective_guidance(snapshot):
    """Read the version's pinned guidance, never silently borrow the latest row."""
    data=json.loads((Path(__file__).resolve().parent.parent/'data'/'historical_objective_bindings.json').read_text())
    version=data['profiles'].get(snapshot['profile_id'],{}).get(snapshot['version'])
    if version is None:raise ValueError('该历史版本的目标资料尚未绑定，请先登记版本化目标来源')
    if (version['initial_definition_hash'] != snapshot['definition_hash']
            or historical_initial.digest(snapshot['definition']) != snapshot['definition_hash']):
        raise ValueError('目标资料与完整历史初态内容不一致；不能仅凭相同版本号借用目标来源')
    row=version['phases'].get(snapshot['phase_id'])
    if row is None:return None
    if row.get('unavailable_reason'):raise ValueError(row['unavailable_reason'])
    sources=snapshot['definition']['sources']
    if any(i not in sources or historical_initial.digest(sources[i])!=digest for i,digest in row['source_hashes'].items()):
        raise ValueError('目标来源与该历史版本的固定来源不一致，不能借用其他版本来源')
    value=copy.deepcopy(row['guidance'])
    value['sources']=[{**copy.deepcopy(snapshot['definition']['sources'][e['source_id']]),
                      'id':e['source_id'],'locator':e['locator']} for e in value.pop('evidence')]
    value['binding']={'initial_version':snapshot['version'],
        'initial_definition_hash':version['initial_definition_hash'],
        'guidance_hash':historical_initial.digest(row)}
    return value


def interaction_scope(snapshot):
    phase=next(p for p in snapshot['definition']['phases'] if p['id']==snapshot['phase_id'])
    return copy.deepcopy(phase.get('interaction'))


def configuration_template(snapshot, force_scope='phase', *, window=None, termination_mode=None):
    """An unfilled calculation contract, never an executable teaching seed."""
    identities = partition(snapshot,force_scope,window=window)
    air_ids=aviation_partition(snapshot,force_scope if window is None else 'phase')
    battle = snapshot['definition']['battle']
    era = 'ancient' if battle == '长平之战' else 'long_march' if battle.startswith('红军长征-') else 'korea' if battle.startswith('抗美援朝-') else 'ww2'
    note = '待说明缺载字段的估计依据；模型规则尚未经历史效能标定'
    guidance=objective_guidance(snapshot)
    profile=guidance['profile'] if guidance else None
    team=guidance['team'] if guidance else 'red'
    actors = {}
    for unit in snapshot['definition']['units']:
        if unit['id'] not in identities:
            continue
        position = unit['facts']['position']['value']
        point = {k: position[k] for k in ('lat', 'lng')} if position and position['phase_id'] == snapshot['phase_id'] else {'lat': None, 'lng': None}
        actors[unit['id']] = {'personnel': unit['facts']['personnel']['value'], 'position': point,
            'equipment': {k: None for k in combined_arms.RULES['categories']},
            'type': None, 'speed': None, 'attack_range_m': None, 'ground_control_radius_km': None,
            'logistics': {'food': None, 'ammo': None}, 'formation': {**{key: None for key in sorted(FORMATION_FIELDS)},'motorized':None},
            'assumption': note}
    point = {'lat': None, 'lng': None}
    result={'format': FORMAT, 'phase_id': snapshot['phase_id'],
        'clock': {'start': None, 'time_step': '30分钟', 'assumption': note},
        'area': {'center': copy.deepcopy(point), 'radius_km': None, 'terrain_factor': None, 'assumption': note},
        'actors': actors,
        'rules': {**copy.deepcopy(combined_arms.RULES), 'era': era, 'air_support': False, 'motorized': era not in ('ancient','long_march'),
                  'goal_profile': profile, 'required_survivors': None, 'convoy_km_per_turn': None, 'bridge_enabled': False},
        'support': {team: {'position': copy.deepcopy(point), 'stock': None,
            'inventory': {k: None for k in ('fuel_liters','spares','materials','shells','aa_rounds')}, 'assumption': note} for team in ('red','blue')},
        'facility': {'id': 'calculation-hub', 'name': '计算汇总点（非史实桥梁）', **point,
                     'progress': 0, 'integrity': 0, 'materials': 0, 'capacity': 0, 'used': 0},
        'goal': {'team':team,'profile': profile, 'objective': copy.deepcopy(point), 'exit': copy.deepcopy(point),
                 'radius_km': None, 'deadline_turn': None, 'required_turns': None, 'required_survivors': None,
                 'description': None, 'assumption': note}, 'assumptions': note,
        **({'aviation':{identity:{'initial':{'committed':None,'ordnance':None,'fuel':None},
            'entry':copy.deepcopy(point),'rules':copy.deepcopy(air_assets.DEFAULT_RULES),'assumption':note,
            **({'availability':{'version':'air-availability-1','start':None,'end':None,
                'assumption':'待明确估计可用起止；累计参战不是同日到场，空end才表示持续可用。'}}
                if force_scope=='campaign' and window is None else {})}
            for identity in air_ids}} if air_ids else {})}
    phase=next(p for p in snapshot['definition']['phases'] if p['id']==snapshot['phase_id'])
    if phase['date']['label'].startswith('公元前'):
        result['clock'].update(mode='relative', start=phase['date']['label'],
            assumption='保留史料阶段标签；T+为计算经过时间，不换算为不存在的精确公历起点。')
    if phase.get('interaction'):
        for team,support in result['support'].items():
            if team not in phase['interaction']['active_teams']:
                support.update(stock=0,inventory={key:0 for key in support['inventory']},
                    assumption='本阶段无此方计算单位；格式占位不生成仓库实体，位置仅作参数占位。')
    if any(r['kind']=='formation_crossing' for r in phase.get('process_requirements',[])):
        from . import crossings
        result['facility']['crossing_model']=crossings.configuration_template(note)
        result['rules']['bridge_enabled']=True
    from . import campaign
    if force_scope=='campaign':
        from . import campaign_scope
        result['campaign_scope']=campaign_scope.template(snapshot,window)
        if window:
            result['clock'].update(start=window['definition']['bounds']['start'],
                assumption=window['definition']['bounds']['note'])
    else:
        from . import campaign_scope
        rows=campaign_scope.local_coverage(snapshot)
        if rows:
            result['oob_coverage']={'version':campaign_scope.LOCAL_VERSION,'remainders':{
                r['parent_id']:{'policy':None,'assumption':'待明确仅投入所列下级，还是有证据的完整覆盖；未知余部不得填零。'} for r in rows}}
    if campaign.required(snapshot,result):result['campaign']=campaign.template(snapshot,identities)
    if force_scope=='campaign' and phase.get('interaction'):
        if termination_mode!='objectives':
            raise ValueError('非接敌多单位会战范围须显式选择目标完成制；局部转移仍可使用原限时模板')
        from . import campaign_plan
        result['goal']['termination_mode']='objectives'
        result['campaign_plan']=campaign_plan.transfer_template(snapshot,identities)
        result['campaign']['objective']['relief_regions']=[]
        result['campaign']['surrender']['enabled']=False
    if force_scope=='phase' or window is not None:
        from . import initial_command
        opening=initial_command.template(snapshot,window)
        if opening:result['initial_command']=opening
    result['supply_distribution']={'version':'split-stocks-1','food_mass_share':.5,'priority':'food',
        'assumption':'教学运输初值：原补给包拆为各一工作量粮食与弹药，质量份额各半，优先补粮；未经历史重量标定，可编辑并重新验证。'}
    from . import campaign_estimates
    campaign_estimates.prepare(result,window,termination_mode)
    return result


def _validate(snapshot, params, *, actor_ids=None, _frozen=False):
    historical_initial.restore(snapshot)
    _fields(params, {'format','phase_id','clock','area','actors','rules','support','facility','goal','assumptions'}
            |({'aviation'} if _air_ids(snapshot,params) else set())|({'partitions'} if 'partitions' in params else set())
            |({'campaign'} if 'campaign' in params else set())
            |({'campaign_plan'} if 'campaign_plan' in params else set())
            |({'campaign_lifecycle'} if 'campaign_lifecycle' in params else set())
            |({'campaign_scope'} if 'campaign_scope' in params else set())
            |({'oob_coverage'} if 'oob_coverage' in params else set())
            |({'initial_command'} if 'initial_command' in params else set())
            |({'support_dynamics'} if 'support_dynamics' in params else set())
            |({'movement_feedback'} if 'movement_feedback' in params else set())
            |({'fire_accounting'} if 'fire_accounting' in params else set())
            |({'fire_dynamics'} if 'fire_dynamics' in params else set())
            |({'supply_schedule'} if 'supply_schedule' in params else set())
            |({'terrain_model'} if 'terrain_model' in params else set())
            |({'supply_distribution'} if 'supply_distribution' in params else set())
            |({'operation_boundary'} if 'operation_boundary' in params else set()), '历史计算参数字段非法')
    if 'terrain_model' in params:
        from . import terrain_process
        terrain_process.validate(params['terrain_model'], params['area'])
    if 'supply_distribution' in params:
        from . import split_supply
        split_supply.validate_config(params['supply_distribution'])
    if 'support_dynamics' in params:
        from . import support_dynamics
        support_dynamics.validate_binding(params['support_dynamics'],params.get('rules'),params.get('supply_distribution'))
    if 'movement_feedback' in params:
        from . import movement_feedback
        movement_feedback.validate_config(params['movement_feedback'])
    if 'fire_accounting' in params:
        from . import combat_effects
        combat_effects.validate_accounting(params['fire_accounting'])
    if 'fire_dynamics' in params:
        from . import combat_effects
        combat_effects.validate_dynamics(params['fire_dynamics'])
    from . import supply_schedule
    scope=interaction_scope(snapshot)
    supply_schedule.validate_parameters(params,node_ids=[team+'-historical-supply' for team in (scope['active_teams'] if scope else ('red','blue'))])
    aviation=_air_definition(snapshot,params,_frozen=_frozen)
    if params['format'] != FORMAT or params['phase_id'] != snapshot['phase_id']:
        raise ValueError('历史参数格式或初始阶段不一致')
    _text(params['assumptions'], '必须说明估计范围与限制')
    from . import campaign
    from . import campaign_scope
    campaign_scope.validate(snapshot,params,frozen=_frozen)
    campaign_scope.validate_local(snapshot,params)
    from . import initial_command
    initial_command.validate(snapshot,params,frozen=_frozen)
    campaign.validate_parameters(snapshot,params)
    phase = next(p for p in snapshot['definition']['phases'] if p['id']==snapshot['phase_id'])
    relative = phase['date']['label'].startswith('公元前')
    _fields(params['clock'], {'start','time_step','assumption'} | ({'mode'} if relative else set()), '计算时钟字段非法')
    _text(params['clock']['assumption'], '钟点和回合须说明建模依据')
    _text(params['clock']['start'], '计算起点不能为空')
    if relative:
        if (params['clock']['mode'] != 'relative' or params['clock']['start'] != phase['date']['label']
                or phase.get('execution_window')):
            raise ValueError('公元前阶段须保留原阶段标签并使用relative时钟；不能虚构公历日期或绕过日期窗口')
        start = None
    else:
        try:
            start = datetime.fromisoformat(params['clock']['start'])
        except (ValueError, TypeError) as exc:
            raise ValueError('计算起点须为明确日期时间，精度假设另行说明') from exc
        if start.tzinfo is not None: raise ValueError('计算时钟使用已说明的当地时间，不混入时区偏移')
    if any(r['kind']=='formation_crossing' for r in phase.get('process_requirements',[])) and not params.get('facility',{}).get('crossing_model'):
        raise ValueError('本阶段主任务包含编组渡运，必须绑定通道模型，不能退回无河流的普通占点')
    label = phase['date']['label']
    years = [int(v) for v in re.findall(r'(?<!\d)(\d{4})(?:年|-)', label)]
    months = [int(v) for v in re.findall(r'(\d{1,2})月', label)]
    if not relative and years and not min(years)<=start.year<=max(years): raise ValueError('计算年份与所选历史阶段不一致')
    if not relative and months and not min(months)<=start.month<=max(months): raise ValueError('计算月份与所选历史阶段不一致')
    periods = re.findall(r'(?:(\d{4})年)?(\d{1,2})月(?:(\d{1,2})日|([上中下]旬))?',label)
    if not relative and periods and years:
        first,last=periods[0],periods[-1]
        first_year=int(first[0] or years[0]);last_year=int(last[0] or years[-1])
        first_month,last_month=int(first[1]),int(last[1])
        low=int(first[2]) if first[2] else {'上旬':1,'中旬':11,'下旬':21}.get(first[3],1)
        high=int(last[2]) if last[2] else {'上旬':10,'中旬':20}.get(last[3],calendar.monthrange(last_year,last_month)[1])
        if not datetime(first_year,first_month,low).date() <= start.date() <= datetime(last_year,last_month,high).date():
            raise ValueError('计算日期超出所载阶段的月／旬范围')
    if not relative and phase['date']['precision']=='day' and label != start.date().isoformat():
        raise ValueError('计算日期与所选历史阶段不一致')
    sim_clock.duration_seconds(params['clock']['time_step'])
    area = params['area']
    _fields(area, {'center','radius_km','terrain_factor','assumption'}, '计算地域字段非法')
    _point(area['center']); _number(area['radius_km'], .1, 2000); _number(area['terrain_factor'], .1, 10)
    _text(area['assumption'], '地域与部署精度须说明依据')
    if 'operation_boundary' in params:
        from . import operation_boundary
        operation_boundary.validate(params['operation_boundary'],area,
            actors=params['actors'].values() if isinstance(params['actors'],dict) else (),plan=params.get('campaign_plan'))
    if phase.get('geographic_scope'):
        region=phase['geographic_scope']
        if missions.distance(area['center'],region['center'])+area['radius_km']>region['radius_km']+1e-6:
            raise ValueError('计算地域超出当前阶段地域范围；请核对温井、云山等历史地名，不得以全战役范围替代局部阶段')
    actors = params['actors']
    expected=campaign_scope.selected(snapshot,params) if campaign_scope.enabled(params) else partition(snapshot)
    if not isinstance(actors, dict) or set(actors) != set(expected):
        raise ValueError('必须覆盖不重叠的历史战斗单位；不得漏兵、增加指挥机关或同时累计上下级')
    index = {u['id']:u for u in snapshot['definition']['units']}
    if actor_ids is not None and not set(actor_ids)<=set(actors):
        raise ValueError('局部校验引用未知历史单位')
    for identity, actor in actors.items():
        if actor_ids is not None and identity not in actor_ids:continue
        _fields(actor, ACTOR_FIELDS, '历史单位计算字段非法：'+identity)
        _text(actor['assumption'], '每个单位必须解释估计参数')
        _text(actor['type'], '模型兵种不能为空')
        kind = classify_unit(actor['type'])
        if not kind:
            raise ValueError('单位 '+identity+' 的兵种 '+repr(actor['type'])+' 未登记；请使用共享兵种名称或规范ID，如徒步步兵/infantry、坦克装甲兵/armor')
        if kind['id'] in ('command','aviation','naval'):
            raise ValueError('当前参数化地面模型不能把指挥、海空或未登记兵种当作步兵')
        _number(actor['personnel'], 1, 1000000, True)
        _number(actor['speed'], .01, 150); _number(actor['attack_range_m'], 0, 300000)
        _number(actor['ground_control_radius_km'], 0, 100)
        _point(actor['position'])
        if missions.distance(actor['position'], area['center']) > area['radius_km']:
            raise ValueError('单位部署超出已声明计算地域')
        fact = index[identity]['facts']['personnel']['value']
        if fact is not None and actor['personnel'] != fact:
            raise ValueError('已载历史人数不能静默改成估计；须另建合成派生')
        position = index[identity]['facts']['position']['value']
        if position and position['phase_id'] == snapshot['phase_id'] and position['kind'] == 'unit_position':
            if actor['position'] != {k:position[k] for k in ('lat','lng')}:
                raise ValueError('本阶段已载的部队位置不能静默改写')
        if position and position['phase_id']==snapshot['phase_id'] and position['kind']=='deployment_area_reference':
            if missions.distance(actor['position'],position)>position['uncertainty_km']:
                raise ValueError('估计初始位置超出来源部署区域及工作不确定范围：'+identity)
        _fields(actor['equipment'], combined_arms.RULES['categories'], '必须分别给定五类装备')
        for amount in actor['equipment'].values(): _number(amount, 0, 100000, True)
        equipment = index[identity]['facts']['equipment']['value']
        if equipment is not None:
            raise ValueError('有史实装备记载时须先建立分类口径映射，不能覆盖为估计')
        _fields(actor['logistics'], {'food','ammo'}, '必须明确粮弹库存')
        for amount in actor['logistics'].values(): _number(amount, 0, 100)
        from . import support_dynamics
        # Initial partitions inherit this normalized food coverage. Each leaf's
        # committed/scale is the parent total, so its frozen capacity is equal.
        support_dynamics.validate_food_loading(params.get('support_dynamics'),
            {'historical_unit_id':identity,'personnel':{'committed':actor['personnel']},
             'logistics':actor['logistics']})
        form = actor['formation']
        _fields({k:v for k,v in form.items() if k!='motorized'}, FORMATION_FIELDS, '编组展开、状态与保障字段不完整')
        if 'motorized' in form and type(form['motorized']) is not bool:raise ValueError('单位机动方式须明确为布尔值')
        if form['role'] not in ('infantry','armor','support'): raise ValueError('尚未登记该计算兵种')
        for key in ('fatigue','suppression','entrenchment','signal'):
            _number(form[key], 0, 100, True,label=f'actors.{identity}.formation.{key}')
        _number(form['intel_confidence'],0,100,label=f'actors.{identity}.formation.intel_confidence')
        for key in ('fuel_liters','spares','materials','shells','aa_rounds','reload_remaining'):
            _number(form[key], 0, 10000000, True,label=f'actors.{identity}.formation.{key}')
        _number(form['intel_age_min'],0,10000000,label=f'actors.{identity}.formation.intel_age_min')
        _number(form['dispersion_km2'], .001, 10000,label=f'actors.{identity}.formation.dispersion_km2')
        _number(form['protection'], 0, 1,label=f'actors.{identity}.formation.protection')
    cfg, goal = params['rules'], params['goal']
    extra = {'era','air_support','motorized','goal_profile','required_survivors','convoy_km_per_turn','bridge_enabled'}
    _fields(cfg, set(combined_arms.RULES)|extra, '封闭运算规则字段非法')
    for key, reference in combined_arms.RULES.items():
        value = cfg[key]
        if isinstance(reference, str) or isinstance(reference, list):
            if value != reference: raise ValueError('运算模型版本或装备类别不一致')
        elif isinstance(reference, dict):
            _fields(value, reference, '分类物资质量表字段非法')
            for name,number in value.items(): _number(number,label=f'rules.{key}.{name}')
        else: _number(value, integer=type(reference) is int,label=f'rules.{key}')
    if not _frozen:
        for identity, actor in actors.items():
            if actor_ids is not None and identity not in actor_ids:continue
            kind = classify_unit(actor['type'])
            if kind['id'] in ('rocket','sp_artillery','towed_artillery','mortar') and actor['attack_range_m'] > cfg['direct_range_m']:
                raise ValueError('单位 '+identity+' 的炮兵自卫直射范围超出本局direct_range_m上限；火炮间接射程应填写rules.artillery_range_m，使用bombard/suppress，不得用火炮射程扩大小武器fire范围')
    if cfg['era'] not in ('ancient','long_march','ww2','korea') or any(type(cfg[k]) is not bool for k in ('air_support','motorized','bridge_enabled')):
        raise ValueError('时代或能力开关非法')
    battle = snapshot['definition']['battle']
    expected_era = 'ancient' if battle=='长平之战' else 'long_march' if '红军长征-' in battle else 'korea' if battle.startswith('抗美援朝-') else 'ww2'
    if cfg['era'] != expected_era: raise ValueError('历史初态不能切换战争时代；应另建合成派生')
    if expected_era=='ancient' and any(p['equipment'][k] for p in actors.values() for k in ('armor','artillery','air_defense')):
        raise ValueError('当前古代模型不能配发现代装备')
    for key in ('ton_per_supply_unit','transport_tons_per_truck','shells_per_supply_unit','aa_rounds_per_supply_unit'):
        _number(cfg[key], .000000001)
    for value in cfg['cargo_mass_tons'].values(): _number(value, .000000001)
    if cfg['air_support'] and aviation is None: raise ValueError('历史航空资源尚未绑定，不能使用固定教学飞机池')
    _number(cfg['convoy_km_per_turn'], 0, 300, label='rules.convoy_km_per_turn')
    _number(cfg['required_survivors'], 1, len(actors), True)
    goal_fields={'profile','objective','exit','radius_km','deadline_turn','required_turns','required_survivors','description','assumption'}
    _fields(goal,goal_fields|({k for k in ('team','termination_mode') if k in goal} if isinstance(goal,dict) else set()),'程序目标字段非法')
    from . import mission_termination
    objectives=mission_termination.objective_driven(goal)
    owner=goal.get('team','red')
    if owner not in ('red','blue'):raise ValueError('目标方须为red或blue')
    interaction=phase.get('interaction')
    if interaction and (owner not in interaction['active_teams'] or goal['profile'] not in ('crossing','breakout')):
        raise ValueError('非接敌转移须由在场方完成渡运或转移目标，不能靠无敌军自动赢得交战目标')
    if owner=='blue' and goal['profile'] not in ('assault','delay','breakout','crossing'):
        raise ValueError('蓝方目标当前仅支持地域夺控、迟滞与突围；其他目标尚未按方别绑定')
    if goal['profile'] not in ('assault','delay','breakout','rail','underground','reception','crossing') or cfg['goal_profile'] != goal['profile']:
        raise ValueError('目标与计算规则类型不一致')
    if goal['profile']=='crossing' and not params.get('facility',{}).get('crossing_model'):raise ValueError('渡运目标必须配置有限河线、两岸与吞吐模型')
    _point(goal['objective']); _point(goal['exit']); _number(goal['radius_km'], .01, area['radius_km'])
    for key in ('deadline_turn','required_turns'): _number(goal[key], 1, 100000, True)
    if 'team' in goal:
        if not objectives and goal['profile'] not in ('delay','underground') and goal['required_turns']>goal['deadline_turn']:
            raise ValueError('连续控制回合数不能大于截止回合')
        points=['objective']+(['exit'] if goal['profile'] in ('delay','breakout') else [])
        if any(missions.distance(goal[key],area['center'])>area['radius_km']+1e-6 for key in points):
            raise ValueError('目标或出口超出计算地域，单位无法在有效战区内完成目标')
    if phase.get('execution_window'):
        window_start=phase['execution_window'].get('start')
        if window_start and start<datetime.fromisoformat(window_start):
            raise ValueError('计算起点早于本阶段计算窗口；不能把后续单位提前到场')
        window_end=datetime.fromisoformat(phase['execution_window']['end'])
        if start>=window_end:
            raise ValueError('计算起点须在本阶段计算窗口内；开放延伸不能改写历史初态起点')
        end=start+timedelta(seconds=sim_clock.duration_seconds(params['clock']['time_step'])*goal['deadline_turn'])
        if not objectives and end>window_end:
            raise ValueError('初态和截止回合超出当前阶段计算窗口；后续援军或兵种尚未绑定，须缩短窗口或选择已支持阶段')
    _number(goal['required_survivors'], 1, sum(index[i]['team']==owner for i in actors), True)
    if cfg['required_survivors'] != goal['required_survivors']: raise ValueError('存续门槛不一致')
    for key in ('description','assumption'): _text(goal[key], '目标和估计依据不能为空')
    _fields(params['support'], {'red','blue'}, '保障必须分别配置双方')
    for team, support in params['support'].items():
        _fields(support, {'position','stock','inventory','assumption'}, '保障参数字段非法')
        _point(support['position']); _number(support['stock']); _text(support['assumption'], '保障须说明估计依据')
        _fields(support['inventory'], {'fuel_liters','spares','materials','shells','aa_rounds'}, '分类保障库存不完整')
        for amount in support['inventory'].values(): _number(amount, 0, 100000000, True)
        if interaction and team not in interaction['active_teams'] and (support['stock'] or any(support['inventory'].values())):
            raise ValueError('非接敌范围外一方不得配置虚构仓库库存')
    f = params['facility']
    _fields(f, {'id','name','lat','lng','progress','integrity','materials','capacity','used'}|{k for k in ('crossing_model','crossing_network') if k in f}, '通行设施参数不完整')
    from . import crossing_network
    crossing_network.validate(f,area=area)
    _point({k:f[k] for k in ('lat','lng')})
    for key in ('id','name'): _text(f[key], '设施身份不能为空')
    for key in ('progress','integrity'): _number(f[key], 0, 100, True)
    for key in ('materials','capacity','used'): _number(f[key], 0, 10000000, True)
    if f['used'] > f['capacity']: raise ValueError('设施已用容量非法')
    if 'crossing_model' in f:
        from . import crossings
        crossings.validate_model(f['crossing_model'])
        if not cfg['bridge_enabled']:raise ValueError('配置渡运模型必须同时开启通行设施约束')
        for p in [f]+list(f['crossing_model']['barrier'].values())+list(f['crossing_model']['banks'].values()):
            if missions.distance(p,area['center'])>area['radius_km']:raise ValueError('渡运设施、有限河线和两岸点须位于计算范围内')
    json.dumps(params, ensure_ascii=False, allow_nan=False)
    from . import formation_parts
    formation_parts.validate_inputs(snapshot,params,index,partial=actor_ids is not None)
    from . import historical_constraints
    historical_constraints.enforce(snapshot,params,actor_ids)
    from . import campaign_estimates
    campaign_estimates.validate_parameters(snapshot,params,actor_ids)
    # Goal-DAG validity is universal, not conditional on an optional numerical
    # prior bundle. A globals stage must reject errors while it is still writable.
    from . import campaign_plan
    campaign_plan.validate_inputs(snapshot,params)
    if 'campaign_lifecycle' in params:
        from . import campaign_lifecycle
        campaign_lifecycle.validate_config(params['campaign_lifecycle'],
            {'historical_initial':snapshot},params.get('campaign_plan'))
    return index


def definition(snapshot, params, *, _frozen=False):
    index = _validate(snapshot, params, _frozen=_frozen)
    from . import campaign_scope
    snapshot, params = copy.deepcopy(snapshot), copy.deepcopy(params)
    cfg, area, goal = params['rules'], params['area'], params['goal']
    rosters = {'red_units':[], 'blue_units':[]}; nodes=[]
    for team, support in params['support'].items():
        if not any(index[i]['team']==team for i in params['actors']):continue
        nodes.append({'id':team+'-historical-supply','name':team+'方计算补给节点','team':team,
                      **support['position'],'stock':support['stock'],'source':support['assumption'],
                      **({'commodities':{'food':support['stock'],'ammo':support['stock']}} if 'supply_distribution' in params else {})})
    labels={'armor':'装甲车辆','artillery':'火炮','air_defense':'防空火器','engineer':'工兵作业组','transport':'运输单元'}
    for identity in (campaign_scope.selected(snapshot,params) if campaign_scope.enabled(params) else partition(snapshot)):
        fact=index[identity];p=params['actors'][identity];team=fact['team']
        sources={k:{'kind':'model_estimate','note':p['assumption']} for k in ('personnel','equipment','position','performance','logistics')}
        if fact['facts']['personnel']['value'] is not None:
            sources['personnel']={'kind':'source_fact','evidence':copy.deepcopy(fact['facts']['personnel']['evidence'])}
        rosters[team+'_units'].append({'historical_unit_id':identity,'name':fact['name'],'type':p['type'],
            'echelon':fact['echelon'],'parent_id':fact['parent_id'],'historical_evidence':copy.deepcopy(fact['evidence']),
            'parameter_sources':sources, **p['position'], 'hp':100, 'speed':p['speed'],
            'attack_range':p['attack_range_m'],'ground_control_radius_km':p['ground_control_radius_km'],
            'morale':'模型初始假设','supply':min(p['logistics'].values()),'supply_node_id':team+'-historical-supply',
            'personnel':{'committed':p['personnel'],'current':p['personnel'],'casualties':0,'noncombat_losses':0,'source':p['assumption']},
            'equipment':[{'category':cat,'name':labels[cat],'committed':amount,'operational':amount,
                          'damaged':0,'destroyed':0,'damage_load':0,'source':p['assumption']}
                         for cat in combined_arms.RULES['categories'] for amount in [p['equipment'][cat]]],
            'logistics':p['logistics'],'formation':{**p['formation'],'source':p['assumption']}})
    world={'center':[area['center']['lat'],area['center']['lng']],'current_time':params['clock']['start'],
        'current_terrain':'参数化地形；未作DEM配准', **rosters,'supply_nodes':nodes,'engagements':[],
        'historical_initial':snapshot,'source_note':SOURCE+'；'+params['assumptions'],
        'combined_arms':{'version':combined_arms.VERSION,'rules_hash':missions.digest(cfg),'source':SOURCE,
            'bridge':params['facility'],'events':[], 'depots':{t:s['inventory'] for t,s in params['support'].items()}}}
    from . import formation_parts
    formation_parts.expand(world,params)
    if 'operation_boundary' in params:
        from . import operation_boundary
        operation_boundary.validate(params['operation_boundary'],area,
            actors=[{'position':{k:u[k] for k in ('lat','lng')}} for _,u in missions.units(world)],plan=params.get('campaign_plan'))
    if 'support_dynamics' in params:
        from . import support_dynamics
        for _,unit in missions.units(world):unit['sustainment']=support_dynamics.initial_state(params['support_dynamics'])
    from . import campaign
    process=campaign.bind(snapshot,params)
    if process is not None:world['campaign']=campaign.initial_state(world,process,params['clock']['start'])
    from . import campaign_plan
    plan=campaign_plan.bind(params.get('campaign_plan'),world,goal,area)
    from . import campaign_lifecycle
    lifecycle=campaign_lifecycle.validate_config(params['campaign_lifecycle'],world,plan) if 'campaign_lifecycle' in params else None
    from . import ferries
    ferries.initialize(world)
    battle_scope.validate(world, anchors.collect_available_nodes(snapshot['definition']['battle'],battle=snapshot['definition']['battle']))
    binding={'format':FORMAT,'initial':snapshot,'parameters':params}
    return {'id':'HO-'+missions.digest(binding)[:20], 'battle':snapshot['definition']['battle'],
        'title':'具名历史部队参数化 · '+snapshot['definition']['battle'],'profile':'combined',
        'assumptions':SOURCE+'；'+params['assumptions'],'historical_calculation':binding,
        'goal':goal_text(params) if process is not None or 'termination_mode' in goal else goal['description'],'ceasefire_turn':4,'time_step':params['clock']['time_step'],
        **({'termination_mode':goal['termination_mode']} if 'termination_mode' in goal else {}),
        'deadline_turn':goal['deadline_turn'],'required_turns':goal['required_turns'],
        'map_center':area['center'],'map_radius_km':area['radius_km'], 'objective':goal['objective'],
        'exit':goal['exit'],'goal_radius_km':goal['radius_km'],
        'rules':{'move_km':max(p['speed'] for p in params['actors'].values())*sim_clock.duration_seconds(params['clock']['time_step'])/3600/area['terrain_factor'],
                 'damage':12,'cover':.8},
        'geometry':{'control_radius_km':min(p['ground_control_radius_km'] for p in params['actors'].values()),'terrain_factor':area['terrain_factor']},
        'combined_rules':cfg,'initial_state':world,
        **({'operation_boundary':copy.deepcopy(params['operation_boundary'])} if 'operation_boundary' in params else {}),
        **({'support_dynamics':params['support_dynamics']} if 'support_dynamics' in params else {}),
        **({'movement_feedback':copy.deepcopy(params['movement_feedback'])} if 'movement_feedback' in params else {}),
        **({'fire_accounting':copy.deepcopy(params['fire_accounting'])} if 'fire_accounting' in params else {}),
        **({'fire_dynamics':copy.deepcopy(params['fire_dynamics'])} if 'fire_dynamics' in params else {}),
        **({'supply_schedule':params['supply_schedule']} if 'supply_schedule' in params else {}),
        **({'terrain_model':params['terrain_model']} if 'terrain_model' in params else {}),
        **({'supply_distribution':params['supply_distribution']} if 'supply_distribution' in params else {}),
        **({'campaign_definition':process} if process is not None else {}),
        **({'campaign_plan':plan} if plan is not None else {}),
        **({'campaign_lifecycle':lifecycle} if lifecycle is not None else {}),
        **({'air_definition':_air_definition(snapshot,params,_frozen=_frozen)} if 'aviation' in params else {}),
        **({'objective_team':goal['team']} if 'team' in goal else {})}


def from_binding(binding):
    _fields(binding, {'format','initial','parameters'}, '缺少完整历史计算输入快照')
    if binding['format'] != FORMAT: raise ValueError('历史计算版本非法')
    # Restore the exact previously frozen inputs, including old range mistakes;
    # this does not grant new builds permission to repeat those mistakes.
    return definition(binding['initial'], binding['parameters'], _frozen=True)


def initial(snapshot, parameters):
    return missions.from_definition(definition(snapshot, parameters))


def validate_identity(world):
    spec=world['mission']['definition'];original=spec['initial_state']
    if world.get('historical_initial') != original['historical_initial']:
        raise ValueError('计算过程不得改写历史事实快照')
    from . import formation_registry
    index={u['name']:u for _,u in formation_registry.reference(world)}
    if {u.get('name') for _,u in missions.units(world)} != set(index):
        raise ValueError('历史单位名单丢失或被替换')
    for _,unit in missions.units(world):
        if any(unit.get(k)!=index[unit['name']].get(k) for k in
               ('historical_unit_id','exercise_unit_id','echelon','parent_id','historical_evidence','parameter_sources','calculation_unit_id','formation_part')):
            raise ValueError('历史单位身份、隶属或参数来源被改写')
        original_unit = index[unit['name']]
        if (unit['personnel'].get('source') != original_unit['personnel'].get('source')
                or unit['formation'].get('source') != original_unit['formation'].get('source')
                or [e.get('source') for e in unit['equipment']] != [e.get('source') for e in original_unit['equipment']]):
            raise ValueError('参数估计说明不能在计算过程中冒充史实来源')


def goal_text(parameters):
    if parameters.get('campaign_plan'):
        plan=parameters['campaign_plan'];labels={n['id']:n['label'] for n in plan['nodes']}
        solo=any(not row['node_ids'] for row in plan['outcomes'].values())
        return ('会战目标图：'+ '；'.join(('红方' if team=='red' else '蓝方')+'（'+('全部' if row['mode']=='all' else '任一')+'）：'+
            '、'.join(labels[i] for i in row['node_ids']) for team,row in plan['outcomes'].items() if row['node_ids'])+
            ('。各方向按依赖与激活时点评分；只结算参演方转移目标，不因对方未建模自动获胜；保持时间按回合端点采样。' if solo else
             '。各方向按依赖与激活时点评分，双方同时达标判平局；保持时间按回合端点采样。'))
    goal = parameters['goal']; profile = goal['profile']
    deadline, turns, survivors = goal['deadline_turn'], goal['required_turns'], goal['required_survivors']
    owner=goal.get('team','red');own='红方' if owner=='red' else '蓝方';other='蓝方' if owner=='red' else '红方'
    objectives=goal.get('termination_mode')=='objectives'
    if parameters.get('campaign',{}).get('objective_policy')=='defensive-delay-1':
        fraction=parameters['campaign']['objective']['min_force_fraction']
        return (f'程序会战迟滞目标：'+(f'连续{turns}回合' if objectives else f'第{deadline}回合截止时')+
            f'{own}至少{survivors}个已入场可用编组，已入场人员保持其投入的{fraction*100:g}%，'
            f'且{other}已入场可用单位未进入出口600米内；不要求夺占据点或阻援区域。'
            +('不按参考轮数或史料日期自动结束。' if objectives else '')+'过程和阈值为显式估计，不代表完整历史胜负。')
    if parameters.get('campaign'):
        objective=parameters['campaign']['objective']
        timing=f'连续保持{turns}回合，' if objectives else f'第{deadline}回合截止时，'
        return (f'程序战役目标：{timing}{own}控制据点及全部{len(objective["relief_regions"])}个阻援区域，'
                f'区域内无{other}可用单位，且保留初始投入人数的{objective["min_force_fraction"]*100:g}%；'
                f'高压制或未入场单位不计控制，{own}全灭提前结束。'+('不按史料日期或参考轮数自动结束。' if objectives else '')+'过程与阈值为明确估计，不强制历史战果。')
    condition = {
        'delay': (f'连续{turns}回合保持' if objectives else f'第{deadline}回合截止时')+f'{own}至少{survivors}个可用单位，且{other}没有可用单位进入退出点600米内',
        'breakout': f'{own}至少{survivors}个可用单位进入退出点600米内并连续保持{turns}回合',
        'crossing': f'{own}至少{survivors}个可用编组完成登记通道渡运并进入目标半径{goal["radius_km"]}公里，{other}不占目标区，连续保持{turns}回合',
        'assault': f'目标半径{goal["radius_km"]}公里内有{own}、无{other}可用单位并连续保持{turns}回合；高压制单位不计控制',
        'rail': f'交通完整度不高于20并连续保持{turns}回合',
        'underground': (f'连续{turns}回合保持' if objectives else f'第{deadline}回合截止时')+f'组织度至少50且仍有{own}可用单位',
        'reception': f'接收标志为1并连续保持{turns}回合；接收动作自第4回合窗口后可用',
    }[profile]
    timing='不按史料日期或参考轮数自动结束' if objectives else f'总截止为第{deadline}回合'
    return f'程序局部目标：{condition}；{timing}，{own}全灭提前结束。不代表全战役胜负。'

