"""Explicit estimates on sourced Wujiang identities; no historical strength claims."""
import copy
from gentactix import historical_initial as hi,historical_operations as ho
from tools.qa.historical_operational_fixture import inputs as ground_inputs
BATTLE='红军长征-强渡乌江-1935.01.01至1935.01.06'
NOTE='QA数值、几何和通行能力估计，不是1935年实力表、阵地、河槽或历史武器标定。'
def inputs():
 snapshot=hi.initial(BATTLE,'follow_on_jan3')['historical_initial'];params=ho.configuration_template(snapshot);_,old=ground_inputs()
 center={'lat':27.3148,'lng':107.402}
 for identity in params['actors']:
  actor=copy.deepcopy(next(iter(old['actors'].values())));red=identity.startswith('lm.red.')
  actor.update(personnel=1600 if identity=='lm.red.cmc_column' else 3000 if red else 1000,
               position={'lat':27.3138 if red else 27.33,'lng':107.402},type='步兵',attack_range_m=500,assumption=NOTE)
  actor['equipment']={k:0 for k in actor['equipment']};actor['equipment']['transport']=4 if identity=='lm.red.cmc_column' else 6 if red else 2
  actor['formation'].update(role='support' if identity=='lm.red.cmc_column' else 'infantry',motorized=False,
   fatigue=0,suppression=0,entrenchment=0,fuel_liters=0,spares=0,materials=0,shells=0,aa_rounds=0,signal=100,intel_age_min=0)
  params['actors'][identity]=actor
 params.update(clock={'start':'1935-01-03 12:00','time_step':'30分钟','assumption':NOTE},
  area={'center':center,'radius_km':30,'terrain_factor':1.5,'assumption':NOTE},assumptions=NOTE)
 params['rules'].update(bridge_enabled=True,goal_profile='crossing',required_survivors=2,motorized=False,convoy_km_per_turn=10,
  command_base_s=0,command_signal_s=0,command_distance_s_per_km=0)
 params['support']=copy.deepcopy(old['support'])
 for team,lat in (('red',27.31),('blue',27.34)):
  params['support'][team].update(position={'lat':lat,'lng':107.402},stock=0,inventory={k:0 for k in params['support'][team]['inventory']},assumption=NOTE)
 params['facility'].update(**center,name='江界河后续通行计算通道',progress=100,integrity=100,materials=0,capacity=2)
 params['facility']['crossing_model'].update(barrier={'a':{'lat':27.3148,'lng':107.397},'b':{'lat':27.3148,'lng':107.407}},
  banks={'a':{'lat':27.3145,'lng':107.402},'b':{'lat':27.3151,'lng':107.402}},throughput_work_per_hour=15000,
  equipment_work={'armor':10,'artillery':5,'air_defense':5,'engineer':0,'transport':2},
  build_progress_per_engineer_hour=10,supply_work_per_unit=100,assumption=NOTE)
 target={'lat':27.3158,'lng':107.402}
 params['goal'].update(team='red',profile='crossing',objective=target,exit=target,radius_km=.1,deadline_turn=6,
  required_turns=1,required_survivors=2,description='QA局部后续渡运集结；不代表整个强渡乌江。',assumption=NOTE)
 return snapshot,params
