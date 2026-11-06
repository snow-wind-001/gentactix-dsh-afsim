"""Read-only unit proposals over DSH's registered tools and public trajectory.

No new scheduler, candidate store, state updater or JSON repair. The normal
command path validates the same proposal again before the whole-turn commit.
"""
import copy
from types import SimpleNamespace

from gentactix import commands, missions
from . import afsim_state, extensions

TOOL = 'submit_unit_order'
VERSION = 'unit-order-proposal-1'
TEXT_LIMIT = 1000


def context(session, prepared, identity, *, operation_id):
    value = afsim_state.operation_context(session)
    value['session']['agent_mode'] = session.get('agent_mode')
    value['unit_order'] = dict(version=VERSION, operation_id=operation_id,
        unit_id=identity, world_version=prepared['world_version'],
        state=copy.deepcopy(prepared['state']))
    return value


def validate(ctx, args):
    args = extensions.canonical_numbers(args)
    session = ctx['session']; spec = ctx.get('unit_order')
    if (not isinstance(spec, dict) or spec.get('version') != VERSION
            or not isinstance(spec.get('operation_id'), str)
            or not spec['operation_id'] or spec.get('world_version') != commands.world_version(session)):
        raise ValueError('本次操作未开放该单位候选工具，或观察版本已失效')
    identity = spec.get('unit_id'); cs = spec['state']
    if identity not in cs['unit_agents']:
        raise ValueError('本次原生会话未绑定该单位Agent')
    if not isinstance(args, dict) or set(args) != {'order', 'rationale', 'expected_effect'}:
        raise ValueError('单位候选只接受order、rationale、expected_effect')
    if any(not isinstance(args[k], str) or not args[k].strip() or len(args[k]) > TEXT_LIMIT
           for k in ('rationale', 'expected_effect')):
        raise ValueError('公开依据和预期须为1—1000字的非空文本，不接受内部推理或自动截断')
    draft = args['order']
    if not isinstance(draft, dict):
        raise ValueError('原生Agent的order须为动作对象')
    allowed = set(commands.DRAFT_FIELDS) - {'id'}
    extra = set(draft) - allowed
    if extra:
        raise ValueError('order含不可用字段：' + '、'.join('order.' + str(key) for key in sorted(extra))
            + '；允许字段：' + '、'.join(sorted(allowed))
            + '。人员、装备、疲劳等状态由后续过程结算；单位Agent只提交命令，不得写入状态字段。')
    if 'unit_id' in draft and draft['unit_id'] != identity:
        raise ValueError('不能改写单位身份；当前会话绑定=' + str(identity))
    checked = commands.replace_queue(session, [{**copy.deepcopy(draft), 'unit_id': identity}],
        control_team=cs['control_team'], director=cs['director'], no_fire=cs['no_fire'], intent=cs['intent'])
    commands.step_order(session, checked['orders'][0], cs)
    return copy.deepcopy(args)


def _proof(ctx, args):
    spec = ctx['unit_order']
    fields = dict(version=VERSION, unit_id=spec['unit_id'], operation_id=spec['operation_id'],
                  world_version=spec['world_version'])
    return {**fields, 'proposal_digest': missions.digest({**fields, 'candidate': args})}


def execute(ctx, payload):
    try:
        if payload.get('tool') != TOOL:
            raise ValueError('未知单位候选工具')
        args = validate(ctx, payload.get('args'))
        return dict(ok=True, readonly=True, **_proof(ctx, args),
                    scope='单位候选已校验；未执行动作、提交世界或消费队列和持续任务')
    except (ValueError, KeyError, TypeError) as exc:
        return dict(ok=False, readonly=True, version=VERSION, error=str(exc))


def submitted(observer, ctx, *, start=0):
    accepted = None
    for args, reply, event in extensions.public_tool_results(observer, TOOL, start=start):
        if reply.get('version') != VERSION:
            continue
        args = validate(ctx, args)
        proof = _proof(ctx, args)
        if any(reply.get(k) != v for k, v in proof.items()):
            raise ValueError('原生单位候选指纹与本单位、观察版本、操作或完整参数不一致')
        accepted = args, dict(source='dsh_native_unit_order_tool', **proof, **event)
    return accepted


INSTRUCTION = ('调用submit_unit_order({order:动作对象,rationale:本单位公开依据,expected_effect:预期效果})'
    '提交候选；公开依据及预期各1—1000字，不输出内部推理。失败时依据工具原因修正后重新提交，'
    '成功回执next_action=final_response后直接简短确认，不再继续调用工具或拼接长JSON。'
    'formation、fatigue等状态字段不属于命令，由后续过程结算，不在候选中修改。'
    '工具成功不表示已执行，整轮仍由宿主原子提交。'
    '仅在本次工具不可用时，兼容返回相同三个字段的JSON；不得用最终文字覆盖已通过的结构化候选。')


PLANNER_TOOL = 'submit_planner_orders'
PLANNER_VERSION = 'planner-order-proposal-1'
PLANNER_FIELDS = {'unit_id', 'action', 'duration', 'destination', 'target_id',
                  'air_pool', 'participation', 'rationale', 'expected_effect'}


def planner_context(session, prepared, covered_names, *, operation_id):
    """Bind the existing proposal protocol to the exact remaining batch."""
    value = afsim_state.operation_context(session)
    value['session']['agent_mode'] = session.get('agent_mode')
    required = [dict(id=identity, team=entry['team'], name=entry['name'])
        for identity, (entry, unit) in commands.resolve_units(session, prepared['state']).items()
        if entry['name'] not in covered_names and commands.available(unit)]
    value['planner_orders'] = dict(version=PLANNER_VERSION, operation_id=operation_id,
        world_version=prepared['world_version'],
        command_revision=commands.state(session)['revision'],
        required_units=required, state=copy.deepcopy(prepared['state']))
    return value


def validate_planner(ctx, args):
    # Reuse the existing checked read-only scope once for the whole batch;
    # resolving every order must not revalidate the same campaign repeatedly.
    with missions.validation_scope(ctx['session'].get('war_state')):
        return _validate_planner(ctx, args)


def _validate_planner(ctx, args):
    args = extensions.canonical_numbers(args)
    session = ctx['session']; spec = ctx.get('planner_orders')
    if (session.get('execution_backend') != 'afsim' or session.get('simulation_mode', 'open') != 'open'
            or not isinstance(spec, dict) or spec.get('version') != PLANNER_VERSION
            or not isinstance(spec.get('operation_id'), str) or not spec['operation_id']
            or spec.get('world_version') != commands.world_version(session)
            or spec.get('command_revision') != commands.state(session)['revision']):
        raise ValueError('本次操作未开放批量候选工具，或战局／命令版本已失效')
    if not isinstance(args, dict) or set(args) != {'orders'} or not isinstance(args['orders'], list):
        raise ValueError('批量候选只接受orders数组，不能提交权威状态')
    required = {row['id'] for row in spec['required_units']}
    if not required:
        raise ValueError('本轮没有需要批量规划的单位')
    seen = set()
    for draft in args['orders']:
        if not isinstance(draft, dict) or set(draft) - PLANNER_FIELDS:
            raise ValueError('批量命令包含非法字段；只提交行动及公开依据，不提交状态')
        identity = draft.get('unit_id')
        if not isinstance(identity, str) or identity not in required:
            raise ValueError('单位不在本轮批量名单：' + str(identity)[:96]
                + '；人工、单位Agent与已准备任务不能由批量规划覆盖')
        if identity in seen:
            raise ValueError('批量命令重复单位ID：' + identity)
        seen.add(identity)
        if any(not isinstance(draft.get(k), str) or not draft[k].strip()
               or len(draft[k]) > TEXT_LIMIT for k in ('rationale', 'expected_effect')):
            raise ValueError('每个批量决策须有1—1000字的公开依据与预期')
        normalized = {k: copy.deepcopy(v) for k, v in draft.items()
                      if k not in ('rationale', 'expected_effect')}
        normalized.setdefault('duration', 'next')
        if (normalized['duration'] not in ('next', 'until_arrived')
                or normalized['duration'] == 'until_arrived' and normalized.get('action') != 'move'):
            raise ValueError('批量自主规划持续方式非法')
        commands.step_order(session, normalized, spec['state'])
    if seen != required:
        raise ValueError('批量规划遗漏可行动单位：' + ', '.join(sorted(required - seen)))
    return copy.deepcopy(args)


def _planner_proof(ctx, args):
    spec = ctx['planner_orders']
    fields = dict(version=PLANNER_VERSION, operation_id=spec['operation_id'],
        world_version=spec['world_version'], command_revision=spec['command_revision'],
        required_units_digest=missions.digest(sorted(r['id'] for r in spec['required_units'])))
    return {**fields, 'proposal_digest': missions.digest({**fields, 'candidate': args})}


def execute_planner(ctx, payload):
    try:
        if payload.get('tool') != PLANNER_TOOL:
            raise ValueError('未知批量候选工具')
        args = validate_planner(ctx, payload.get('args'))
        return dict(ok=True, readonly=True, **_planner_proof(ctx, args),
            order_count=len(args['orders']), scope='完整批量候选已校验；未执行、写世界或消费队列')
    except (ValueError, KeyError, TypeError) as exc:
        return dict(ok=False, readonly=True, version=PLANNER_VERSION, error=str(exc),
            required_units=copy.deepcopy((ctx.get('planner_orders') or {}).get('required_units', [])))


def submitted_planner(observer, ctx, *, start=0):
    runs = observer.runs[start:]
    if not runs or runs[-1].get('finish_reason') != 'completed':
        return None
    accepted = None
    current = SimpleNamespace(runs=[runs[-1]])
    for args, reply, event in extensions.public_tool_results(current, PLANNER_TOOL):
        args = validate_planner(ctx, args)
        proof = _planner_proof(ctx, args)
        if (any(reply.get(k) != v for k, v in proof.items())
                or reply.get('order_count') != len(args['orders'])):
            raise ValueError('批量候选的操作、名单、版本或完整参数指纹不一致')
        accepted = args, dict(source='dsh_native_planner_order_tool', **proof, **event)
    return accepted


PLANNER_INSTRUCTION = (
    '本次启用submit_planner_orders({orders:[...]})原生工具，提交required_units中的全部且仅这些单位，'
    '一单位一项命令；人工、已准备任务和单位Agent接管的单位不在本批名单内，不得重复规划。'
    '每项含unit_id、action、简短rationale和expected_effect，其他字段按动作需要提供；'
    'duration仅next或移动until_arrived。不生成权威状态。'
    '该工具直接校验完整名单与资源，无evaluate_action的16项分页上限；失败按工具返回的精确名单修正。'
    '工具校验成功后最终简短确认即可，不再重抄长JSON或改写已提交候选。'
    '工具成功只表示候选通过，实际执行和整轮提交仍由宿主完成。'
    '只有该工具不可用时，才兼容返回相同orders结构的完整JSON。\n')
