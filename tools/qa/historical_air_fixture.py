"""Explicit calculation inputs for the sourced Xiangxi local phase; not history."""
import copy
from gentactix import historical_initial,historical_operations as ho,air_assets
from tools.qa.historical_operational_fixture import inputs as ground_inputs
BATTLE='抗日战争-湘西会战-1945.04.09至1945.06.07'
NOTE='QA局部投入、位置、飞机油弹和效能估计，不是历史实力表、机场、真实任务日期或战损标定。'
def inputs():
    snapshot=historical_initial.initial(BATTLE,'dongkou_late_april')['historical_initial']
    p=ho.configuration_template(snapshot);_,old=ground_inputs();center={'lat':27.05272,'lng':110.5361}
    for identity,lat,number in (('ww2.cn.division57',center['lat']-.003,1800),('ww2.jp.division116',center['lat']+.003,2400)):
        actor=copy.deepcopy(next(iter(old['actors'].values())))
        actor.update(personnel=number,position={'lat':lat,'lng':center['lng']},assumption=NOTE)
        actor['equipment'].update(artillery=4,engineer=0,transport=4)
        actor['formation'].update(shells=48,aa_rounds=0)
        p['actors'][identity]=actor
    p.update(clock={'start':'1945-04-25 06:00','time_step':'30分钟','assumption':NOTE},
        area={'center':center,'radius_km':10,'terrain_factor':1.5,'assumption':NOTE},assumptions=NOTE)
    p['rules'].update(air_support=True,goal_profile='delay',required_survivors=1,convoy_km_per_turn=10)
    p['support']=copy.deepcopy(old['support'])
    for team,sign in (('red',-1),('blue',1)):
        p['support'][team].update(position={'lat':center['lat']+sign*.02,'lng':center['lng']},assumption=NOTE)
    p['facility']=copy.deepcopy(old['facility']);p['facility'].update(**center,integrity=0,progress=0,capacity=0)
    p['goal'].update(team='red',profile='delay',objective=center,exit={'lat':center['lat']-.05,'lng':center['lng']},radius_km=.5,
        deadline_turn=4,required_turns=1,required_survivors=1,description='QA局部迟滞；不代表全会战胜负或历史空袭。',assumption=NOTE)
    p['aviation']['ww2.cacw.group5']={'initial':{'committed':4,'ordnance':8,'fuel':16},
        'entry':{'lat':center['lat']-.03,'lng':center['lng']-.01},'rules':copy.deepcopy(air_assets.DEFAULT_RULES),'assumption':NOTE}
    return snapshot,p
