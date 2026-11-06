"""Six sourced Wanjialing identities with separate, minimal numerical QA inputs."""
import copy
from unittest.mock import patch

from gentactix import historical_initial as hi,historical_operations as ho,missions
from tools.qa.remaining_initial_fixture import inputs as generic_inputs,NOTE
from tools.upgrade_wanjialing import BATTLE


def inputs(*,enabled=True):
    d=hi.definition(BATTLE,'1.1.0')
    with patch.object(hi,'definition',return_value=d):s,p=generic_inputs(BATTLE,'oct7_attack')
    for row in p['oob_coverage']['remainders'].values():row.update(policy='excluded_unquantified',assumption=NOTE)
    c=p['campaign'];c['assumption']=NOTE
    for row in c['arrivals'].values():row.update(not_before=p['clock']['start'],assumption=NOTE)
    for row in c['fortifications'].values():row.update(integrity=10,degradation_per_shell=.1,assumption=NOTE)
    c['surrender'].update(enabled=False,range_m=100,suppression_threshold=90,ammo_threshold=10,assumption=NOTE)
    c['objective'].update(relief_regions=[{'center':copy.deepcopy(p['area']['center']),'radius_km':.1}],min_force_fraction=.1,assumption=NOTE)
    p['goal']['termination_mode']='objectives'
    if enabled:p['initial_command']={'version':'historical-command-baseline-1','assumption':NOTE+' 本次显式采用所选7日来源关系为初始作战指挥；不触发后续历史命令。'}
    else:p.pop('initial_command',None)
    return s,p


def session(*,enabled=True):
    s,p=inputs(enabled=enabled)
    world=ho.initial(s,p) if enabled else missions.from_definition(ho.definition(s,p,_frozen=True))
    return dict(id='initial-command-qa',turn_count=0,role_epoch=0,product_mode='historical',simulation_mode='open',
        execution_backend='narrative',time_step='30分钟',war_state=world)
