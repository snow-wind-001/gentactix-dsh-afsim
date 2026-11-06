"""Full22 registered input priors, explicit all-hold QA candidate; not an executor."""
import copy
from functools import lru_cache


@lru_cache(maxsize=1)
def _initial():
    from backend.scenario_builder import historical_basis
    from gentactix import historical_operations
    basis = historical_basis('抗日战争-万家岭战役-1938.09下旬至1938.10',
        force_scope='campaign', campaign_window_id='WJL-oct6-10',
        campaign_window_version='1.5.0', termination_mode='objectives', time_step='1小时')
    return historical_operations.initial(basis['initial'], basis['configuration_template'])


def session():
    return dict(id='full22-preview-pages-qa', role_epoch=0, turn_count=0,
        agent_mode='native', execution_backend='narrative', time_step='1小时',
        product_mode='historical', simulation_mode='open', war_state=copy.deepcopy(_initial()))


def candidate(world):
    from verify_campaign_plan_backends import proposal
    from gentactix import missions, movement_feedback, support_dynamics as sd
    value = proposal(world)
    cfg = sd.configuration(world)
    value['sustainment_ledger'] = dict(version=sd.VERSION, units=[])
    for (_, unit), row, ledger in zip(missions.units(world), value['unit_updates'], value['resource_ledger']['units']):
        receipt = sd.expected(cfg, unit, 'hold', 3600)
        row['logistics']['food'] = unit['logistics']['food'] - receipt['consumed']
        ledger['food_spent'] = receipt['consumed']
        row['sustainment'] = dict(version=sd.VERSION,
            **{k: receipt[k] for k in ('shortage_hours', 'noncombat_remainder')})
        value['sustainment_ledger']['units'].append(dict(unit=unit['name'], **receipt))
        following = {**unit, 'sustainment': row['sustainment']}
        row['formation']['fatigue'] = movement_feedback.fatigue_value(world, unit, 'hold', 0, following=following)
    return value
