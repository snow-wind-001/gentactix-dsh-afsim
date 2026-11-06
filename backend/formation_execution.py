"""Isolated registered-world execution through the existing engine pipelines.

This has no HTTP commit, persistence service or model transport. It certifies
current-state codecs while public registered-world admission remains closed.
"""
import copy

from gentactix import commands,formation_session,missions,sim_clock
from . import afsim_turns,afsim_world,dsh_simulation


def validator(session):
    formation_session.validate(session)
    before=session['war_state'];definition=before['mission']['definition_hash']
    ledger=copy.deepcopy(before.get('formation_registry'));turn=before['mission']['turn']
    elapsed=before['simulation_clock']['elapsed_seconds'];seconds=sim_clock.duration_seconds(session['time_step'])
    def check(world):
        if world['mission']['definition_hash']!=definition or world.get('formation_registry')!=ledger:
            raise ValueError('隔离执行不能替换定义、根账或转换记录')
        if (world['mission']['turn'],world['simulation_clock']['elapsed_seconds']) not in ((turn,elapsed),(turn+1,elapsed+seconds)):
            raise ValueError('隔离执行只能验证同一前态或下一完整回合')
        return missions.validate(world,allow_prepared=True)
    return check


def scene(session,orders):
    check=validator(session);check(session['war_state'])
    # Compilation only: the scope ends before any external process starts.
    with formation_session.command_validation(session):
        return afsim_world.compile_scene(session['war_state'],orders,sim_clock.duration_seconds(session['time_step']),native_rules=True)


def trial(session,drafts,observer,*,backend,cancel_check=None,instruction=''):
    """Return a detached executed frame; never write/adopt the session."""
    from .session_store import serializable
    if backend not in ('afsim','narrative'):raise ValueError('隔离执行后端须为afsim或narrative')
    work=serializable(session);work['execution_backend']=backend;check=validator(work);cs=commands.state(work)
    expected={i for i,(_,u) in commands.resolve_units(work).items() if commands.available(u)}
    if {r['unit_id'] for r in drafts}!=expected:raise ValueError('隔离试算须明确覆盖双方全部可行动单位')
    with formation_session.command_validation(work):
        work['command_state']=commands.replace_queue(work,drafts,control_team=cs['control_team'],director=cs['director'],
            no_fire=cs['no_fire'],intent=cs['intent'])
    prepared=formation_session.command_probe(work)
    if prepared['blocked'] or prepared['expired']:raise ValueError('隔离试算含受阻或过期命令，未执行')
    orders=[r['order'] for r in prepared['manual']]
    check=validator(work)
    if backend=='afsim':
        compiled=scene(work,orders)
        result,executed,prompt=afsim_turns.execute_scene(work,orders,observer,cancel_check=cancel_check,
            scene=compiled,world_validator=check)
    elif backend=='narrative':
        result,executed,prompt=dsh_simulation.advance(work,None,observer,instruction=instruction,
            cancel_check=cancel_check,fixed_orders=orders,world_validator=check)
    else:raise ValueError('隔离执行后端须为afsim或narrative')
    after=result['updated_state'];check(after)
    cs,decisions=commands.finish(work,prepared,after,executed=executed,rationales=result.get('decisions',[]))
    work.update(war_state=after,command_state=cs,turn_count=after['mission']['turn'])
    formation_session.validate(work)
    return dict(session=work,result=result,orders=executed,decisions=decisions,prompt=prompt,runtime_admitted=False,
        scope='隔离后端真实执行帧；未提交原会话或存档')
