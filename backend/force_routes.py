"""Task organization API reusing command permissions, revisions and checkpoints."""
from fastapi import APIRouter, HTTPException
from pydantic import Field

from gentactix import commands, force_organization as forces, force_tasks
from . import session_store
from .command_routes import Revision, _check, _persist


class OrganizationRequest(Revision):
    organization_revision: int = Field(ge=0)


class DetachRequest(OrganizationRequest):
    unit_ids: list[str] = Field(min_length=1,max_length=1000)
    label: str = Field(min_length=1,max_length=80)
    assumption: str = Field(min_length=1,max_length=2000)
    parent_id: str | None = Field(default=None,max_length=256)


class MergeRequest(OrganizationRequest):
    group_ids: list[str] = Field(min_length=2,max_length=1000)
    label: str = Field(min_length=1,max_length=80)
    assumption: str = Field(min_length=1,max_length=2000)


class GroupOrderRequest(OrganizationRequest):
    group_id: str = Field(min_length=1,max_length=256)
    order: dict


class ReparentRequest(OrganizationRequest):
    group_id: str = Field(min_length=1,max_length=256)
    parent_id: str | None = Field(default=None,max_length=256)
    assumption: str = Field(min_length=1,max_length=2000)


class TaskRequest(OrganizationRequest):
    group_id: str = Field(min_length=1,max_length=256)
    task: dict
    replace_existing: bool = False
    preview_hash: str | None = Field(default=None,max_length=64)
    execution: dict | None = None


class CancelTaskRequest(OrganizationRequest):
    task_id: str = Field(min_length=1,max_length=80)


class ConversionPreviewRequest(Revision):
    kind: str
    unit_ids: list[str] = Field(min_length=1,max_length=32)
    allocations: list[dict] | None = Field(default=None,min_length=2,max_length=32)
    assumption: str = Field(min_length=1,max_length=2000)
    organization_revision: int | None = Field(default=None,ge=0)
    offset: int = Field(default=0,ge=0)
    limit: int = Field(default=8,ge=1,le=8)
    view_version: str | None = None


class ConversionCommitRequest(Revision):
    kind: str
    unit_ids: list[str] = Field(min_length=1,max_length=32)
    allocations: list[dict] | None = Field(default=None,min_length=2,max_length=32)
    assumption: str = Field(min_length=1,max_length=2000)
    organization_revision: int = Field(ge=0)
    view_version: str = Field(min_length=64,max_length=64)
    commit_id: str = Field(pattern='^[a-f0-9]{32}$')


def view(session):
    cs=commands.view(session)
    return {**forces.view(session),'command_revision':cs['revision'],'world_version':cs['world_version'],
        'turn':cs['turn'],'controllable_ids':[u['id'] for u in cs['units'] if u['controllable']],
        'targets':[{k:u[k] for k in ('id','name','team','available')} for u in cs['units'] if u.get('present',True)]}


def _guard(session,request,ids):
    _check(session,request)
    if forces.state(session)['revision']!=request.organization_revision:
        raise HTTPException(409,'任务编组已变化，请刷新后重试')
    commands.assert_writable(session)
    controllable={u['id'] for u in commands.view(session)['units'] if u['controllable']}
    if not ids or not set(ids)<=controllable:raise ValueError('只能调整当前有指挥权限的在场单位')


def _save(session,value):
    candidate=session_store.serializable(session)
    candidate['force_organization']=value
    session_store.validate(candidate)
    session_store.save(candidate)
    session['force_organization']=value


def build_router(get_session,serialized):
    router=APIRouter()

    @router.post('/api/sessions/{sid}/force-organization/conversion-preview')
    def conversion_preview(sid:str,request:ConversionPreviewRequest):
        session=get_session(sid);_check(session,request)
        if request.organization_revision is not None and request.organization_revision!=forces.state(session)['revision']:
            raise HTTPException(409,'组织修订已变化，请重新预览')
        from gentactix import formation_conversion
        args=request.model_dump(exclude_none=True,exclude={'expected_turn','revision','world_version','organization_revision'})
        try:return formation_conversion.observation(session,args)
        except (ValueError,KeyError,TypeError) as exc:raise HTTPException(422,str(exc)) from exc

    @router.post('/api/sessions/{sid}/force-organization/conversion-commit')
    @serialized(checkpoint=False)
    def conversion_commit(sid:str,request:ConversionCommitRequest):
        from . import formation_commit
        session=get_session(sid)
        try:
            result=formation_commit.commit(session,request.model_dump(exclude_none=True))
            return {**view(session),'conversion_result':result}
        except commands.Conflict as exc:raise HTTPException(409,str(exc)) from exc
        except (ValueError,KeyError,TypeError) as exc:raise HTTPException(422,str(exc)) from exc
        except OSError as exc:raise HTTPException(503,'编组检查点保存失败，原状态和命令保留') from exc

    @router.get('/api/sessions/{sid}/campaign-lifecycle')
    def lifecycle(sid:str,offset:int=0,limit:int=8,view_version:str|None=None):
        from gentactix import campaign_lifecycle
        session=get_session(sid)
        if not session.get('war_state'):raise HTTPException(409,'请先初始化战局')
        try:return campaign_lifecycle.observation(session['war_state'],offset=offset,limit=limit,view_version=view_version)
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc

    @router.get('/api/sessions/{sid}/campaign-objectives')
    def objectives(sid:str,kind:str='nodes',node_id:str|None=None,offset:int=0,limit:int=8,view_version:str|None=None):
        from gentactix import campaign_plan
        session=get_session(sid)
        if not session.get('war_state'):raise HTTPException(409,'请先初始化战局')
        try:return campaign_plan.observation(session['war_state'],kind=kind,node_id=node_id,offset=offset,limit=limit,view_version=view_version)
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc

    @router.get('/api/sessions/{sid}/force-organization')
    def get(sid:str):
        session=get_session(sid)
        if not session.get('war_state'):raise HTTPException(409,'请先初始化战局')
        return view(session)

    @router.get('/api/sessions/{sid}/force-organization/tasks')
    def tasks(sid:str,kind:str='tasks',task_id:str|None=None,offset:int=0,limit:int=8,view_version:str|None=None):
        from gentactix import force_task_execution
        session=get_session(sid)
        if not session.get('war_state'):raise HTTPException(409,'请先初始化战局')
        args=dict(kind=kind,offset=offset,limit=limit)
        if task_id:args['task_id']=task_id
        if view_version:args['view_version']=view_version
        try:return force_task_execution.observation(session,args)
        except commands.Conflict as exc:raise HTTPException(409,str(exc)) from exc
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc

    def execute(sid,request,operation):
        session=get_session(sid)
        try:
            if isinstance(request,DetachRequest):ids=request.unit_ids
            elif isinstance(request,ReparentRequest):
                ids=forces.member_ids(session,request.group_id)
                if request.parent_id:ids+=forces.member_ids(session,request.parent_id)
            elif isinstance(request,GroupOrderRequest):ids=forces.effective_member_ids(session,request.group_id)
            else:ids=[i for g in request.group_ids for i in forces.member_ids(session,g)]
            _guard(session,request,ids)
            operation(session)
            return view(session)
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc
        except OSError as exc:raise HTTPException(503,'编组检查点写入失败，原状态保留') from exc

    @router.post('/api/sessions/{sid}/force-organization/detach')
    @serialized
    def detach(sid:str,request:DetachRequest):
        return execute(sid,request,lambda s:_save(s,forces.detach(s,request.unit_ids,request.label,request.assumption,parent_id=request.parent_id)))

    @router.post('/api/sessions/{sid}/force-organization/merge')
    @serialized
    def merge(sid:str,request:MergeRequest):
        return execute(sid,request,lambda s:_save(s,forces.merge(s,request.group_ids,request.label,request.assumption)))

    @router.post('/api/sessions/{sid}/force-organization/wrap')
    @serialized
    def wrap(sid:str,request:MergeRequest):
        return execute(sid,request,lambda s:_save(s,forces.wrap(s,request.group_ids,request.label,request.assumption)))

    @router.post('/api/sessions/{sid}/force-organization/reparent')
    @serialized
    def reparent(sid:str,request:ReparentRequest):
        return execute(sid,request,lambda s:_save(s,forces.reparent(s,request.group_id,request.parent_id,request.assumption)))

    @router.post('/api/sessions/{sid}/force-organization/orders')
    @serialized
    def order(sid:str,request:GroupOrderRequest):
        def persist_order(session):
            members=set(forces.effective_member_ids(session,request.group_id))
            if any(o['unit_id'] in members for o in commands.state(session)['orders']):
                raise HTTPException(409,'范围内已有人工命令，请先预览兵团任务并明确保留或覆盖；旧命令未改变')
            _persist(session,forces.queue(session,request.group_id,request.order))
        return execute(sid,request,persist_order)

    def task_operation(sid,request,commit):
        session=get_session(sid)
        try:
            _guard(session,request,forces.effective_member_ids(session,request.group_id))
            if not commit:return force_tasks.preview(session,request.group_id,request.task,replace_existing=request.replace_existing,execution=request.execution)
            if not request.preview_hash:raise ValueError('请先预览并确认本次兵团任务')
            cs=force_tasks.commit(session,request.group_id,request.task,request.preview_hash,replace_existing=request.replace_existing,execution=request.execution)
            _persist(session,cs)
            return view(session)
        except commands.Conflict as exc:raise HTTPException(409,str(exc)) from exc
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc
        except OSError as exc:raise HTTPException(503,'任务检查点保存失败，原队列保留') from exc

    @router.post('/api/sessions/{sid}/force-organization/task-preview')
    def task_preview(sid:str,request:TaskRequest):return task_operation(sid,request,False)

    @router.post('/api/sessions/{sid}/force-organization/tasks')
    @serialized
    def task_commit(sid:str,request:TaskRequest):return task_operation(sid,request,True)

    @router.post('/api/sessions/{sid}/force-organization/cancel-task')
    @serialized
    def task_cancel(sid:str,request:CancelTaskRequest):
        from gentactix import force_task_execution
        session=get_session(sid);_check(session,request)
        if forces.state(session)['revision']!=request.organization_revision:raise HTTPException(409,'编组已变化，请刷新')
        try:
            _persist(session,force_task_execution.cancel(session,request.task_id))
            return view(session)
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc
        except OSError as exc:raise HTTPException(503,'撤销任务保存失败，原任务保留') from exc

    return router
