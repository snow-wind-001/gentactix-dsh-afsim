"""Durable admission contracts for audited conversion sessions, not physics."""
import re
from . import missions

VERSION='formation-runtime-1'
FIELD='formation_runtime'


def physical_digest(world):
    # Admission metadata is checked separately. It must not invalidate the
    # existing zero-time physical proof or create a registry/hash cycle.
    return missions.digest({k:v for k,v in world.items() if k!=FIELD})


def validate_world(world):
    ledger=world.get('formation_registry');value=world.get(FIELD)
    if (not isinstance(value,dict) or set(value)!={'version','registry_hash','definition_hash','handoff_hash','commit_count'}
            or value.get('version')!=VERSION or not isinstance(ledger,dict)
            or type(value.get('commit_count')) is not int or value['commit_count']<1
            or any(not isinstance(value.get(k),str) or not re.fullmatch('[a-f0-9]{64}',value[k])
                for k in ('registry_hash','definition_hash','handoff_hash'))
            or value['commit_count']!=len(ledger.get('transactions',[]))
            or value['registry_hash']!=missions.digest(ledger)
            or value['definition_hash']!=world.get('mission',{}).get('definition_hash')):
        raise ValueError('运行中编组候选尚未完成正式提交事务，或准入回执与归属账不一致')
    return True


def seal(session):
    world=session['war_state'];ledger=world['formation_registry']
    world[FIELD]=dict(version=VERSION,registry_hash=missions.digest(ledger),
        definition_hash=world['mission']['definition_hash'],
        handoff_hash=missions.digest(session['command_state']['formation_handoffs']),
        commit_count=len(ledger['transactions']))


def validate_session(session):
    from . import commands
    world=session.get('war_state') or {};ledger=world.get('formation_registry')
    commits=session.get('formation_commits')
    if not ledger:
        if world.get(FIELD) is not None or commits:raise ValueError('编组提交回执缺少当前归属账')
        return
    # session_store performs the full world, command and organization checks
    # separately. Do not rerun them here and again later in the same restore.
    validate_world(world)
    if (session.get('turn_count')!=world['mission']['turn']
            or session.get('time_step')!=world['mission']['definition']['time_step']):
        raise ValueError('编组会话回合或步长与当前世界不一致')
    handoffs=session['command_state'].get('formation_handoffs',[])
    if world[FIELD]['handoff_hash']!=missions.digest(handoffs):raise ValueError('编组准入与命令交接记录不一致')
    if not isinstance(commits,dict) or len(commits)!=len(handoffs):raise ValueError('编组正式提交记录缺失或重复')
    seen=set()
    for identity,row in commits.items():
        if (not isinstance(identity,str) or not re.fullmatch('[a-f0-9]{32}',identity)
                or not isinstance(row,dict) or set(row)!={'version','request','request_hash','registry_revision','proposal_hash','view_version'}
                or row['version']!=VERSION or type(row['registry_revision']) is not int
                or not 1<=row['registry_revision']<=len(handoffs) or row['registry_revision'] in seen):
            raise ValueError('编组提交记录版本或修订非法')
        revision=row['registry_revision'];seen.add(revision)
        event=ledger['transactions'][revision-1];handoff=handoffs[revision-1];request=row['request']
        if (not isinstance(request,dict) or request.get('commit_id')!=identity
                or row['request_hash']!=commands.fingerprint(request)
                or request.get('expected_turn')!=event['turn'] or request.get('kind')!=event['proposal']['kind']
                or request.get('revision')!=handoff['before_command_state']['revision']
                or request.get('organization_revision')!=handoff['before_organization']['revision']
                or set(request.get('unit_ids',[]))!=set(handoff['command_map'])
                or row['proposal_hash']!=event['proposal']['proposal_hash']):
            raise ValueError('编组提交记录与归属或命令交接不一致')
        args={k:request[k] for k in ('kind','unit_ids','allocations','assumption') if k in request}
        proposal_request=event['proposal']['request']
        if (request.get('assumption')!=proposal_request['assumption']
                or request['kind']=='split' and request.get('allocations')!=proposal_request['allocations']
                or request['kind']=='merge' and 'allocations' in request):
            raise ValueError('编组提交的分配输入与实际提案不一致')
        op=missions.digest([request.get('world_version'),request['revision'],request['organization_revision'],args])[:32]
        token=missions.digest([request.get('world_version'),request['revision'],request['organization_revision'],row['proposal_hash']])
        if (token!=row['view_version'] or token!=request.get('view_version')
                or op!=event['proposal']['request']['operation_id']):
            raise ValueError('编组正式提交未绑定原预览或操作')
