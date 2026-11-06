"""Preview and atomically open a continuation from a completed historical phase."""
import copy
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from gentactix import missions, phase_continuity, reporting, historical_operations, force_organization, commands
from . import scenario_builder, session_store, afsim_world, harness_engine


class ContinuationRequest(BaseModel):
    draft_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    world_version: str
    organization_revision: int | None = Field(default=None,ge=0)
    command_revision: int | None = Field(default=None,ge=0)


class ObjectiveBranchRequest(BaseModel):
    world_version: str


def _candidate(session, request):
    source = session.get('war_state')
    if session.get('product_mode') != 'historical' or not source:
        raise ValueError('阶段续接仅适用于历史战局推演')
    if missions.digest(source) != request.world_version:
        raise ValueError('前态已变化，请刷新后重新预览')
    if request.organization_revision is not None and request.organization_revision!=force_organization.state(session)['revision']:
        raise ValueError('编组修订已变化，请重新预览阶段续接')
    if request.command_revision is not None and request.command_revision!=commands.state(session)['revision']:
        raise ValueError('命令修订已变化，请重新预览阶段续接')
    draft = scenario_builder.load(request.draft_id)
    if (draft.get('kind') != 'historical_operation' or draft.get('execution_backend') != session.get('execution_backend')
            or draft.get('construction', {}).get('source') != 'dsh_native_skill'):
        raise ValueError('请选择相同执行后端的已验证历史配置')
    target = {'format': 'historical-operation-1', 'initial': draft['initial'], 'parameters': draft['parameters']}
    if missions.digest(historical_operations.from_binding(target)) != draft['definition_hash']:
        raise ValueError('目标配置已过期，请重新验证')
    return missions.from_definition(phase_continuity.definition(phase_continuity.bind(source, target)))


def build_router(get_session, serialized):
    router = APIRouter()

    @router.post('/api/sessions/{sid}/objective-branch')
    @serialized
    def objective_branch(sid: str, request: ObjectiveBranchRequest):
        source=get_session(sid);current=source.get('war_state') or {}
        spec=current.get('mission',{}).get('definition',{})
        if missions.digest(current)!=request.world_version:
            raise HTTPException(422,'前态已变化，请刷新战局后再创建分支')
        if (source.get('product_mode')!='historical' or source.get('simulation_mode')=='replay'
                or not str(spec.get('id','')).startswith('HO-') or current.get('history_replay')):
            raise HTTPException(422,'此入口只适用于具名历史初态的开放战局；回溯或阶段续接请使用各自入口')
        if spec.get('termination_mode')=='objectives':
            raise HTTPException(422,'当前战局已经按目标完成，不需要切换')
        mission=current['mission']
        if mission.get('status')=='completed' and mission.get('reason')!='截止回合目标未达成':
            raise HTTPException(422,'目标已经达成或目标方已无可用人员，不能通过取消时限改写结果')
        try:
            binding=copy.deepcopy(spec['historical_calculation'])
            binding['parameters']['goal']['termination_mode']='objectives'
            target=historical_operations.from_binding(binding)
            world=copy.deepcopy(current)
            initial=missions.from_definition(target)
            world['mission'].update(id=target['id'],definition=target,definition_hash=missions.digest(target),
                initial_hash=initial['mission']['initial_hash'],status='active',winner=None,reason='')
            missions.validate(world)
            engine=source.get('execution_backend','narrative')
            scene=afsim_world.compile_scene(world,[],.001,native_rules=True)
            evidence=scenario_builder._load_world(world,scene,engine,None)
            if evidence:world['afsim']=evidence
            child=session_store.serializable(source)
            child.update(id=uuid.uuid4().hex[:12],war_state=world,last_war_state=None,
                historical_definition=target,mission_id=target['id'],trajectory=[],decision_log=[],
                counterfactuals=[],causal_analysis=None,failed_operations=[],engine_last_meta={},
                role_epoch=source.get('role_epoch',0)+1,cancel_requested=False,progress=None,active_observer=None)
            child.pop('command_state',None);child.pop('command_proposals',None)
            child['branch_origin']={'session_id':sid,'turn':source['turn_count'],'world_version':request.world_version,
                'source_definition_hash':missions.digest(spec),'basis':'目标完成分支；保留当前人员装备库存和模拟时间，原限时战局不变'}
            child['history']=[f'【目标完成制分支 | {world["current_time"]}】\n\n'
                f'从原战局T+{source["turn_count"]}的实际态势继续。原限时战局及其结算结果保留在来源存档。'
                '本分支不按史料日期或参考轮数自动结束，按当前程序目标和连续达标要求结算。'
                '人员、装备、库存与模拟时间未重置；原命令队列已清空，请重新下令。尚未执行新的推演回合。',
                *child.get('history',[])]
            session_store.validate(child);session_store.save(child)
            from .main import _SESSIONS,_snapshot
            _SESSIONS[child['id']]=child
            return _snapshot(get_session(child['id']))
        except (ValueError,KeyError,TypeError) as exc:
            raise HTTPException(422,str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(502,'目标制分支装载失败，原战局保留：'+str(exc)) from exc

    @router.get('/api/sessions/{sid}/phase-continuation')
    def candidates(sid: str):
        session = get_session(sid)
        binding = (session.get('war_state') or {}).get('mission', {}).get('definition', {}).get('historical_calculation')
        rows = []
        if binding:
            for path in scenario_builder.directory().glob('*.json'):
                try:
                    draft = scenario_builder.load(path.stem)
                    initial = draft.get('initial') or {}
                    if (draft.get('kind') == 'historical_operation' and initial.get('profile_id') == binding['initial']['profile_id']
                            and initial.get('definition_hash') == binding['initial']['definition_hash']
                            and draft.get('execution_backend') == session.get('execution_backend')):
                        rows.append({'id': draft['id'], 'phase_id': initial['phase_id'],
                                     'label': next(p['label'] for p in initial['definition']['phases'] if p['id'] == initial['phase_id']),
                                     'start': draft['parameters']['clock']['start'], 'saved_at': path.stat().st_mtime})
                except (ValueError, KeyError, OSError, TypeError):
                    continue
        return {'world_version': missions.digest(session.get('war_state')),
                'items': sorted(rows, key=lambda r: r['saved_at'], reverse=True)[:30]}

    @router.post('/api/sessions/{sid}/phase-continuation/preview')
    def preview(sid: str, request: ContinuationRequest):
        try:
            world = _candidate(get_session(sid), request)
            source=get_session(sid)
            carried=force_organization.continue_session(source,dict(id=sid+'-preview',war_state=world,
                time_step=world['mission']['definition']['time_step'],turn_count=0,
                product_mode='historical',simulation_mode='open',execution_backend=source.get('execution_backend','narrative')))
            return {'handoff': world['phase_handoff'], 'definition_hash': world['mission']['definition_hash'],
                    'start': world['current_time'], 'units': sum(1 for _ in missions.units(world)),
                    'command_handoff':carried['command_handoff'],
                    'organization_revision':force_organization.state(source)['revision'],
                    'command_revision':commands.state(source)['revision']}
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post('/api/sessions/{sid}/phase-continuation')
    @serialized
    def continue_phase(sid: str, request: ContinuationRequest):
        source = get_session(sid)
        observer = harness_engine.RunObserver('阶段续接')
        source.update(progress=observer.progress, active_observer=observer)
        try:
            world = _candidate(source, request)
            engine = source.get('execution_backend', 'narrative')
            scene = afsim_world.compile_scene(world, [], .001, native_rules=True)
            evidence = scenario_builder._load_world(world, scene, engine, lambda: bool(source.get('cancel_requested')))
            if evidence:
                world['afsim'] = evidence
            from .main import _new_session, _SESSIONS, _snapshot
            session = _new_session(source['scenario_input'], world['mission']['definition']['time_step'],
                source['use_adjudicator'], source['battle_choice'], source['use_rag'], source['use_live_intel'],
                source.get('use_agent_tools', False), source.get('persist_roles'), source.get('agent_mode', 'json'))
            session.update(execution_backend=engine, product_mode='historical', simulation_mode='open',
                historical_definition=copy.deepcopy(world['mission']['definition']), mission_id=world['mission']['id'],
                war_state=world, turn_count=0,
                branch_origin={'session_id': sid, 'turn': source['turn_count'], 'world_version': request.world_version,
                               'basis': phase_continuity.VERSION},
                history=[reporting.initial_status(world)])
            session.update(force_organization.continue_session(source,session))
            session_store.validate(session)
            session_store.save(session)
            _SESSIONS[session['id']] = session
            return _snapshot(get_session(session['id']))
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(502, '续接原生装载失败，原战局保留：' + str(exc)) from exc
        except OSError as exc:
            raise HTTPException(503, '阶段检查点保存失败，原战局保留：'+str(exc)) from exc
        finally:
            source.update(progress=None, active_observer=None, cancel_requested=False)

    return router
