"""Explicit QA estimates over sourced Jialing axes; never production defaults."""
import copy

from gentactix import historical_initial as hi, historical_operations as ho

BATTLE = '红军长征-嘉陵江战役-1935.03.28至1935.04.21'
PHASES = ('tazishan_opening', 'yuankou_opening', 'jianxikou_langzhong', 'jianmen_apr2')
NOTE = ('软件QA估计：本地投入人数、装备、位置、时钟、效能和库存均未历史标定。'
        '军属参战部只测试局部投入，不代表全军实到。现代聚落点不是真实渡口或阵地。'
        '零装备表示本次未配置资源，不是历史上没有。')


def inputs(phase_id=PHASES[0], *, throughput=1200):
    snapshot = hi.initial(BATTLE, phase_id)['historical_initial']
    p = ho.configuration_template(snapshot)
    phase = next(r for r in snapshot['definition']['phases'] if r['id'] == phase_id)
    center = copy.deepcopy(phase['geographic_scope']['center'])
    lat, lng = center['lat'], center['lng']
    crossing = phase_id != PHASES[-1]
    units = {u['id']: u for u in snapshot['definition']['units']}
    for identity, actor in p['actors'].items():
        red = units[identity]['team'] == 'red'
        gun = units[identity]['role'] == 'support'
        actor.update(personnel=120 if gun else 300 if identity == 'jl.red.hq_training' else 900 if red else 600,
            position={'lat':lat, 'lng':lng + (.004 if gun else .0015 if red else -.025) if crossing
                      else lng + (.0027 if red else -.0027)},
            type='炮兵' if gun else '步兵', speed=3,
            attack_range_m=500 if gun else 1000, ground_control_radius_km=.1,
            equipment={k:4 if gun and k == 'artillery' else 0 for k in actor['equipment']},
            logistics={'food':80, 'ammo':80},
            formation={'role':'support' if gun else 'infantry', 'motorized':False,
                'fatigue':0, 'suppression':0, 'entrenchment':10, 'dispersion_km2':.5,
                'protection':.15, 'fuel_liters':0, 'spares':0, 'materials':0,
                'shells':240 if gun else 0, 'aa_rounds':0, 'reload_remaining':0,
                'intel_age_min':0, 'intel_confidence':80, 'signal':100}, assumption=NOTE)
    p.update(clock={'start':phase['execution_window']['start'].replace('T',' '),
                    'time_step':'30分钟', 'assumption':NOTE},
             area={'center':center, 'radius_km':4, 'terrain_factor':1.5, 'assumption':NOTE},
             assumptions=NOTE)
    profile = 'crossing' if crossing else 'assault'
    survivors = 2 if phase_id == PHASES[0] else 1
    p['rules'].update(era='long_march', motorized=False, air_support=False,
        goal_profile=profile, required_survivors=survivors, convoy_km_per_turn=1.5,
        bridge_enabled=crossing, command_base_s=0, command_signal_s=0,
        command_distance_s_per_km=0, artillery_range_m=6000)
    for team, sign in (('red',1), ('blue',-1)):
        p['support'][team].update(position={'lat':lat+.01, 'lng':lng+sign*.02}, stock=0,
            inventory={k:0 for k in p['support'][team]['inventory']}, assumption=NOTE+'仅携行库存。')
    p['facility'].update(id='qa-'+phase_id, name='QA登记渡运能力（非已核桥梁）' if crossing else 'QA计算汇总点',
        **center, progress=100 if crossing else 0, integrity=100 if crossing else 0,
        materials=0, capacity=2 if crossing else 0, used=0)
    if crossing:
        p['facility']['crossing_model'].update(
            barrier={'a':{'lat':lat-.02,'lng':lng}, 'b':{'lat':lat+.02,'lng':lng}},
            banks={'a':{'lat':lat,'lng':lng+.001}, 'b':{'lat':lat,'lng':lng-.001}},
            throughput_work_per_hour=throughput,
            equipment_work={'armor':10,'artillery':5,'air_defense':5,'engineer':0,'transport':2},
            build_progress_per_engineer_hour=10, supply_work_per_unit=100,
            assumption=NOTE+'以共享容量抽象渡运，不代表有实体桥、真实船数、水流或单船往返。')
    target = {'lat':lat, 'lng':lng-.002 if crossing else lng}
    p['goal'].update(team='red', profile=profile, objective=target, exit=copy.deepcopy(target),
        radius_km=.15, deadline_turn=8, required_turns=1, required_survivors=survivors,
        description='QA完成登记渡运并集结；不代表攻克阆中或完整战役。' if crossing else 'QA剑门关局部攻坚，不强制历史歼敌结果。',
        assumption=NOTE)
    return snapshot, p
