"""Explicit QA estimates over source identities, not historical deployments."""
import copy
from gentactix import anchors, combined_arms, historical_initial, historical_operations

BATTLE = '抗美援朝-第一次战役-1950.10.25至1950.11.05'
NOTE = 'QA建模估计；人数、装备、库存与坐标均非史实实到量或阵地测绘，不强制匹配历史战果。'


def inputs(phase='liangshuidong_opening'):
    initial = historical_initial.initial(BATTLE, phase)['historical_initial']
    parameters = historical_operations.configuration_template(initial)
    nodes = anchors.collect_available_nodes(BATTLE, battle=BATTLE)
    center = nodes['抗美援朝-西线-温井' if phase=='liangshuidong_opening' else '抗美援朝-西线-云山旧城']
    center = {'lat': center[0], 'lng': center[1]}
    source = {u['id']: u for u in initial['definition']['units']}
    relative = {
        'kw.cn.division115': (-.005, -.008), 'kw.cn.division116': (.006, -.006), 'kw.cn.division117': (.006, .007),
        'kw.us.cavalry8.battalion1': (.003, 0), 'kw.us.cavalry8.battalion2': (0, -.003),
        'kw.us.cavalry8.battalion3': (-.004, 0), 'kw.rok.regiment15': (.003, .004),
        'kw.us.artillery99.battery_c': (-.007, 0), 'kw.us.tank70.company_b.attached_platoon': (-.004, .001),
        'kw.cn.regiment354': (.008, 0), 'kw.rok.regiment2.battalion3': (.005, .001),
    }
    for identity, row in parameters['actors'].items():
        team = source[identity]['team']; tank = '.tank70.' in identity; artillery = '.artillery99.' in identity
        lat, lng = relative[identity]
        count = 2500 if identity=='kw.cn.regiment354' else 5000 if team=='red' else 25 if tank else 180 if artillery else 2000 if identity=='kw.rok.regiment15' else 650
        row.update(personnel=count, position={'lat':center['lat']+lat, 'lng':center['lng']+lng},
            type='装甲' if tank else '炮兵' if artillery else '步兵', speed=3, attack_range_m=1200 if tank else 1000,
            ground_control_radius_km=.2, equipment={'armor':4 if tank else 0,'artillery':4 if artillery else 0,
                'air_defense':0,'engineer':2,'transport':6 if team=='blue' else 0},
            logistics={'food':80,'ammo':80}, formation={'role':'armor' if tank else 'artillery' if artillery else 'infantry',
                'fatigue':10,'suppression':0,'entrenchment':10,'dispersion_km2':1,'protection':.15,
                'motorized':team=='blue','fuel_liters':1000 if team=='blue' else 0,
                'spares':10,'materials':4,'shells':300 if artillery else 0,'aa_rounds':0,'reload_remaining':0,
                'intel_age_min':0,'intel_confidence':80,'signal':90}, assumption=NOTE)
    opening = phase=='liangshuidong_opening'
    parameters.update(clock={'start':'1950-10-25 10:20' if opening else '1950-11-01 17:00','time_step':'30分钟','assumption':NOTE},
        area={'center':center,'radius_km':8,'terrain_factor':1.5,'assumption':NOTE}, assumptions=NOTE)
    parameters['rules']={**copy.deepcopy(combined_arms.RULES),'era':'korea','air_support':False,
        'motorized':True,'goal_profile':'delay','required_survivors':1,'convoy_km_per_turn':3,'bridge_enabled':False}
    parameters['support']={t:{'position':{'lat':center['lat']+sign*.015,'lng':center['lng']},'stock':300,
        'inventory':{'fuel_liters':4000,'spares':40,'materials':40,'shells':3000,'aa_rounds':0},'assumption':NOTE}
        for t,sign in (('red',1),('blue',-1))}
    parameters['facility']={'id':'calculation-hub','name':'计算汇总点（非史实桥梁）',**center,'progress':0,'integrity':0,'materials':0,'capacity':0,'used':0}
    parameters['goal']={'profile':'delay','objective':center,'exit':{'lat':center['lat']-.025,'lng':center['lng']},
        'radius_km':.4,'deadline_turn':3 if opening else 8,'required_turns':1,'required_survivors':1,
        'description':'QA局部延迟条件，非历史战役胜负或历史歼灭数量。','assumption':NOTE}
    return initial, parameters
