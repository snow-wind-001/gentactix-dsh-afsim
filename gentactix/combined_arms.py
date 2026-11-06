"""Versioned aggregate force inputs and validation, never a combat executor.

All generated counts are explicit teaching priors. Historical cards and legacy
mission definitions are untouched. WSF Script owns transitions in afsim_combined.
"""
import copy
from decimal import Decimal
import json
import hashlib
import math
from functools import lru_cache
from . import missions, adjudication_lib, anchors, sim_clock, combat_effects
from .unit_types import classify_unit

VERSION='combined-arms-teaching-1'
SOURCE='团级合成教学编制与效能假设；非战役实际部署/武器标定；史料数值不用于逐轮硬编码'
RULES={'version':VERSION,'categories':['armor','artillery','air_defense','engineer','transport'],
       'direct_range_m':1200,'armor_range_m':3000,'artillery_range_m':12000,
       'aa_range_m':4500,'aa_ceiling_m':4500,'aa_loss_coefficient':.015,'artillery_min_range_m':300,
       'shells_per_gun':2,'max_salvo':24,'reload_turns':1,'suppression_decay':10,
       'suppression_control_threshold':65,
       'fortify_gain':20,'build_gain':50,'build_materials':4,'repair_limit':2,
       'repair_parts_per_item':1,'transport_tons_per_truck':.15,'ton_per_supply_unit':.25,
       'shells_per_supply_unit':12,'aa_rounds_per_supply_unit':8,
       'cargo_mass_tons':{'fuel_liters':.0008,'spares':.008,'materials':.01,'shells':.01,'aa_rounds':.0002},
       'command_base_s':60,'command_distance_s_per_km':12,'command_signal_s':6,
       'intel_age_decay':.015,'fatigue_move_gain':15,'fatigue_rest_recovery':12,
       'bridge_capacity':2,'bridge_corridor_km':.7,'initial_bridge_progress':0}
EXTRA_ACTIONS=('bombard','suppress','fortify','build_bridge','demolish','repair_equipment','recon','restore_comms')
TARGET_ACTIONS=('fire','bombard','suppress','air_support')


def is_combined(world):return bool((world or {}).get('mission',{}).get('definition',{}).get('combined_rules'))


def air_enabled(world):return is_combined(world) and world['mission']['definition']['combined_rules']['air_support']


def weapon_limits(world, unit):
    """Declared nominal ranges, independent of current ammo or order permission.

    This resolves existing inputs only; it does not change frozen physics or
    promise that a weapon is ready, an action permitted, or a target detected.
    """
    cfg=world['mission']['definition']['combined_rules']
    result={'fire':{'min_range_m':0,'max_range_m':unit['attack_range']}}
    issued={e['category']:e.get('committed',e.get('operational',0)) for e in unit.get('equipment',[])}
    if issued.get('artillery',0)>0:
        result.update({key:{'min_range_m':cfg['artillery_min_range_m'],'max_range_m':cfg['artillery_range_m']}
                       for key in ('bombard','suppress')})
    if issued.get('air_defense',0)>0:
        result['air_defense']={'min_range_m':0,'max_range_m':cfg['aa_range_m']}
    return result


def weapon_warnings(world, unit):
    """Expose legacy range mistakes without rewriting saved inputs or losses."""
    kind=classify_unit(unit.get('type'))
    maximum=weapon_limits(world,unit)['fire']['max_range_m']
    if kind and kind['id'] in ('rocket','sp_artillery','towed_artillery','mortar') and maximum>world['mission']['definition']['combined_rules']['direct_range_m']:
        return [f'炮兵自卫直射范围{maximum:g}米超出本局直射基准，可能混用了间接射程。当前保留旧参数；请另建配置核验，不作为历史武器效能证明。']
    return []


@lru_cache(maxsize=1)
def _catalog():
    result=[]
    original={s['battle']:s for s in missions.catalog()}
    for battle in adjudication_lib.list_battles():
        old=original.get(battle)
        if old:
            center=copy.deepcopy(old['map_center']);date=old['initial_state']['current_time']
        else:
            nodes=anchors.collect_available_nodes(battle,battle=battle)
            if not nodes:raise ValueError('统一教学想定缺少战役地理参考点：'+battle)
            lat,lng=next(iter(nodes.values()));center={'lat':lat,'lng':lng}
            import re
            m=re.search(r'(19\d{2})[.](\d{2})(?:[.](\d{2}))?',battle)
            date=f'{m[1]}-{m[2]}-{m[3] or "01"} 08:00' if m else '公元前260年 08:00'
        ancient=battle=='长平之战';march=battle.startswith('长征-') or '长征' in battle
        era='ancient' if ancient else 'long_march' if march else 'korea' if battle.startswith('抗美援朝-') else 'ww2'
        air=bool(old and old['profile']=='air')
        goal_profile=old['profile'] if old else ('breakout' if march or ancient else 'delay' if '防御' in battle or '上甘岭' in battle else 'assault')
        config={**copy.deepcopy(RULES),'era':era,'air_support':air,'motorized':era not in ('ancient','long_march'),'goal_profile':goal_profile,
                'convoy_km_per_turn':15 if era not in ('ancient','long_march') else 1.5}
        if ancient:config.update(direct_range_m=350,armor_range_m=350,artillery_range_m=0)
        if march:config['artillery_range_m']=6000
        identity='CA-'+hashlib.sha256(battle.encode()).hexdigest()[:12]+'-v1'
        if old and old['id']=='AJ18-local-v1':identity='CA-AJ18-v1'
        result.append(_definition(identity,battle,center,date,config))
    return result


def catalog():return copy.deepcopy(_catalog())


def demo_definition():return next(s for s in catalog() if s['id']=='CA-AJ18-v1')


def definition(identity):
    for spec in _catalog():
        if spec['id']==identity:return copy.deepcopy(spec)
    raise ValueError('未知团级教学想定')


CUSTOM_VERSION = 'synthetic-config-1'
CUSTOM_SOURCE = '用户自定义合成教学演习参数；不是历史实际编制、库存或部署'
CUSTOM_LIMITS = {'personnel': (1, 100000), 'food': (0, 100), 'ammo': (0, 100),
                 'shells': (0, 1000000), 'aa_rounds': (0, 1000000),
                 'fuel_liters': (0, 10000000), 'fatigue': (0, 100)}


def configuration_limits(*,historical_baseline=False):
    from . import formation_parts
    maximum=formation_parts.LIMITS[formation_parts.CAMPAIGN_VERSION][1]if historical_baseline else 12
    return {'max_units_per_team':maximum}


def configuration(identity):
    return configuration_from_definition(definition(identity))


def configuration_from_definition(spec):
    return {'version': CUSTOM_VERSION, 'teams': {
        team: [{'name': u['name'], 'personnel': u['personnel']['current'],
                'equipment': {e['category']: e['operational'] for e in u['equipment']},
                **{k: u['logistics'][k] for k in ('food', 'ammo')},
                **{k: u['formation'][k] for k in ('shells', 'aa_rounds', 'fuel_liters', 'fatigue')}}
               for u in spec['initial_state'][team+'_units']] for team in ('red', 'blue')},
        **({'fire_accounting':copy.deepcopy(spec['fire_accounting'])} if 'fire_accounting' in spec else {}),
        **({'fire_dynamics':copy.deepcopy(spec['fire_dynamics'])} if 'fire_dynamics' in spec else {}),
        **({'aviation':{i:{k:copy.deepcopy(p[k]) for k in ('initial','entry','rules','assumption')}
                       for i,p in spec['air_definition']['pools'].items()}} if 'air_definition' in spec else {})}


def configure(identity, values):
    """Build a deterministic input variant; all transitions still belong to WSF."""
    return configure_definition(definition(identity), values)


def configure_definition(base, values, *, reference=None, historical_baseline=False):
    """Reuse the same input validator for a host-validated frozen definition."""
    spec = copy.deepcopy(base)
    values = copy.deepcopy(values)
    if not isinstance(values, dict) or set(values) - {'version', 'teams', 'historical_basis','aviation','fire_accounting','fire_dynamics'} or not {'version','teams'} <= set(values) or values['version'] != CUSTOM_VERSION:
        raise ValueError('合成演习配置版本或字段非法')
    if 'fire_accounting' in values:
        combat_effects.validate_accounting(values['fire_accounting'])
        spec['fire_accounting']=copy.deepcopy(values['fire_accounting'])
    else:
        spec.pop('fire_accounting',None)
    if 'fire_dynamics' in values:
        combat_effects.validate_dynamics(values['fire_dynamics'])
        spec['fire_dynamics']=copy.deepcopy(values['fire_dynamics'])
    else:
        spec.pop('fire_dynamics',None)
    from . import air_assets
    if 'air_definition' in spec:
        inputs=values.get('aviation');pools=spec['air_definition']['pools']
        if not isinstance(inputs,dict) or set(inputs)!=set(pools):raise ValueError('合成航空须保留同一历史来源池，不能漏配或虚构航空部队')
        for identity,p in inputs.items():
            if not isinstance(p,dict) or set(p)!={'initial','entry','rules','assumption'}:raise ValueError('合成航空只能编辑计算参数')
            pools[identity].update(copy.deepcopy(p))
        air_assets.validate_definition(spec['air_definition'])
        spec['initial_state'].pop('air_operations',None)
    elif 'aviation' in values:raise ValueError('本初态没有具名航空基础，不能套用其他时代飞机')
    if values.get('historical_basis') is not None:
        if reference is None:
            from . import scenario_basis
            binding = values['historical_basis']
            reference = scenario_basis.resolve(spec['battle'], binding.get('basis_hash') if isinstance(binding, dict) else None)
        if values['historical_basis'] != {'battle':spec['battle'], 'basis_hash':reference['basis_hash']}:
            raise ValueError('史实基础版本或战役不一致，不能替换来源')
    teams = values['teams']
    if not isinstance(teams, dict) or set(teams) != {'red', 'blue'}:
        raise ValueError('合成演习必须分别配置红蓝双方')
    seen = set()
    maximum=configuration_limits(historical_baseline=historical_baseline)['max_units_per_team']
    for team, rows in teams.items():
        minimum=0 if historical_baseline and not base['initial_state'][team+'_units'] else 1
        if not isinstance(rows, list) or not minimum <= len(rows) <= maximum:
            raise ValueError(f'每方须有{minimum}至{maximum}个可操纵编组')
        baseline = spec['initial_state'][team+'_units']; configured = []
        for i, row in enumerate(rows):
            if not isinstance(row, dict) or set(row) - {'name','equipment',*CUSTOM_LIMITS,'position','basis_id'} or not {'name','equipment',*CUSTOM_LIMITS} <= set(row):
                allowed={'name','equipment',*CUSTOM_LIMITS,'position','basis_id'}
                missing=sorted({'name','equipment',*CUSTOM_LIMITS}-set(row)) if isinstance(row,dict) else []
                extra=sorted(set(row)-allowed) if isinstance(row,dict) else []
                raise ValueError('合成编组配置字段非法：缺少'+str(missing)+'；多余'+str(extra)+'。不要附加说明性字段，按种子编组格式提交')
            name = row['name']
            if not isinstance(name, str) or not name.strip() or len(name) > 60 or any(ord(c)<32 for c in name) or name in seen:
                raise ValueError('编组名称须为唯一的1至60字单行文本')
            seen.add(name)
            for key, (low, high) in CUSTOM_LIMITS.items():
                if key in ('food','ammo'):
                    if type(row[key]) not in (int,float) or not low <= row[key] <= high or not math.isfinite(row[key]):
                        raise ValueError(f'{name}的{key}须为{low}至{high}的有限工作量')
                elif type(row[key]) is not int or not low <= row[key] <= high:
                    raise ValueError(f'{name}的{key}须为{low}至{high}的整数')
            equipment = row['equipment']
            if not isinstance(equipment, dict) or set(equipment) != set(RULES['categories']) or any(type(v) is not int or not 0 <= v <= 10000 for v in equipment.values()):
                raise ValueError('装备仅支持已登记的五个类别，每类0至10000个')
            if spec['combined_rules']['era'] == 'ancient' and any(equipment[k] for k in ('armor', 'artillery', 'air_defense')):
                raise ValueError('古代规则尚不支持装甲、火炮或防空装备；请改选近现代合成演习')
            origin = (next((u for u in baseline if u.get('calculation_unit_id',u.get('historical_unit_id'))==row.get('basis_id')),None)
                      if historical_baseline else baseline[i % len(baseline)])
            if origin is None:raise ValueError('派生编组须绑定当前阶段同阵营的初态单位')
            u = copy.deepcopy(origin)
            u.update(name=name, lat=spec['map_center']['lat']+(i-(len(rows)-1)/2)*.003)
            if reference:
                source = next((r for r in reference['units'] if r['id']==row.get('basis_id') and r['team']==team),None)
                if source is None:
                    raise ValueError('编组必须绑定同一阵营的史料单位参考')
                u['historical_reference'] = copy.deepcopy(source)
                if not historical_baseline:u['type'] = '装甲兵' if equipment['armor'] else '步兵'
                u['parameter_sources'] = {'reference_name':'史料卡参战单位参考',
                    'name':'派生演习名称；可由用户修改', 'personnel':'演习估计或用户输入',
                    'type':'局部演习兵种假设，不代表整个历史上级部队',
                    'equipment':'演习配发；不是历史实到量', 'position':'演习部署估计或地图编辑'}
                if historical_baseline:
                    u['source_historical_unit_id']=source.get('historical_unit_id',source['id'])
                    if name != origin['name'] and not u.get('formation_part'):
                        u.pop('historical_unit_id',None)
                        u['echelon']='演习派生编组'
                        u['historical_evidence']=[];u['parent_id']=None
                    before_equipment={e['category']:e['committed'] for e in origin['equipment']}
                    if equipment['armor'] and not before_equipment['armor']:
                        u['type']='装甲兵';u['formation']['role']='armor';u['formation']['motorized']=True
                    elif equipment['artillery'] and not before_equipment['artillery']:
                        u['type']='炮兵';u['formation']['role']='support'
            elif 'basis_id' in row:
                raise ValueError('存在来源ID但缺少史实基础版本')
            if 'position' in row:
                pos=row['position']
                if not isinstance(pos,dict) or set(pos)!={'lat','lng'} or any(type(v) not in (int,float) or not math.isfinite(v) for v in pos.values()) or not -90<=pos['lat']<=90 or not -180<=pos['lng']<=180:
                    raise ValueError('编组部署坐标非法')
                if missions.distance(pos,spec['map_center'])>spec['map_radius_km']:
                    raise ValueError('编组部署超出当前局部想定边界；总览须拆分局部战区')
                pos.update(lat=float(pos['lat']),lng=float(pos['lng']))
                u.update(lat=pos['lat'],lng=pos['lng'])
            u['personnel'] = {'committed': row['personnel'], 'current': row['personnel'], 'casualties': 0, 'noncombat_losses': 0, 'source': CUSTOM_SOURCE}
            for e in u['equipment']:
                e.update(committed=equipment[e['category']], operational=equipment[e['category']], damaged=0, destroyed=0, damage_load=0, source=CUSTOM_SOURCE)
            u['logistics'] = {k: row[k] for k in ('food', 'ammo')}
            u['formation'].update({k: row[k] for k in ('shells', 'aa_rounds', 'fuel_liters', 'fatigue')}, source=CUSTOM_SOURCE)
            if not historical_baseline:
                u['attack_range'] = spec['combined_rules']['armor_range_m'] if equipment['armor'] else spec['combined_rules']['direct_range_m']
            elif u['type'] != origin['type']:
                u['attack_range'] = spec['combined_rules']['armor_range_m'] if equipment['armor'] else min(origin['attack_range'],spec['combined_rules']['direct_range_m'])
            configured.append(u)
        spec['initial_state'][team+'_units'] = configured
    spec['synthetic_configuration'] = copy.deepcopy(values)
    spec['base_definition_hash'] = missions.digest(base)
    spec['title'] = '自定义合成教学演习 · ' + spec['battle']
    spec['assumptions'] = CUSTOM_SOURCE + '；行动与目标沿用所选规则，不等于完整历史战役'
    cfg = spec['combined_rules']
    cfg['required_survivors'] = min(cfg['required_survivors'] if historical_baseline else 2, len(teams[missions.objective_team(spec)]))
    if cfg['required_survivors'] == 1:
        spec['goal'] = spec['goal'].replace('至少两个', '至少一个')
    cfg['motorized'] = cfg['motorized'] or any(r['equipment']['armor'] for rows in teams.values() for r in rows)
    model = spec['initial_state']['combined_arms']
    model.update(source=CUSTOM_SOURCE, rules_hash=missions.digest(cfg))
    if base['initial_state'].get('formation_groups'):
        from . import formation_parts
        formation_parts.rebind_exercise(spec['initial_state'],base['initial_state'])
        cfg['required_survivors']=min(cfg['required_survivors'],len(formation_parts.buckets(spec['initial_state'],missions.objective_team(spec))))
        model['rules_hash']=missions.digest(cfg)
    return spec


def _definition(identity,battle,center,date,config):
    lat,lng=center['lat'],center['lng']; ancient=config['era']=='ancient';march=config['era']=='long_march'
    units={};nodes=[]
    for team,label,sign in (('red','红方',-1),('blue','蓝方',1)):
        units[team+'_units']=[]
        nodeid=team+'-warehouse';nodes.append({'id':nodeid,'team':team,'name':label+'教学仓库/指挥所','lat':lat,'lng':lng+sign*.035,'stock':480,'source':SOURCE})
        for i,role in enumerate(('infantry','armor','support')):
            role_label=('步兵编组','机动编组','支援编组')[i]
            if not ancient:role_label=('步兵团','机动团','支援团')[i]
            counts={'armor':(4,24,0)[i],'artillery':(4,4,18)[i],'air_defense':(2,2,6)[i],'engineer':6,'transport':(20,30,40)[i]}
            if ancient or march:
                counts['armor']=0
                if ancient:counts.update(artillery=0,air_defense=0)
                elif team=='red':counts.update(artillery=(0,0,2)[i],air_defense=0)
            personnel=(3000,1800,1600)[i]
            equipment=[]
            names={'armor':'装甲车辆','artillery':'火炮','air_defense':'防空火器','engineer':'工兵作业组','transport':'运输车辆' if not ancient and not march else '驮运队'}
            for cat in RULES['categories']:
                damaged=2 if cat=='transport' else 0
                equipment.append({'name':names[cat],'category':cat,'committed':counts[cat]+damaged,
                    'operational':counts[cat],'damaged':damaged,'destroyed':0,'damage_load':0,'source':SOURCE})
            maximum=config['armor_range_m'] if counts['armor'] else config['direct_range_m']
            units[team+'_units'].append({'name':label+'教学'+role_label,'type':'骑兵' if ancient and role=='armor' else '步兵' if ancient or march else {'infantry':'摩托化步兵','armor':'装甲兵','support':'炮兵'}[role],
                'lat':lat+(i-1)*.004,'lng':lng+sign*.012,'hp':100,'speed':3,'attack_range':maximum,'ground_control_radius_km':.35,
                'morale':'教学稳定','supply':80,'supply_node_id':nodeid,
                'personnel':{'committed':personnel,'current':personnel,'casualties':0,'noncombat_losses':0,'source':SOURCE},
                'equipment':equipment,'logistics':{'food':80,'ammo':80},
                'formation':{'role':role,'fatigue':10,'suppression':0,'entrenchment':10,
                    'dispersion_km2':.8 if role=='armor' else 1.2,'protection':.7 if role=='armor' and counts['armor'] else .15,
                    'fuel_liters':2000 if config['motorized'] else 0,'spares':20,'materials':16,'shells':160 if counts['artillery'] else 0,
                    'aa_rounds':160 if counts['air_defense'] else 0,'reload_remaining':0,
                    'intel_age_min':30,'intel_confidence':70,'signal':80,'source':SOURCE}})
    world={'center':[lat,lng],'current_time':date,'current_terrain':'丘陵河谷（教学示意，未作DEM配准）',
        **units,'supply_nodes':nodes,'engagements':[],
        'combined_arms':{'version':VERSION,'rules_hash':missions.digest(config),'source':SOURCE,
            'depots':{t:{'fuel_liters':12000 if config['motorized'] else 0,'spares':120,'materials':120,'shells':12000 if not ancient else 0,'aa_rounds':8000 if not ancient else 0} for t in ('red','blue')},
            'bridge':{'id':'teaching-crossing','name':'教学桥梁/渡口','lat':lat,'lng':lng,'progress':0,'integrity':100,
                'materials':40,'capacity':config['bridge_capacity'],'used':0},'events':[]}}
    goals={'delay':'坚持到截止回合，至少两个红方编组存续，蓝方未突入示意后方出口',
        'breakout':'至少两个红方编组到达示意后方出口并连续保持两轮',
        'rail':'将交通网完好度降至20以下并连续保持两轮',
        'underground':'坚持到截止回合，组织存续值不低于50且有红方编组可用',
        'reception':'在第4轮停火接收窗口开启后于目标区完成接收',
        'air':'控制桥梁东侧目标区连续两轮；航空支援按任务影响战损',
        'assault':'控制桥梁东侧目标区连续两轮，且保持红方编组可用'}
    return {'id':identity,'battle':battle,'title':'团级多兵种综合教学 · '+battle,
        'profile':'combined','assumptions':SOURCE+'；同一战役的合成局部演习，不代替历史初态',
        'goal':goals[config['goal_profile']], 'ceasefire_turn':4,
        'time_step':'30分钟','deadline_turn':8,'required_turns':2,'map_center':center,'map_radius_km':10,
        'objective':{'lat':lat,'lng':lng+.004},'exit':{'lat':lat,'lng':lng-.03},'goal_radius_km':.5,
        'rules':{'move_km':1.5,'damage':12,'cover':.8},'geometry':{'control_radius_km':.15,'terrain_factor':1.0},
        'initial_state':world,'combined_rules':config}


def fire_unavailability(world, unit):
    """Shared resource gates; explain a disabled action without running combat."""
    f = unit.get('formation', {})
    count = {e['category']: e['operational'] for e in unit.get('equipment', [])}
    reference = combat_effects.reference(world)
    reasons = {}
    if unit['logistics']['ammo'] < combat_effects.work_cost(reference,'fire'):
        reasons['fire'] = '携行弹药不足，不能完成一个射击周期；请先补给'
    remaining = f.get('reload_remaining_s', f.get('reload_remaining', 0)*reference['artillery_cycle_s'])
    if count.get('artillery', 0) <= 0:
        indirect = '没有可用炮兵装备，不能执行炮击或压制'
    elif f.get('shells', 0) <= 0:
        indirect = '炮弹库存不足，不能执行炮击或压制；请先补给'
    elif remaining >= sim_clock.duration_seconds(world['mission']['definition']['time_step']):
        indirect = '炮兵本轮仍处于射击冷却期，请等待后重新下令'
    else:
        indirect = ('携行弹药不足，不能完成一个射击周期；请先补给'
                    if unit['logistics']['ammo']<combat_effects.work_cost(reference,'bombard') else None)
    if indirect:
        reasons.update(bombard=indirect, suppress=indirect)
    return reasons


def actions(world,unit,team):
    from . import ferries
    boat=ferries.carrier(world,unit['name'])
    if boat and boat['phase'] in ('outbound','unloading'):return ['hold','move']
    f=unit.get('formation',{}); count={e['category']:e['operational'] for e in unit.get('equipment',[])}
    cfg=world['mission']['definition']['combined_rules']
    result=['hold','move','fire','resupply','conceal','fortify','recon','restore_comms']
    from . import campaign
    if campaign.release_seconds(world,unit)>0:return list(campaign.WAITING_ACTIONS)
    if campaign.definition(world) and campaign.definition(world)['surrender']['enabled']:result.append('capture')
    fire_reasons = fire_unavailability(world, unit)
    if 'fire' in fire_reasons: result.remove('fire')
    result += [action for action in ('bombard', 'suppress') if action not in fire_reasons]
    if count.get('engineer',0)>0:
        if world.get('combined_arms',{}).get('bridge',{}).get('crossing_model'):
            if f.get('materials',0)>0 and world['combined_arms']['bridge']['materials']>0:result+=['build_bridge']
            if f.get('materials',0)>=4:result+=['demolish']
        elif cfg.get('bridge_enabled',True) and f.get('materials',0)>=cfg['build_materials']:result+=['build_bridge','demolish']
        if f.get('spares',0)>0 and any(e['damaged'] for e in unit['equipment']):result+=['repair_equipment']
    if air_enabled(world):
        from . import air_assets
        if (air_assets.available(world,team) if air_assets.world_definition(world) is not None else team=='red'):
            result+=['air_support']
    profile=world['mission']['definition']['combined_rules']['goal_profile']
    if profile=='rail':result+=['sabotage','repair']
    if profile=='reception' and world['mission']['turn']>=world['mission']['definition']['ceasefire_turn']:
        result=[a for a in result if a not in ('fire','bombard','suppress','air_support','demolish')]+['accept']
    from . import unit_participation
    if not unit_participation.in_operation(world,unit):
        result=[a for a in result if a not in unit_participation.OFFENSIVE]
    return result


def validate(world):
    spec=world.get('mission',{}).get('definition',{})
    reference=None
    if 'fire_accounting' in spec or 'fire_dynamics' in spec or any(world.get(k) for k in ('combat_reference','afsim','dsh_execution')):
        reference=combat_effects.reference(world)
    if not is_combined(world):return
    cfg=world['mission']['definition']['combined_rules'];model=world.get('combined_arms',{})
    if cfg.get('version')!=VERSION or model.get('version')!=VERSION or model.get('rules_hash')!=missions.digest(cfg):raise ValueError('多兵种规则版本或摘要不一致')
    from . import air_assets
    if air_assets.world_definition(world) is not None:air_assets.world_state(world)
    b=model['bridge']
    from . import crossings, crossing_network
    crossing_network.validate(b,world['mission']['definition']['initial_state']['combined_arms']['bridge'])
    if 'crossing_model' in b:
        crossings.validate_model(b['crossing_model'])
        if not cfg.get('bridge_enabled',True) or cfg['build_gain']<=0 or cfg['build_materials']<=0:raise ValueError('渡运模型必须保留设施约束及正值工程材料配比')
        initial=world['mission']['definition']['initial_state']['combined_arms']['bridge']
        if any(b.get(k)!=initial.get(k) for k in ('id','name','lat','lng','capacity','crossing_model')):
            raise ValueError('推演中不能改写渡运设施的冻结位置、身份或能力')
    for key in ('progress','integrity'):
        if type(b[key]) is not int or not 0<=b[key]<=100:raise ValueError('桥梁状态非法')
    from . import ferries
    ferries.validate(world)
    if any(type(b[k]) is not int or b[k]<0 for k in ('materials','capacity','used')) or ('crossing_model' not in b and b['used']>b['capacity']):raise ValueError('通行容量或材料非法')
    for pool in model['depots'].values():
        if any(type(v) is not int or v<0 for v in pool.values()):raise ValueError('仓库分类库存非法')
    for _,u in missions.units(world):
        if u.get('crossing'):
            if 'crossing_model' not in b:raise ValueError('本局未绑定渡运模型，不能迁入其他渡河任务')
            crossings.validate_task(crossing_network.by_id(world,u['crossing']['site_id']),u['crossing'])
        cats=[e['category'] for e in u['equipment']]
        if cats!=RULES['categories']:raise ValueError('分类装备账缺失或被重排')
        for e in u['equipment']:
            if any(type(e[k]) is not int or e[k]<0 for k in ('committed','operational','damaged','destroyed')) or e['committed']!=e['operational']+e['damaged']+e['destroyed']:raise ValueError('分类装备账不守恒')
            if not 0<=e.get('damage_load',0)<1:raise ValueError('装备毁伤余量非法')
        f=u['formation']
        from . import movement_feedback, motion_state
        if movement_feedback.continuous(world):
            motion_state.validate_unit(u)
        elif motion_state.present(u):
            raise ValueError('旧运动规则不能携带连续机动精度字段')
        from . import suppression_state
        if reference and 'suppression_state' in reference:
            if world['mission']['turn']>0 and suppression_state.FIELD not in f:
                raise ValueError('已执行单位的连续压制余量缺失，不能按零恢复')
            suppression_state.validate_unit(u)
        elif suppression_state.FIELD in f:
            raise ValueError('旧规则不能携带连续压制余量')
        if 'motorized' in f and type(f['motorized']) is not bool:raise ValueError('单位机动方式非法')
        for k in ('fatigue','suppression','entrenchment','signal'):
            if type(f[k]) is not int or not 0<=f[k]<=100:raise ValueError('编组状态非法：'+k)
        if type(f['intel_confidence']) not in (int,float) or not math.isfinite(f['intel_confidence']) or not 0<=f['intel_confidence']<=100:
            raise ValueError('情报可信度须为0至100的有限分值')
        for k in ('fuel_liters','spares','materials','shells','aa_rounds','reload_remaining'):
            if type(f[k]) is not int or f[k]<0:raise ValueError('编组资源非法：'+k)
        if type(f['intel_age_min']) not in (int,float) or not math.isfinite(f['intel_age_min']) or f['intel_age_min']<0:
            raise ValueError('情报时效须为有限非负分钟数')
        for k in ('combat_damage_remainder','fatality_remainder'):
            if k in f and (type(f[k]) not in (int,float) or not math.isfinite(f[k]) or not 0<=f[k]<1):
                raise ValueError('火力毁伤余量非法：'+k)
        if reference and 'damage_quantum'in reference and 'combat_damage_remainder'in f:
            micro=Decimal(str(f['combat_damage_remainder']))*1000000
            if micro!=micro.to_integral_value():raise ValueError('毁伤余量须符合冻结的1e-6精度；不能自动舍入已携带的余量')
        if 'reload_remaining_s' in f and (type(f['reload_remaining_s']) is not int or f['reload_remaining_s']<0):raise ValueError('炮兵秒级冷却非法')
        combat_effects.validate_personnel(u['personnel'])
        if not all(type(f[k]) in (int,float) and math.isfinite(f[k]) and f[k]>0 for k in ('dispersion_km2',)) or not 0<=f['protection']<=1:raise ValueError('防护或展开面积非法')


def validate_order(world,order):
    old={u['name']:(team,u) for team,u in missions.units(world)};team,u=old[order['unit']]
    if order['action'] not in actions(world,u,team):raise ValueError('当前装备、资源或冷却状态不支持该命令')
    action=order['action'];f=u['formation'];cfg=world['mission']['definition']['combined_rules']
    if 'air_pool' in order and action!='air_support':raise ValueError('只有航空任务可以指定航空资源池')
    if action=='air_support':
        from . import air_assets
        definition=air_assets.world_definition(world)
        if definition is not None:
            from . import air_availability
            _,pool=air_assets.select(definition,air_assets.world_state(world),team,order.get('air_pool'))
            air_availability.require(world,pool)
        elif 'air_pool' in order:raise ValueError('本想定未登记具名航空资源池')
    if action in TARGET_ACTIONS:
        name=order.get('target')
        target=old.get(name) if isinstance(name,str) else None
        if not target or target[0]==team or target[1]['personnel']['current']<=0:
            opponents=[n for n,(t,v) in old.items() if t!=team and v['personnel']['current']>0]
            raise ValueError('攻击目标无效：'+u['name']+'的'+action+'命令必须附target="敌方精确单位名"。'
                '当前对方存活单位名（仍需核对射程与资源）：'+json.dumps(opponents[:8],ensure_ascii=False))
        maximum=weapon_limits(world,u).get(action,{}).get('max_range_m',u['attack_range'])
        if action!='air_support' and missions.distance(u,target[1])*1000>maximum+1:raise ValueError('目标超出武器射程')
        if action in ('bombard','suppress') and missions.distance(u,target[1])*1000<cfg['artillery_min_range_m']:raise ValueError('目标低于间瞄火力最小射程')
        reference=combat_effects.reference(world)
        if action!='air_support' and u['logistics']['ammo']<combat_effects.work_cost(reference,action):raise ValueError('弹药工作量不足')
    if action in ('build_bridge','demolish'):
        from . import crossing_network
        site=crossing_network.engineering_site(world,u);points=list(site['crossing_model']['banks'].values()) if site.get('crossing_model') else [site]
        if min(missions.distance(u,p) for p in points)>.7:raise ValueError('工兵行动须位于通行设施或岸点700米内')
    if action in ('sabotage','repair','accept') and missions.distance(u,world['mission']['definition']['objective'])>.6:raise ValueError('任务须在目标600米内')


GUIDANCE=('团级多兵种教学：build_bridge须在桥梁700米内，每轮施工50%，下一轮才可通行；桥梁每轮最多2编组。'
 'fire/bombard/suppress在回合内按秒级周期持续执行，逐次消耗弹药；炮兵冷却可跨回合保留秒数。火力受防护、展开、工事、疲劳、压制与情报时效影响。'
 'repair_equipment消耗备件修复待修装备，不补造已毁装备；resupply受运输队、燃油、库存、线路和桥梁约束。'
 'recon刷新指挥情报；restore_comms恢复联络；地图全知显示不等于实时侦察。'
 '命令有回合内通信延迟，行军受可用行动时间限制；人员和分类装备均由AFSIM计算。')
