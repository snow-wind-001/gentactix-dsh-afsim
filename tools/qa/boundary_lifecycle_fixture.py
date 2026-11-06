"""Three same-world stages with a sourced roster and explicit QA geometry."""
from tools.qa.operation_boundary_fixture import inputs as base_inputs
from tools.qa.campaign_plan_fixture import NOTE


def inputs():
    source, p = base_inputs()
    p['clock']['time_step'] = '15分钟'
    p['area']['terrain_factor'] = 1.0  # QA path length, not historical terrain.
    p['campaign_plan']['elimination_ends'] = False
    p['campaign_lifecycle'] = dict(version='campaign-lifecycle-1', finish_policy='all_phases', assumption=NOTE,
        phases=[dict(id='exit_window', label='QA阶段一：机动准备', goal_ids=[], minimum_duration_seconds=900,
                     operation_ids=[], assumption=NOTE),
                dict(id='wait_window', label='QA阶段二：后方保障', goal_ids=[], minimum_duration_seconds=1800,
                     operation_ids=[], assumption=NOTE),
                dict(id='continue_window', label='QA阶段三：返回并继续原任务',
                     goal_ids=['north', 'south', 'preserve'], minimum_duration_seconds=0,
                     operation_ids=[], assumption=NOTE)])
    for actor in p['actors'].values():
        actor['equipment']['transport'] = 20
    return source, p


def member(world):
    return next(u for u in world['red_units'] if u['historical_unit_id'] == 'ww2.cn.division159')


def seed_damage(world):
    """An explicit accounting fixture, never passed off as actual combat."""
    u = member(world)
    u['personnel'].update(current=280, casualties=20)
    next(e for e in u['equipment'] if e['category'] == 'transport').update(operational=18, damaged=1, destroyed=1)
    u['formation']['fatigue'] = 40
    # Seal the explicitly damaged T0 fixture, not a runtime phase transition.
    from gentactix import campaign_plan
    campaign_plan.initialize(world)
    return world


def partial_exit(world):
    route = world['mission']['definition']['operation_boundary']['routes'][0]
    return {k: (route['inside'][k]+route['outside'][k])/2 for k in ('lat','lng')}
