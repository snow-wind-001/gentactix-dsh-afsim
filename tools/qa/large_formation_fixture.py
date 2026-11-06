"""Sourced Wuhan identities, explicitly invented numerical QA deployment.

This is not a reconstructed 1938 deployment and must never become a corpus card.
"""
import copy
from gentactix import historical_initial as hi,historical_operations as ho
from tools.qa.historical_operational_fixture import inputs as base_inputs

NOTE='79单位扩容QA假设：坐标、兵额、配发、效能和到场非史实，仅验算规模、指挥与账本连续性。'
BATTLE='抗日战争-武汉会战-1938.06至1938.10'


def inputs():
    snapshot=hi.initial(BATTLE,'campaign_reference',version='1.1.0')['historical_initial']
    p=ho.configuration_template(snapshot,'campaign');_,base=base_inputs()
    center={'lat':30.59,'lng':114.31}
    p['clock']=dict(start='1938-06-12 00:00',time_step='30分钟',assumption=NOTE)
    p['area']=dict(center=center,radius_km=100,terrain_factor=1,assumption=NOTE)
    p['campaign_scope'].update(planning_end='1938-10-27 00:00',assumption=NOTE)
    for row in p['campaign_scope']['remainders'].values():
        row.update(policy='excluded_unquantified',assumption=NOTE+' 仅已列下级参加QA；未列余部未知且未投入，不宣称完整父级。')
    index={u['id']:u for u in snapshot['definition']['units']};counters={'red':0,'blue':0}
    prototype=next(iter(base['actors'].values()))
    for identity in p['actors']:
        team=index[identity]['team'];n=counters[team];counters[team]+=1
        a=copy.deepcopy(prototype);a.update(personnel=3000 if team=='red' else 8000,
            position={'lat':center['lat']+(n//10)*.004,'lng':center['lng']+(n%10)*.004+(.006 if team=='blue' else 0)},assumption=NOTE)
        a['equipment']['armor']=0;p['actors'][identity]=a
        p['campaign']['arrivals'][identity].update(not_before=p['clock']['start'],assumption=NOTE)
        p['campaign']['fortifications'][identity].update(integrity=0,degradation_per_shell=.1,assumption=NOTE)
    p['support']=copy.deepcopy(base['support'])
    for team,row in p['support'].items():row.update(position=dict(center),stock=50000,assumption=NOTE)
    p['facility']={**copy.deepcopy(base['facility']),**center}
    p['rules']=copy.deepcopy(base['rules']);p['rules'].update(goal_profile='assault',required_survivors=5)
    p['goal']={**copy.deepcopy(base['goal']),'team':'red','profile':'assault','objective':center,
        'exit':center,'radius_km':.3,'required_survivors':5,'deadline_turn':48,'required_turns':2,
        'termination_mode':'objectives','description':NOTE,'assumption':NOTE}
    p['campaign']['surrender'].update(enabled=False,range_m=100,suppression_threshold=80,ammo_threshold=0,assumption=NOTE)
    p['campaign']['objective'].update(relief_regions=[{'center':{'lat':30.61,'lng':114.31},'radius_km':.4},
        {'center':{'lat':30.59,'lng':114.35},'radius_km':.4}],min_force_fraction=.5,assumption=NOTE)
    p['campaign']['assumption']=NOTE;p['assumptions']=NOTE
    return snapshot,p
