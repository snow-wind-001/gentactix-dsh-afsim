"""Explicit QA inputs over sourced Pingxingguan IDs; not measured deployments."""
import copy
from gentactix import combined_arms, historical_initial, historical_operations

BATTLE='抗日战争-平型关伏击战-1937.09.25'
NOTE='QA数值与局部部署假设；保留公开番号和部署方位，不宣称实到人数、实测射界或完整历史重建。'


def inputs():
    snapshot=historical_initial.initial(BATTLE,'qiaogou')['historical_initial']
    params=historical_operations.configuration_template(snapshot)
    center={'lat':39.34,'lng':113.98}
    positions=[(39.338,113.973),(39.341,113.98),(39.345,113.989),(39.35,114.005),(39.342,113.982),(39.346,113.99)]
    names={u['id']:u for u in snapshot['definition']['units']}
    for (identity,p),(lat,lng) in zip(params['actors'].items(),positions):
        team=names[identity]['team']
        p.update(personnel=1800 if team=='red' else 350,position={'lat':lat,'lng':lng},
            equipment={'armor':0,'artillery':0,'air_defense':0,'engineer':2,'transport':4 if team=='red' else 24},
            type='步兵',speed=3,attack_range_m=1000,ground_control_radius_km=.2,
            logistics={'food':80,'ammo':80},formation={'role':'infantry' if team=='red' else 'support','fatigue':10,'suppression':0,
                'motorized':team=='blue','entrenchment':0,'dispersion_km2':1,'protection':.15,'fuel_liters':1000 if team=='blue' else 0,'spares':4,'materials':4,
                'shells':0,'aa_rounds':0,'reload_remaining':0,'intel_age_min':0,'intel_confidence':80,'signal':85},assumption=NOTE)
    params.update(clock={'start':'1937-09-25 07:00','time_step':'30分钟','assumption':NOTE+'7时许取整为计算时钟，另有8时等异文。'},
        area={'center':center,'radius_km':15,'terrain_factor':1.8,'assumption':NOTE},assumptions=NOTE)
    params['rules'].update(era='ww2',air_support=False,motorized=True,goal_profile='delay',required_survivors=1,
                          convoy_km_per_turn=3,bridge_enabled=False)
    params['support']={team:{'position':{'lat':center['lat']+sign*.03,'lng':center['lng']},'stock':200,
        'inventory':{'fuel_liters':0,'spares':40,'materials':40,'shells':0,'aa_rounds':0},'assumption':NOTE}
        for team,sign in (('red',-1),('blue',1))}
    params['facility']={'id':'calculation-hub','name':'计算汇总点（非史实桥梁）',**center,'progress':0,'integrity':0,'materials':0,'capacity':0,'used':0}
    params['goal']={'profile':'delay','objective':center,'exit':{'lat':39.32,'lng':113.96},'radius_km':.5,
        'deadline_turn':12,'required_turns':1,'required_survivors':1,'description':'窗口内保留红方单位并阻止蓝方抵达出口；局部规则测试，非历史胜负定义。','assumption':NOTE}
    return snapshot,params
