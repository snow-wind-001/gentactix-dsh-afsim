"""Explicit QA inputs over real roster IDs; NOT a historical deployment dataset."""
import copy
from gentactix import combined_arms, historical_initial

BATTLE = '抗日战争-徐州会战总览-1938.01至1938.05'
NOTE = 'QA数值假设，仅验证真实番号绑定与原生运算；不是已考证人数、武器效能或部署。'


def inputs():
    baseline = historical_initial.initial(BATTLE, 'taierzhuang')['historical_initial']
    center = {'lat': 34.55528, 'lng': 117.73917}
    actors = {}
    rows = [('ww2.cn.division31', 6000, 34.55528, 117.73817, 0, 8),
            ('ww2.jp.seya_detachment', 3000, 34.56128, 117.73917, 8, 12),
            ('ww2.jp.sakamoto_detachment', 1800, 34.56428, 117.74117, 0, 6)]
    for identity, strength, lat, lng, armor, artillery in rows:
        actors[identity] = {'personnel': strength, 'position': {'lat': lat, 'lng': lng},
            'equipment': {'armor': armor, 'artillery': artillery, 'air_defense': 0, 'engineer': 8, 'transport': 20},
            'type': '步兵', 'speed': 3, 'attack_range_m': 1500, 'ground_control_radius_km': .2,
            'logistics': {'food': 80, 'ammo': 80},
            'formation': {'role': 'infantry', 'fatigue': 10, 'suppression': 0, 'entrenchment': 10,
                'dispersion_km2': 3, 'protection': .15, 'fuel_liters': 2000, 'spares': 20,
                'materials': 16, 'shells': 120, 'aa_rounds': 0, 'reload_remaining': 0,
                'intel_age_min': 10, 'intel_confidence': 80, 'signal': 90}, 'assumption': NOTE}
    cfg = {**copy.deepcopy(combined_arms.RULES), 'era': 'ww2', 'air_support': False,
           'motorized': True, 'goal_profile': 'delay', 'required_survivors': 1,
           'convoy_km_per_turn': 15, 'bridge_enabled': False}
    params = {'format': 'historical-operation-1', 'phase_id': 'taierzhuang',
        'clock': {'start': '1938-03-31 00:00', 'time_step': '30分钟', 'assumption': NOTE},
        'area': {'center': center, 'radius_km': 20, 'terrain_factor': 1.0, 'assumption': NOTE},
        'actors': actors, 'rules': cfg,
        'support': {team: {'position': {'lat': center['lat'] + sign * .02, 'lng': center['lng']},
            'stock': 480, 'inventory': {'fuel_liters': 12000, 'spares': 120, 'materials': 120,
                                      'shells': 12000, 'aa_rounds': 0}, 'assumption': NOTE}
                    for team, sign in [('red', -1), ('blue', 1)]},
        'facility': {'id': 'calculation-hub', 'name': '计算汇总点（不是史实桥梁）',
            **center, 'progress': 100, 'integrity': 100, 'materials': 0, 'capacity': 100, 'used': 0},
        'goal': {'profile': 'delay', 'objective': center,
            'exit': {'lat': center['lat'] - .03, 'lng': center['lng']}, 'radius_km': .5,
            'deadline_turn': 2, 'required_turns': 1, 'required_survivors': 1,
            'description': 'QA目标：截止时保持至少一个红方部队且蓝方未到出口；非全会战胜负。', 'assumption': NOTE},
        'assumptions': NOTE}
    return baseline, params
