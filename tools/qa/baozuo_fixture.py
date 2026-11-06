"""QA inputs over Baozuo's sourced roster; not a reconstructed deployment.

The versioned source keeps unknown facts null. These test estimates must never
be installed as production defaults or advertised as historical calibration.
"""
import copy

from gentactix import historical_initial as hi, historical_operations as ho

BATTLE = '红军长征-包座战役-1935.08.29至1935.09.01'
PHASE = 'baozuo_core'
NOTE = ('软件QA估计：人数、装备、效能、阵地、工事和库存未考证；'
        '不按战后残部或战果反推，不模拟真实山脊通视、夜间隐蔽与寺院布局。'
        '零装备表示本次测试未配置资源，不证明历史上没有该装备。')


def inputs():
    snapshot = hi.initial(BATTLE, PHASE)['historical_initial']
    params = ho.configuration_template(snapshot)
    phase = next(p for p in snapshot['definition']['phases'] if p['id'] == PHASE)
    center = copy.deepcopy(phase['geographic_scope']['center'])
    lat, lng = center['lat'], center['lng']
    rows = {}
    for i, regiment in enumerate((263, 264, 265, 266, 267, 268)):
        rows[f'lm.red.regiment{regiment}'] = (900, lat-.025+i*.001, lng+.004)
    rows['lm.red.regiment264'] = (900, lat+.0027, lng)
    rows['lm.red.division10'] = (1500, lat+.06, lng)
    rows['lm.blue.dajie_garrison'] = (500, lat-.0027, lng)
    rows['lm.blue.qiuji_garrison'] = (1200, lat+.055, lng)
    for i, regiment in enumerate((289, 291, 294)):
        rows[f'lm.blue.regiment{regiment}'] = (1800, lat-.031, lng+i*.003)
    for identity, actor in params['actors'].items():
        count, north, east = rows[identity]
        actor.update(personnel=count, type='步兵', speed=3, attack_range_m=1000,
            ground_control_radius_km=.2, position={'lat':north, 'lng':east},
            equipment={category:0 for category in actor['equipment']},
            logistics={'food':80, 'ammo':80},
            formation={'role':'infantry', 'motorized':False, 'fatigue':15,
                'suppression':0, 'entrenchment':15, 'dispersion_km2':.5,
                'protection':.15, 'fuel_liters':0, 'spares':0, 'materials':0,
                'shells':0, 'aa_rounds':0, 'reload_remaining':0,
                'intel_age_min':0, 'intel_confidence':80, 'signal':80},
            assumption=NOTE)
    params.update(clock={'start':'1935-08-29 18:00', 'time_step':'1小时', 'assumption':NOTE},
        area={'center':center, 'radius_km':15, 'terrain_factor':1.5, 'assumption':NOTE},
        assumptions=NOTE)
    params['rules'].update(era='long_march', motorized=False, air_support=False,
        goal_profile='assault', required_survivors=1, convoy_km_per_turn=1.5,
        bridge_enabled=False)
    params['support'] = {team:{
        'position':{'lat':lat+sign*.10, 'lng':lng}, 'stock':0,
        'inventory':{'fuel_liters':0, 'spares':0, 'materials':0, 'shells':0, 'aa_rounds':0},
        'assumption':NOTE+'本次只检查携行物资，未声明完成徒步/驮运补给建模。'}
        for team, sign in (('red',1), ('blue',-1))}
    params['facility'] = {'id':'calculation-hub', 'name':'计算汇总点（非史实桥梁）',
        **center, 'progress':0, 'integrity':0, 'materials':0, 'capacity':0, 'used':0}
    params['goal'] = {'team':'red', 'profile':'assault', 'objective':center,
        'exit':{'lat':lat+.08, 'lng':lng}, 'radius_km':.6,
        'deadline_turn':58, 'required_turns':1, 'required_survivors':1,
        'description':'QA攻点与阻援联合目标；不强制历史歼敌、投降或求吉寺战斗结果。',
        'assumption':NOTE}
    config = params['campaign']
    config['assumption'] = NOTE
    for identity, arrival in config['arrivals'].items():
        arrival.update(not_before='1935-08-29T18:00', assumption=NOTE)
    # Distinct, source-bounded test times. Only the window is sourced; these
    # regiment-specific choices do not claim a recovered historical timetable.
    for regiment, instant in ((291,'1935-08-30T19:00'), (289,'1935-08-30T22:00'),
                              (294,'1935-08-31T06:00')):
        config['arrivals'][f'lm.blue.regiment{regiment}'].update(
            not_before=instant, event_kind='battlefield_entry',
            reference_id=f'bz49-reg{regiment}-entry', assumption=NOTE+'时点取自史料窗口内的QA选择。')
    for identity, fort in config['fortifications'].items():
        fort.update(integrity=50 if identity.endswith('_garrison') else 0,
            degradation_per_shell=.5, assumption=NOTE)
    config['surrender'].update(enabled=True, range_m=300, suppression_threshold=80,
        ammo_threshold=0, assumption=NOTE)
    config['objective'].update(relief_regions=[
        {'center':{'lat':lat-.026, 'lng':lng+.003}, 'radius_km':1.2},
        # Control the route beyond the northern strongpoint; the published
        # sources disagree about its fall, so do not require its destruction.
        {'center':{'lat':lat+.075, 'lng':lng}, 'radius_km':.6}],
        min_force_fraction=.1, assumption=NOTE)
    return snapshot, params
