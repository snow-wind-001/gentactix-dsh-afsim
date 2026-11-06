"""Explicit test inputs over sourced Xiangjiang identities, not production seeds."""
import copy
from gentactix import historical_initial as hi,historical_operations as ho,combined_arms
BATTLE='红军长征-湘江战役-1934.11.25至1934.12.01'
NOTE='软件QA估计：本地投入、装备、位置、工事、库存和效能非史实实到；不按战果反推，不强制历史胜负。无车辆、航空或防空装备；未建模真实山脊通视和全部渡江纵队。'

def inputs(phase_id='xinxu_nov28'):
 s=hi.initial(BATTLE,phase_id)['historical_initial'];p=ho.configuration_template(s)
 phase=next(v for v in s['definition']['phases'] if v['id']==phase_id);center=copy.deepcopy(phase['geographic_scope']['center'])
 source={u['id']:u for u in s['definition']['units']};indices={'red':0,'blue':0}
 for identity,a in p['actors'].items():
  team=source[identity]['team'];i=indices[team];indices[team]+=1;gun=source[identity]['role']=='support'
  a.update(personnel=150 if gun else 1800 if team=='blue' else 900,
   type='炮兵' if gun else '步兵',speed=3,attack_range_m=500 if gun else 1000,
   ground_control_radius_km=.2,position={'lat':center['lat']+(.015 if gun else .0027 if team=='red' else -.0027),'lng':center['lng']+i*.0015},
   equipment={'armor':0,'artillery':4 if gun else 0,'air_defense':0,'engineer':0,'transport':0},
   logistics={'food':80,'ammo':80},formation={'role':'support' if gun else 'infantry','motorized':False,
    'fatigue':15,'suppression':0,'entrenchment':15,'dispersion_km2':.5,'protection':.15,
    'fuel_liters':0,'spares':0,'materials':0,'shells':240 if gun else 0,'aa_rounds':0,'reload_remaining':0,
    'intel_age_min':0,'intel_confidence':80,'signal':80},assumption=NOTE)
 p.update(clock={'start':phase['execution_window']['start'].replace('T',' '),'time_step':'30分钟','assumption':NOTE},
  area={'center':center,'radius_km':3,'terrain_factor':1.5,'assumption':NOTE},assumptions=NOTE)
 p['rules']={**copy.deepcopy(combined_arms.RULES),'era':'long_march','air_support':False,'motorized':False,
  'artillery_range_m':6000,'goal_profile':'delay','required_survivors':1,'convoy_km_per_turn':1.5,'bridge_enabled':False}
 p['support']={team:{'position':{'lat':center['lat']+sign*.02,'lng':center['lng']},'stock':0,
  'inventory':{'fuel_liters':0,'spares':0,'materials':0,'shells':0,'aa_rounds':0},'assumption':NOTE+'本次仅检验携行物资，不声称完成徒步补给运输。'} for team,sign in (('red',1),('blue',-1))}
 p['facility']={'id':'calculation-hub','name':'计算汇总点（非史实桥梁）',**center,'progress':0,'integrity':0,'materials':0,'capacity':0,'used':0}
 p['goal']={'team':'red','profile':'delay','objective':center,'exit':{'lat':center['lat']+.012,'lng':center['lng']},
  'radius_km':.25,'deadline_turn':8,'required_turns':2,'required_survivors':1,
  'description':'保护向北通路的局部迟滞检验；不等于军委纵队已过江或全战役胜利。','assumption':NOTE}
 return s,p
