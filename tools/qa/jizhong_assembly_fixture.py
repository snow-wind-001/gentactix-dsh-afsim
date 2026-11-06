"""Explicit34identity QA parameters, not historical strengths or deployments."""
import copy
from gentactix import historical_initial as hi,historical_operations as ho
from tools.qa.historical_operational_fixture import inputs as base_inputs

NOTE='34身份QA：人数、分类装备、位置、机动与航空均为未标定测试参数；地面统一步兵模型只验身份/账/航空时序，不代表全部历史兵种、完整组织存续或反扫荡过程。'

def inputs():
    battle=next(x['battle'] for x in hi.catalog() if x['profile_id']=='AJ15-jizhong');snapshot=hi.initial(battle)['historical_initial'];p=ho.configuration_template(snapshot,'campaign');_,base=base_inputs();center={'lat':38.2,'lng':115.6};index={u['id']:u for u in snapshot['definition']['units']};counter={'red':0,'blue':0}
    p['clock']=dict(start='1942-05-01T00:00:00',time_step='30分钟',assumption=NOTE);p['area']=dict(center=center,radius_km=60,terrain_factor=1,assumption=NOTE)
    p['campaign_scope'].update(planning_end='1942-06-21T00:00:00',assumption=NOTE)
    for identity in p['actors']:
     team=index[identity]['team'];n=counter[team];counter[team]+=1;actor=copy.deepcopy(next(iter(base['actors'].values())))
     actor.update(personnel=500 if team=='red' else 4000,position={'lat':center['lat']+(0 if team=='red' else .2)+(n//9)*.01,'lng':center['lng']+(n%9)*.01},assumption=NOTE)
     actor['equipment'].update(armor=0,artillery=0,air_defense=0);actor['formation'].update(shells=0,aa_rounds=0)
     p['actors'][identity]=actor;p['campaign']['arrivals'][identity].update(not_before=p['clock']['start'],assumption=NOTE)
     p['campaign']['fortifications'][identity].update(integrity=0,degradation_per_shell=.1,assumption=NOTE)
    p['support']=copy.deepcopy(base['support'])
    for row in p['support'].values():row.update(position=dict(center),stock=50000,assumption=NOTE)
    p['facility']={**copy.deepcopy(base['facility']),**center};p['rules']=copy.deepcopy(base['rules']);p['rules'].update(air_support=True,goal_profile='assault',required_survivors=5)
    objective={'lat':38.0,'lng':115.6};p['goal']={**copy.deepcopy(base['goal']),'team':'red','profile':'assault','objective':objective,'exit':center,'radius_km':.3,'required_survivors':5,'deadline_turn':48,'required_turns':2,'termination_mode':'objectives','description':NOTE,'assumption':NOTE}
    p['campaign']['surrender'].update(enabled=False,range_m=100,suppression_threshold=80,ammo_threshold=0,assumption=NOTE)
    p['campaign']['objective'].update(relief_regions=[{'center':{'lat':38.0,'lng':115.65},'radius_km':.4},{'center':{'lat':38.0,'lng':115.55},'radius_km':.4}],min_force_fraction=.5,assumption=NOTE);p['campaign']['assumption']=NOTE;p['assumptions']=NOTE
    p['aviation']['ww2.jp.flight29'].update(initial={'committed':4,'ordnance':8,'fuel':16},entry={'lat':38.4,'lng':115.6},assumption=NOTE,
     availability={'version':'air-availability-1','start':'1942-05-01T00:30:00','end':None,'assumption':NOTE})
    for actor in p["actors"].values():actor["formation"].setdefault("motorized",True)
    return snapshot,p
