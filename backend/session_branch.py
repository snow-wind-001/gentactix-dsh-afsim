"""Detached open branch, retaining domain lineage and allocating no SDK session."""
import copy

from gentactix import commands, force_organization
from . import session_store


def prepare(source,identity):
    if source['war_state'].get('formation_registry'):session_store.validate(source)
    namespace,epoch=commands.identity_namespace(source)
    branch=session_store.serializable(source)
    cs=commands.state(source)
    origin=dict(version=commands.IDENTITY_VERSION,session_id=namespace,role_epoch=epoch)
    branch.update(id=identity,simulation_mode='open',role_epoch=source.get('role_epoch',0)+1,
        command_identity_origin=origin,command_state=cs,
        counterfactuals=[],causal_analysis=None,failed_operations=[],engine_last_meta=None,
        chat_messages=[],review_text=None,review_reasoning=None,review_audit=None,
        cancel_requested=False,progress=None,active_observer=None)
    branch['branch_origin']=dict(session_id=source['id'],turn=source['turn_count'],
        world_version=commands.world_version(source),basis='开放假设分支；继承既有实态与公开轨迹，不冒充史实回放',
        identity_policy=commands.BRANCH_POLICY,command_identity_origin=copy.deepcopy(origin),
        source_role_epoch=source.get('role_epoch',0),source_command_revision=cs['revision'],
        source_organization_revision=force_organization.state(source)['revision'],
        conversion_revision=len((source['war_state'].get('formation_registry') or {}).get('transactions',[])),
        native_memory='fresh_sessions_required; source_sessions_remain_in_source',
        inherited_batches=copy.deepcopy(cs['batches']),
        inherited_trajectory_count=len(source.get('trajectory',[])))
    # These are historical references only. Never resume or dispose a source
    # unit's Native session from the child; the original battle still owns it.
    for unit,binding in cs.get('agent_sessions',{}).items():
        cs.setdefault('agent_resets',[]).append(dict(unit_id=unit,turn=source['turn_count'],
            previous_session_id=binding['session_id'],reason='开放分支新建运行会话；来源绑定与历史保留在原局'))
    cs['agent_sessions']={};cs['batches']={};cs['revision']+=1
    branch.pop('command_proposals',None)
    session_store.validate(branch)
    return branch
