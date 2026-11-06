"""Software-only estimates for the nine new profiles, never historical defaults."""
import copy
from gentactix import historical_initial as hi, historical_operations as ho

IDS = {'LM03-chishui', 'LM05-dadu', 'LM06-maogong', 'LM08-lazikou',
       'LM09-red25', 'LM11-baizhang', 'LM12-wumeng', 'LM15-reunion', 'CP01-changping'}
NOTE = ('仅软件QA：人数、装备、库存、部署、路线及效能未历史标定；'
        '局部投入不等于军团实到，测试几何不是真实阵地。零装备表示此测试未配置。')


def cases():
    for row in hi.catalog():
        d = hi.definition(row['battle'])
        if d['id'] in IDS:
            for p in d['phases']:
                if p['id'] != 'campaign_reference':
                    yield row['battle'], p['id']


def inputs(battle, phase_id):
    s = hi.initial(battle, phase_id)['historical_initial']
    p = ho.configuration_template(s)
    phase = next(r for r in s['definition']['phases'] if r['id'] == phase_id)
    center = copy.deepcopy(phase.get('geographic_scope', {}).get('center', {'lat':35.9, 'lng':112.85}))
    lat, lng = center['lat'], center['lng']
    crossing = 'crossing_model' in p['facility']
    noncontact = bool(phase.get('interaction'))
    ancient = battle == '长平之战'
    units = {u['id']:u for u in s['definition']['units']}
    for i, (identity, a) in enumerate(p['actors'].items()):
        red = units[identity]['team'] == 'red'
        a.update(personnel=300, equipment={k:0 for k in a['equipment']},
            position={'lat':lat+i*.0001, 'lng':lng+(.002 if red else -.003)},
            type='步兵', speed=3, attack_range_m=100 if ancient else 1000,
            ground_control_radius_km=0, logistics={'food':80, 'ammo':80},
            formation={'role':'infantry', 'motorized':False, 'fatigue':0, 'suppression':0,
                'entrenchment':10, 'dispersion_km2':.5, 'protection':.15, 'fuel_liters':0,
                'spares':0, 'materials':0, 'shells':0, 'aa_rounds':0, 'reload_remaining':0,
                'intel_age_min':0, 'intel_confidence':80, 'signal':100}, assumption=NOTE)
    if not ancient:
        p['clock']['start'] = phase['execution_window']['start'].replace('T',' ')
    p['clock'].update(time_step='30分钟', assumption=NOTE)
    p.update(area={'center':center, 'radius_km':4, 'terrain_factor':1.5, 'assumption':NOTE}, assumptions=NOTE)
    p['rules'].update(required_survivors=1, convoy_km_per_turn=1.5,
        command_base_s=0, command_signal_s=0, command_distance_s_per_km=0)
    for team, sign in (('red',1), ('blue',-1)):
        p['support'][team].update(position={'lat':lat+.01,'lng':lng+sign*.02}, stock=0,
            inventory={k:0 for k in p['support'][team]['inventory']}, assumption=NOTE)
    p['facility'].update(id='qa-'+phase_id, name='QA通道' if crossing else 'QA计算汇总点',
        **center, progress=100 if crossing else 0, integrity=100 if crossing else 0,
        capacity=2 if crossing else 0)
    if crossing:
        p['facility']['crossing_model'].update(
            barrier={'a':{'lat':lat-.02,'lng':lng},'b':{'lat':lat+.02,'lng':lng}},
            banks={'a':{'lat':lat,'lng':lng+.001},'b':{'lat':lat,'lng':lng-.001}},
            throughput_work_per_hour=1200,
            equipment_work={'armor':10,'artillery':5,'air_defense':5,'engineer':0,'transport':2},
            build_progress_per_engineer_hour=10, supply_work_per_unit=100, assumption=NOTE)
    # The existing breakout/delay contract uses a 600 m exit radius.
    # Put the exit outside the starting positions and require two rounds.
    exit_task = p['goal']['profile'] in ('breakout', 'delay')
    target = {'lat':lat,'lng':lng-.002 if crossing else lng+.010 if exit_task else lng}
    p['goal'].update(objective=target, exit=copy.deepcopy(target), radius_km=.15,
        deadline_turn=2, required_turns=2, required_survivors=1,
        description='仅检验局部软件状态、机动和判定，不是全程历史验收。', assumption=NOTE)
    return s, p
