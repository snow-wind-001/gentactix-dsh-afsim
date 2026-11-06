"""Small, explicitly nonhistorical inputs for operational-process regressions."""
import copy
from gentactix import campaign,historical_initial as hi
from tools.qa.historical_operational_fixture import inputs as base_inputs

NOTE='软件QA假设，新增过程不是徐州史实，不能安装为历史档案。'

def inputs():
    snapshot,params=base_inputs();snapshot=copy.deepcopy(snapshot);params=copy.deepcopy(params)
    phase=next(p for p in snapshot['definition']['phases'] if p['id']==snapshot['phase_id'])
    phase['process_requirements']=[{'kind':'combined_operation','scope':NOTE,'evidence':copy.deepcopy(phase['evidence'])}]
    phase['execution_window']={'start':'1938-03-31T00:00','end':'1938-04-01T00:00',
        'kind':'model_scope_limit','note':NOTE,'evidence':copy.deepcopy(phase['evidence'])}
    snapshot['definition_hash']=hi.digest(snapshot['definition'])
    params['goal']['profile']='assault';params['rules']['goal_profile']='assault'
    ids=list(params['actors']);config=campaign.template(snapshot,ids);config['assumption']=NOTE
    for identity,row in config['arrivals'].items():row.update(not_before='1938-03-31T00:00',assumption=NOTE)
    config['arrivals']['ww2.jp.sakamoto_detachment']['not_before']='1938-03-31T01:00'
    for identity,row in config['fortifications'].items():row.update(integrity=100 if 'seya' in identity else 0,degradation_per_shell=.5,assumption=NOTE)
    config['surrender'].update(enabled=True,range_m=1000,suppression_threshold=80,ammo_threshold=0,assumption=NOTE)
    config['objective'].update(relief_regions=[{'center':copy.deepcopy(params['goal']['objective']),'radius_km':.6}],min_force_fraction=.1,assumption=NOTE)
    params['campaign']=config
    return snapshot,params
