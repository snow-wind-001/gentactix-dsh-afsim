"""One conversion transaction using the existing operation lock/checkpoint store."""
import copy
import re

from gentactix import commands,force_organization,formation_conversion,formation_runtime,formation_session,missions,sim_clock
from . import session_store


def compile_candidate(candidate):
    """Validate current codecs only; no WSF job or model decision is executed."""
    with formation_session.command_validation(candidate):
        commands.prepare(candidate)
        if candidate.get('execution_backend')=='afsim':
            from . import afsim_world
            orders=[dict(unit=u['name'],action='hold') for _,u in commands.iter_units(candidate['war_state']) if commands.available(u)]
            afsim_world.compile_scene(candidate['war_state'],orders,sim_clock.duration_seconds(candidate['time_step']),native_rules=True)


def commit(session,request):
    with missions.validation_scope(session.get('war_state')):
        return _commit(session,request)


def _receipt(session,identity,row,*,replayed):
    cs=session['command_state'];mapping=cs['formation_handoffs'][row['registry_revision']-1]['command_map']
    current=set(commands.resolve_units(session,cs))
    effective={old:list(dict.fromkeys(i for target in targets for i in formation_session.remap(cs,target) if i in current))
        for old,targets in mapping.items()}
    return dict(replayed=replayed,runtime_admitted=True,physics_executed=False,
        registry_revision=row['registry_revision'],commit_id=identity,view_version=row['view_version'],
        command_map=copy.deepcopy(mapping),current_command_map=effective)


def _commit(session,request):
    # HTTP callers hold the existing _OP_LOCK. Recheck everything from current
    # state; neither a client-supplied world nor a cached candidate is accepted.
    if not isinstance(request,dict) or set(request)-{'kind','unit_ids','allocations','assumption','expected_turn',
            'revision','world_version','organization_revision','view_version','commit_id'}:
        raise ValueError('编组提交字段非法')
    identity=request.get('commit_id')
    if not isinstance(identity,str) or not re.fullmatch('[a-f0-9]{32}',identity):raise ValueError('编组提交需要32位十六进制幂等ID')
    request_hash=commands.fingerprint(request);prior=(session.get('formation_commits') or {}).get(identity)
    if prior:
        session_store.validate(session)
        if prior['request_hash']!=request_hash:raise ValueError('提交ID已用于其他编组输入')
        return _receipt(session,identity,prior,replayed=True)
    commands.check_revision(session,request.get('expected_turn'),request.get('revision'),request.get('world_version'))
    commands.assert_writable(session)
    if request.get('organization_revision')!=force_organization.state(session)['revision']:
        raise commands.Conflict('组织修订已变化，请重新预览')
    if not isinstance(request.get('view_version'),str):raise ValueError('请先预览本次编组并提交view_version')
    session_store.validate(session)
    args={k:copy.deepcopy(request[k]) for k in ('kind','unit_ids','allocations','assumption','view_version') if k in request}
    ids=request.get('unit_ids');controllable={u['id'] for u in commands.view(session)['units'] if u['controllable']}
    if not isinstance(ids,list) or not ids or not set(ids)<=controllable:raise ValueError('只能提交具有当前指挥权限的在场单位')
    value=formation_conversion.preparation(session,args);candidate=value['prepared']['session']
    compile_candidate(candidate)
    revision=len(candidate['war_state']['formation_registry']['transactions'])
    candidate.setdefault('formation_commits',{})[identity]=dict(version=formation_runtime.VERSION,request=copy.deepcopy(request),
        request_hash=request_hash,registry_revision=revision,proposal_hash=value['proposal']['proposal_hash'],view_version=value['view_version'])
    formation_runtime.seal(candidate);session_store.validate(candidate)
    receipt=_receipt(candidate,identity,candidate['formation_commits'][identity],replayed=False)
    session_store.save(candidate)
    session.update(candidate)
    return receipt
