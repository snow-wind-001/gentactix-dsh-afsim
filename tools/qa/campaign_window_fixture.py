"""Invented QA resources over a sourced window; never a historical deployment."""
import copy
from gentactix import historical_initial as hi, historical_operations as ho, campaign_windows as cw
from tools.qa.large_formation_fixture import inputs as large_inputs
from tools.upgrade_wanjialing import BATTLE

NOTE='会战窗口链路QA估计：所有兵额、装备、坐标、库存、到场与效能仅验合同与恢复，未经历史标定。'


def inputs():
    s=hi.initial(BATTLE,'oct6_orders',version='1.3.0')['historical_initial']
    p=ho.configuration_template(s,'campaign',window=cw.pin('WJL-oct6-10'))
    _,base=large_inputs()
    for key in ('area','rules','support','facility','goal','assumptions'):
        p[key]=copy.deepcopy(base[key])
    center={'lat':29.35,'lng':115.65}
    p['area'].update(center=center,radius_km=30,assumption=NOTE)
    p['clock']['assumption']=NOTE
    p['campaign_scope']['assumption']=NOTE
    for r in p['campaign_scope']['remainders'].values():
        r.update(policy='excluded_unquantified',assumption=NOTE+' 未核余部不投入，已列下级不能代表完整父级。')
    prototype=next(iter(base['actors'].values()))
    for n,identity in enumerate(p['actors']):
        actor=copy.deepcopy(prototype)
        actor.update(position={'lat':center['lat']+n*.0001,'lng':center['lng']},assumption=NOTE)
        actor['formation']['motorized']=True
        p['actors'][identity]=actor
        p['campaign']['arrivals'][identity].update(not_before=p['clock']['start'],assumption=NOTE)
        p['campaign']['fortifications'][identity].update(integrity=0,degradation_per_shell=.1,assumption=NOTE)
    for row in p['support'].values():row.update(position=dict(center),assumption=NOTE)
    p['facility'].update(center)
    p['goal'].update(objective=dict(center),exit=dict(center),description=NOTE,assumption=NOTE,termination_mode='objectives')
    p['campaign']['surrender']=copy.deepcopy(base['campaign']['surrender'])
    p['campaign']['objective']=dict(relief_regions=[{'center':{'lat':29.36,'lng':115.65},'radius_km':.4}],min_force_fraction=.5,assumption=NOTE)
    p['campaign']['assumption']=NOTE;p['assumptions']=NOTE
    return s,p
