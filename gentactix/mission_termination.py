"""Shared completion policy for Python goals, native WSF and planning budgets."""

def objective_driven(spec):
    mode=spec.get('termination_mode','deadline')
    if mode not in ('objectives','deadline'):
        raise ValueError('结束方式须为objectives或deadline')
    return mode=='objectives'


def outcome(spec,turn,progress,condition,owner_alive,*,wait_until_deadline=False):
    objectives=objective_driven(spec)
    success=(progress>=spec['required_turns'] if objectives or not wait_until_deadline
             else condition and turn>=spec['deadline_turn'])
    return success,success or not owner_alive or (not objectives and turn>=spec['deadline_turn'])


def native_expressions(spec,owner,*,wait_until_deadline=False):
    if spec.get('campaign_plan'):
        # A new DAG is scored from validated physical results by the common
        # host evaluator; legacy native point goals must not end it early.
        return 'false','false'
    objectives=objective_driven(spec)
    success=(f'progress>={spec["required_turns"]}' if objectives or not wait_until_deadline
             else f'condition && turn>={spec["deadline_turn"]}')
    terminal=f'success || {owner}Alive==0'+('' if objectives else f' || turn>={spec["deadline_turn"]}')
    return success,terminal


def planning_turns(spec,turn):
    """Open missions use a rolling reference horizon, never a hidden deadline."""
    return spec['deadline_turn'] if objective_driven(spec) else max(0,spec['deadline_turn']-turn)
