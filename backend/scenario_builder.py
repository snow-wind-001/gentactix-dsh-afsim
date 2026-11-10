"""DSH skill-driven scenario drafts over historical references and closed templates."""
import copy
from datetime import datetime
import json
import os
from pathlib import Path
from typing import Literal
import re
import threading
import uuid
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from gentactix import combined_arms, missions, scenario_basis, historical_initial, historical_operations, anchors, combat_effects, sim_clock, resource_readiness, scenario_constraints, campaign_windows
from . import harness_engine as h, afsim_world, extensions

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / 'plugins/dsh-afsim/skills/historical-scenario/SKILL.md'
HISTORICAL_SKILL = ROOT / 'plugins/dsh-afsim/skills/historical-units/SKILL.md'
_active = {}
_active_lock = threading.RLock()
HistoricalRequiredModel = Literal['formation-ferry-1','time-sustainment-1','personnel-rations-1',
    'scheduled-supply-1','movement-feedback-1','classified-indirect-1','live-footprint-density-1','live-footprint-density-2']


def directory():
    from . import session_store
    return session_store.directory().parent / 'scenario-drafts'


def load(identity):
    if not isinstance(identity,str) or not re.fullmatch(r'[a-f0-9]{32}',identity):
        raise ValueError('想定草稿ID非法')
    try:
        return json.loads((directory()/(identity+'.json')).read_text())
    except (OSError,ValueError) as exc:
        raise ValueError('想定草稿不存在或已不可读，请重新装载验证') from exc


def pending_configurations(snapshot, *, force_scope=None, window=None):
    result=[]
    for path in directory().glob('*.json'):
        try:
            record=load(path.stem)
            if (record.get('kind')!='historical_configuration' or record.get('loaded_draft_id')
                    or record.get('initial')!=snapshot):continue
            scope=record['parameters'].get('campaign_scope') or {}
            if force_scope is not None and (bool(scope)!=(force_scope=='campaign') or not campaign_windows.equivalent_pins(scope.get('window'),window)):continue
            result.append({'id':record['id'],'execution_backend':record['execution_backend'],
                'time_step':record['parameters']['clock']['time_step'],'termination_mode':record['parameters']['goal'].get('termination_mode','deadline'),'saved_at':path.stat().st_mtime})
        except (ValueError,KeyError,OSError,TypeError):continue
    return sorted(result,key=lambda r:r['saved_at'],reverse=True)[:20]


def completed_configurations(snapshot,*,force_scope=None,window=None):
    result=[]
    for path in directory().glob('*.json'):
        try:
            record=load(path.stem)
            if record.get('kind')!='historical_operation' or record.get('initial')!=snapshot:continue
            scope=record['parameters'].get('campaign_scope') or {}
            if force_scope is not None and (bool(scope)!=(force_scope=='campaign') or not campaign_windows.equivalent_pins(scope.get('window'),window)):continue
            result.append({'id':record['id'],'execution_backend':record['execution_backend'],
                'time_step':record['parameters']['clock']['time_step'],
                'termination_mode':record['parameters']['goal'].get('termination_mode','deadline'),
                'required_models':record['construction'].get('required_models',[]),
                'actor_count':len(record['parameters']['actors']),'saved_at':path.stat().st_mtime})
        except (ValueError,KeyError,OSError,TypeError):continue
    return sorted(result,key=lambda row:row['saved_at'],reverse=True)[:20]


def validate_configuration(identity, config, *, historical_base=None, combat_reference=None):
    if not isinstance(config,dict) or not config.get('historical_basis'):
        raise ValueError('演习必须从当前史实基础派生，不能提交无来源的随机编制')
    if historical_base is not None:
        from gentactix import synthetic_history
        world=missions.from_definition(synthetic_history.definition(historical_base,config))
    else:
        world=missions.initial(identity,configuration=config)
    if combat_reference is not None:
        world['combat_reference']=combat_effects.configuration_reference(world,combat_reference)
    scene=afsim_world.compile_scene(world,[],.001,native_rules=True)
    return world,scene


def bind_model_configuration(identity,config, *, historical_base=None):
    """Provenance belongs to the operation, never to model-generated hashes."""
    if not isinstance(config,dict) or set(config)-{'version','teams','historical_basis','aviation','fire_accounting','fire_dynamics'} or 'teams' not in config:
        raise ValueError('模型配置只提交teams；不要混入地图说明或史料对象')
    if historical_base is not None:
        from gentactix import synthetic_history
        seed=synthetic_history.seed(historical_base)['configuration']
    else:
        seed=scenario_basis.exercise_seed(identity)['configuration']
    if seed.get('fire_accounting') and not config.get('fire_accounting'):
        raise ValueError('模型遗漏源配置已选择的分类炮弹计量；须保留fire_accounting，不能静默切换弹药含义')
    if 'fire_accounting' in config:combat_effects.validate_accounting(config['fire_accounting'])
    if seed.get('fire_dynamics') and not config.get('fire_dynamics'):
        raise ValueError('模型遗漏源配置已选择的动态密度火力过程；须保留fire_dynamics，不能静默回退')
    if 'fire_dynamics' in config:combat_effects.validate_dynamics(config['fire_dynamics'])
    for key in ('version','historical_basis'):
        if key in config and config[key]!=seed[key]:
            raise ValueError('只读来源字段不一致；模型无需提交version或historical_basis，宿主会从本次战役绑定')
    return {**copy.deepcopy(config),'version':seed['version'],'historical_basis':seed['historical_basis']}


def generate_exercise_candidate(identity, prompt, context, observer, *, historical_base=None, combat_reference=None):
    """Retry one rejected model candidate without staging or repairing its text."""
    required = {'read_scenario_skill', 'get_scenario_basis', 'validate_scenario_configuration'}
    for attempt in range(2):
        if observer.cancel_requested:
            raise RuntimeError('已取消想定生成；已有战局未改动')
        start = len(observer.runs)
        result = h._run_brain(prompt, None, role='scenario-builder', observer=observer, native_context=context,
                              cancel_check=lambda: observer.cancel_requested)
        try:
            if observer.cancel_requested:
                raise RuntimeError('已取消想定生成；已有战局未改动')
            answer = h.parse_json_object(result.final_response)
            if not isinstance(answer, dict) or set(answer) - {'configuration', 'explanation'} or 'configuration' not in answer:
                raise ValueError('想定生成只能返回configuration与explanation，且必须包含configuration')
            calls = {event.get('name') for run in observer.runs[start:] for event in run.get('events', [])
                     if event.get('type') == 'tool/call'}
            if not required <= calls:
                raise ValueError('缺少本次DSH实际skill/史料/配置校验调用证据，未接受直接生成结果')
            config = bind_model_configuration(identity, answer['configuration'], historical_base=historical_base)
            validate_configuration(identity, config, historical_base=historical_base, combat_reference=combat_reference)
            return answer, config
        except (ValueError, KeyError, TypeError) as exc:
            if len(observer.runs) > start:
                observer.runs[-1].update(accepted=False, rejection='invalid_scenario_candidate')
            if attempt or observer.cancel_requested:
                raise
            # The model must regenerate its candidate; never infer or patch a
            # broken response, and never include its full raw text in feedback.
            reason = exc.diagnostics['reason'] if isinstance(exc, h.JSONOutputError) else str(exc)[:500]
            observer.progress.update(phase='scenario_output_recovery', recovery_attempt=1)
            prompt += ('\n【配置未提交，重新生成】上次候选未通过校验：' + reason +
                '。请重新读取skill和史料基础，再调用配置校验工具；'
                'configuration只包含teams和种子已有规则字段，teams只包含red和blue数组；'
                '不要添加engine、seed_policy或validation_status等说明字段。'
                'explanation放在configuration之外；输出完整合法JSON。')
    raise AssertionError('unreachable')


def configuration_alternatives(battle,termination_mode=None):
    """Offer explicit supported scopes, never change a requested version or facts."""
    choices=[]
    for version in historical_initial.versions(battle):
        world=historical_initial.initial(battle,version=version['version'])
        snapshot=world['historical_initial']
        for scope in ('phase','campaign'):
            for phase in snapshot['definition']['phases']:
                candidate={**snapshot,'phase_id':phase['id']}
                try:template=historical_operations.configuration_template(candidate,scope,termination_mode=termination_mode)
                except ValueError:continue
                choices.append({'version':version['version'],'force_scope':scope,'phase_id':phase['id'],
                    'label':phase['label'],'actor_count':len(template['actors']),
                    'aviation_count':len(template.get('aviation',{})),
                    'scope':('累计参战编制；开局、分批到场和航空可用时段须显式估计，不代表同日实到或完整会战已验收'
                             if scope=='campaign' else '已登记局部阶段；缺载数值仍须显式估计，不代表完整战役')})
                break
    return choices


def historical_basis(battle, phase_id=None, *, time_step=None, version=None, termination_mode=None, force_scope='phase', campaign_window_id=None, campaign_window_version=None):
    row = next((r for r in historical_initial.catalog() if r['battle'] == battle), None)
    if row is None:
        raise ValueError('未知历史战役')
    from gentactix import campaign_windows
    selected_window=None
    if campaign_window_id:
        if force_scope!='campaign':raise ValueError('会战窗口只能在会战编制范围使用')
        selected_window=campaign_windows.pin(campaign_window_id,campaign_window_version or '1.0.0')
        w=selected_window['definition']
        if (w['battle']!=battle or (version is not None and version!=w['historical_initial']['version'])
                or (phase_id is not None and phase_id!=w['start_phase_id'])):
            raise ValueError('会战窗口与所选战役、史料版本或开局阶段不一致')
        version=w['historical_initial']['version'];phase_id=w['start_phase_id']
    elif campaign_window_version:
        raise ValueError('会战窗口版本须同时指定窗口身份')
    result = {'battle': battle, 'initial': None, 'phases': [], 'ready': False,
              'error': '', 'actors': [], 'configuration_template': None,'configuration_alternatives':[],
              'geo_references': [], 'versions': historical_initial.versions(battle),
              'scope': '具名历史单位的显式计算参数；不证明完整战役部署或真实效能',
              'available_campaign_windows':campaign_windows.catalog(battle),
              'campaign_window':selected_window}
    if time_step is not None:
        result['time_step_constraint'] = {'label': time_step, 'seconds': sim_clock.duration_seconds(time_step),
                                          'source': 'launch_selection'}
    if row['status'] == 'not_profiled':
        result['error'] = '本战役尚无历史单位初态档案；不能使用教学代表编组替代'
        return result
    world = historical_initial.initial(battle, phase_id, version=version)
    snapshot = world['historical_initial']
    # The fact factory defaults to a campaign reference so a retrospective's
    # opening event cannot acquire a later local phase's attendance. For an
    # unqualified configuration request, preselect an explicitly sourced,
    # supported phase and disclose that choice; an explicit phase is respected.
    if force_scope not in ('phase','campaign'):raise ValueError('未知编制范围')
    result['force_scope']=force_scope
    if force_scope=='campaign':result['scope']='会战累计参战编制；开局、分批投入和部署须明确估计，不是确证同日部署；现有史料下级与战场缺项不自动补齐'
    if selected_window:result['scope']=selected_window['definition']['limitations']
    if phase_id is None and force_scope=='phase':
        try:
            historical_operations.configuration_template(snapshot,termination_mode=termination_mode)
        except ValueError:
            for phase in snapshot['definition']['phases']:
                candidate = {**snapshot, 'phase_id': phase['id']}
                try:
                    historical_operations.configuration_template(candidate,termination_mode=termination_mode)
                except ValueError:
                    continue
                snapshot = historical_initial.restore(candidate)['historical_initial']
                result['scope'] += '；默认选择现有资料可配置的局部阶段：' + phase['label'] + '，不代表战役开端或全战役已完成建模'
                break
    result['initial'] = snapshot
    result['pending_configurations'] = pending_configurations(snapshot,force_scope=force_scope,window=selected_window)
    result['completed_configurations']=completed_configurations(snapshot,force_scope=force_scope,window=selected_window)
    from . import scenario_checkpoints
    result['pending_assemblies']=scenario_checkpoints.pending(snapshot,force_scope=force_scope,window=selected_window)
    selected_phase=next(p for p in snapshot['definition']['phases'] if p['id']==snapshot['phase_id'])
    result['interaction']=copy.deepcopy(selected_phase.get('interaction'))
    result['execution_window']=copy.deepcopy(selected_phase.get('execution_window'))
    if selected_window:
        result['execution_window']=copy.deepcopy(selected_window['definition']['bounds'])
    window=result['execution_window']
    if termination_mode not in (None,'objectives','deadline'):raise ValueError('结束方式非法')
    if time_step is not None and termination_mode!='objectives' and window and window.get('start'):
        duration=(datetime.fromisoformat(window['end'])-datetime.fromisoformat(window['start'])).total_seconds()
        if sim_clock.duration_seconds(time_step)>duration:
            raise ValueError(f'所选回合跨度{time_step}超过本阶段计算窗口（{duration/3600:g}小时），无法容纳一整轮；请减小回合跨度。')
    result['geographic_scope']=copy.deepcopy(selected_phase.get('geographic_scope'))
    result['input_constraints']=copy.deepcopy(selected_phase.get('input_constraints'))
    result['excluded_references']=[]
    for u in snapshot['definition']['units']:
        attendance=next((r for r in u['presence'] if r['phase_id']==snapshot['phase_id']),None)
        if attendance and attendance['status'] in ('later_participant','outside_scope'):
            result['excluded_references'].append({'id':u['id'],'name':u['name'],'team':u['team'],
                'status':attendance['status'],'evidence':copy.deepcopy(attendance['evidence'])})
    for phase in snapshot['definition']['phases']:
        value = copy.deepcopy(snapshot); value['phase_id'] = phase['id']
        try:
            historical_operations.configuration_template(value,force_scope,window=selected_window,termination_mode=termination_mode)
            error = ''
        except ValueError as exc:
            error = str(exc)
        result['phases'].append({'id': phase['id'], 'label': phase['label'], 'date': phase['date']['label'],
                                 'ready': not bool(error), 'error': error})
    try:
        template = historical_operations.configuration_template(snapshot,force_scope,window=selected_window,termination_mode=termination_mode)
    except ValueError as exc:
        result['error'] = str(exc)
        result['configuration_alternatives']=configuration_alternatives(battle,termination_mode)
        return result
    result.update(ready=True, configuration_template=template)
    result['aviation']=[{k:copy.deepcopy(u[k]) for k in ('id','name','team','echelon','facts','evidence')}
                        for u in snapshot['definition']['units'] if u['id'] in template.get('aviation',{})]
    if time_step is not None:
        template['clock']['time_step'] = time_step
        if selected_window and 'global_priors' in selected_window['definition'].get('parameter_estimates',{}):
            bounds=selected_window['definition']['bounds']
            seconds=(datetime.fromisoformat(bounds['end'])-datetime.fromisoformat(bounds['start'])).total_seconds()
            import math
            template['goal']['deadline_turn']=max(1,math.ceil(seconds/sim_clock.duration_seconds(time_step)))
    if termination_mode is not None:
        result['termination_mode']=termination_mode
        template['goal']['termination_mode']=termination_mode
    result['objective_guidance']=historical_operations.objective_guidance(snapshot)
    if force_scope=='campaign':
        from gentactix import campaign_scope
        result['organization_coverage']=campaign_scope.coverage(snapshot,list(template['actors']))
        if selected_window:
            result['excluded_references']=[{'id':u['id'],'name':u['name'],'team':u['team'],
                'status':selected_window['definition']['units'][u['id']]['representation'],
                'evidence':copy.deepcopy(selected_window['definition']['units'][u['id']]['evidence'])}
                for u in snapshot['definition']['units'] if u['id'] not in template['actors']]
    else:
        from gentactix import campaign_scope
        result['organization_coverage']=campaign_scope.local_coverage(snapshot)
    result['goal_semantics'] = {
        'delay': '截止回合目标方可用单位达到required_survivors，对方可用单位不在exit的600米内；不检查required_turns或objective占领累计',
        'breakout': '目标方足够可用单位在exit的600米内，连续required_turns回合',
        'crossing': '目标方至少required_survivors个可用编组完成登记通道渡运并进入objective半径，对方不占目标区，连续required_turns回合；未完成工作量或只到入口不算通过',
        'assault': '目标半径内存在目标方且无对方可用单位，连续required_turns回合；高压制单位不计控制',
        'rail': '交通完整度network不高于20，连续required_turns回合',
        'underground': '截止回合organization至少50且红方仍有可用单位',
        'reception': '接收标志accepted为1，连续required_turns回合；接收动作在第4回合窗口后可用',
        'scope': '这是现有计算器条件，不是对真实会战胜负的完整定义'}
    if 'campaign' in template:
        result['goal_semantics']['assault']='截止回合同时满足据点控制、全部阻援区域控制和min_force_fraction人员保存；单点占领不会提前结束；参数是模型估计，不强制历史结果'
    if termination_mode=='objectives':
        result['goal_semantics']['delay']='连续required_turns回合保持目标方可用单位达到required_survivors，对方可用单位不在exit的600米内'
        result['goal_semantics']['underground']='连续required_turns回合保持organization至少50且目标方仍有可用单位'
        if 'campaign' in template:result['goal_semantics']['assault']='据点控制、全部阻援区域控制和min_force_fraction人员保存同时满足并连续required_turns回合；不等待参考轮数或史料日期'
        result['goal_semantics']['termination']='按目标完成或目标方失去全部可用人员结算。deadline_turn仅为滚动规划参考，不自动判负；史料时间窗约束初态，延伸过程为反事实估计，不自动补入后续援军。'
    if 'campaign_plan' in template:
        result['goal_semantics']['assault']=historical_operations.goal_text(template)
        result['goal_semantics']['termination']='按双方目标图及其全军失能策略结算；同时达标判为平局。目标依赖、地域、人数与保持时间由实际态势判定，参考轮数不自动结束战局。'
    for unit in snapshot['definition']['units']:
        if unit['id'] in template['actors']:
            result['actors'].append({k: copy.deepcopy(unit[k]) for k in ('id','name','team','echelon','parent_id','facts','evidence')})
            if selected_window:
                result['actors'][-1]['window_scope']=copy.deepcopy(selected_window['definition']['units'][unit['id']])
                estimates=selected_window['definition'].get('parameter_estimates')
                if estimates:
                    result['actors'][-1]['window_scope']['parameter_estimates']=copy.deepcopy(estimates['actors'][unit['id']])
                    result['actors'][-1]['window_scope']['parameter_estimates'].pop('input_prior',None)
    result['sources'] = copy.deepcopy(snapshot['definition']['sources'])
    result['phase'] = next(copy.deepcopy(p) for p in snapshot['definition']['phases'] if p['id'] == snapshot['phase_id'])
    for name, point in anchors.collect_available_nodes(battle, battle=battle).items():
        result['geo_references'].append({'name': name, 'lat': point[0], 'lng': point[1],
            'kind': '地名参考，不是单位部署', 'metadata': anchors.node_metadata(name)})
    from .scenario_assembly import fixed_parameter_catalogue
    result['fixed_parameter_fields']=fixed_parameter_catalogue(result)
    return result


def _historical_tool(composer, tool, args):
    if tool == 'read_scenario_skill':
        return {'ok': True, 'skill': 'historical-unit-configuration', 'content': HISTORICAL_SKILL.read_text()}
    if composer.get('assembly_id'):
        from . import scenario_assembly
        return scenario_assembly.get(composer['assembly_id']).tool(composer['part'],tool,args,read_only=bool(composer.get('read_only')))
    if tool == 'get_scenario_basis':
        return {'ok': True, **{k: copy.deepcopy(v) for k,v in composer['basis'].items() if k not in ('initial','phases','fixed_parameter_fields')},
                'readonly_binding': '宿主已固定历史身份与来源；只填写configuration_template参数'}
    if tool == 'validate_scenario_configuration':
        try:
            from .scenario_assembly import validate_build_constraints
            validate_build_constraints(args.get('configuration'), composer['basis'])
            world = historical_operations.initial(composer['initial'], args.get('configuration'))
            scene = afsim_world.compile_scene(world, [], .001, native_rules=True)
            return {'ok': True, 'valid': True, 'entities': len(scene['entities']),
                    'resource_readiness': resource_readiness.assess(world),
                    'definition_hash': world['mission']['definition_hash'], 'effective_goal': historical_goal_text(args['configuration']),
                    'scope': 'input_and_model_validation_only; not_live_load'}
        except (ValueError, KeyError, TypeError) as exc:
            return {'ok': True, 'valid': False, 'error': str(exc),
                    'expected_top_level':sorted(composer['basis']['configuration_template']),
                    'received_configuration_type':type(args.get('configuration')).__name__,
                    'instruction': '填写configuration_template的完整参数，不是teams。保留全部真实ID和字段；未知值必须填写并说明估计。'}
    raise ValueError('当前历史配置操作不支持该工具')


def execute_tool(context,payload):
    composer=context['scenario_composer'];tool=payload.get('tool');args=payload.get('args') or {}
    if composer.get('kind') == 'historical_operation':
        return _historical_tool(composer, tool, args)
    if tool=='read_scenario_skill':
        upstream=ROOT/'vendor/afsim/afsim-skill/SKILL.md'
        return {'ok':True,'skill':'historical-afsim-scenario','content':SKILL.read_text(),
            'upstream':str(upstream.relative_to(ROOT)), 'upstream_content':upstream.read_text()[:2600] if upstream.exists() else None}
    if tool=='get_scenario_basis':
        seed=copy.deepcopy(composer['seed'])
        seed['configuration']={k:v for k,v in seed['configuration'].items()if k in ('teams','fire_accounting','fire_dynamics')}
        return {'ok':True,**seed,'readonly_binding':('version与historical_basis由宿主绑定；模型编辑configuration.teams，并保留种子已选的fire_accounting及fire_dynamics'
            if seed['configuration'].get('fire_accounting')or seed['configuration'].get('fire_dynamics')else'version与historical_basis由宿主绑定；模型只编辑configuration.teams')}
    if tool=='validate_scenario_configuration':
        try:
            config=bind_model_configuration(composer['mission_id'],args.get('configuration'),historical_base=composer.get('historical_base'))
            world,scene=validate_configuration(composer['mission_id'],config,historical_base=composer.get('historical_base'))
            return {'ok':True,'valid':True,'entities':len(scene['entities']),
                'definition_hash':world['mission']['definition_hash'],'scope':'input_and_template_validation_only; no_live_battle_write'}
        except (ValueError,KeyError,TypeError) as exc:
            return {'ok':True,'valid':False,'error':str(exc),
                'expected_top_level':['version','teams','historical_basis','fire_accounting','fire_dynamics'],
                'unit_fields':['name','basis_id','position','personnel','equipment','food','ammo','shells','aa_rounds','fuel_liters','fatigue'],
                'instruction':'模型只编辑configuration.teams；每个编组字段按种子完整保留。版本和来源由宿主绑定；estimates、map_center、map_radius_km是只读说明，不可放入configuration。'}
    raise ValueError('当前想定生成操作不支持该工具')


def _load_world(world, scene, execution_backend, cancel_check):
    if execution_backend not in ('afsim','narrative'):raise ValueError('未知执行引擎')
    from gentactix import movement_feedback
    movement_feedback.require_executor(world,backend=execution_backend)
    evidence=None
    if execution_backend=='afsim':
        probe={'id':'draft-'+uuid.uuid4().hex[:12]}
        positions,evidence=afsim_world.run_scene(probe,scene,cancel_check)
        afsim_world.apply_observations(world,positions,scene)
    if cancel_check and cancel_check():
        raise RuntimeError('已取消想定验证，未保存草稿')
    return evidence


def _save_draft(record, world):
    out=directory();out.mkdir(parents=True,exist_ok=True)
    path=out/(record['id']+'.json');tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(record,ensure_ascii=False,allow_nan=False));os.replace(tmp,path)
    return {**record,'preview_world':world}


def stage(identity,config,*,construction,parent=None,cancel_check=None,execution_backend='afsim',historical_base=None,combat_reference=None):
    world,scene=validate_configuration(identity,config,historical_base=historical_base,combat_reference=combat_reference)
    evidence = _load_world(world, scene, execution_backend, cancel_check)
    record={'id':uuid.uuid4().hex,'mission_id':world['mission']['id'],'configuration':copy.deepcopy(world['mission']['definition']['synthetic_configuration']),
        'definition_hash':world['mission']['definition_hash'],'construction':construction,
        'parent_id':parent,'afsim':evidence,'execution_backend':execution_backend,
        'validation':{'engine':'afsim' if evidence else 'dsh','scope':'native_load' if evidence else 'configuration_contract_only'},
        'scope':'staged_exercise_initial_state; no_battle_turn_executed'}
    if historical_base is not None:
        record.update(kind='historical_synthetic',historical_base=copy.deepcopy(historical_base))
    if combat_reference is not None:record['combat_reference']=copy.deepcopy(world['combat_reference'])
    return _save_draft(record, world)


def historical_draft_base(identity):
    parent=load(identity)
    if parent.get('kind')!='historical_operation' or parent.get('construction',{}).get('source')!='dsh_native_skill':
        raise ValueError('必须从DSH skill已验证的具名历史初态派生，不能使用教学代表编组')
    binding={'format':historical_operations.FORMAT,'initial':parent['initial'],'parameters':parent['parameters']}
    base=historical_operations.from_binding(binding)
    if missions.digest(base)!=parent['definition_hash'] or base['id']!=parent['mission_id']:
        raise ValueError('源历史配置与已验证摘要不一致')
    return parent,binding


def historical_goal_text(parameters):
    return historical_operations.goal_text(parameters)


class HistoricalLoadError(RuntimeError):
    def __init__(self, message, configuration_id):
        super().__init__(message)
        self.configuration_id = configuration_id


def stage_historical(snapshot, parameters, *, construction, parent=None, cancel_check=None, execution_backend='afsim'):
    from gentactix import sustainment
    parameters=copy.deepcopy(parameters)
    window=(parameters.get('campaign_scope')or{}).get('window')
    if window:
        from gentactix import campaign_windows
        parameters['campaign_scope']['window']=campaign_windows.transport_pin(snapshot,window)
    scenario_constraints.validate(parameters,construction.get('fixed_parameters'))
    # New interactive teaching scenarios start with all configured units
    # available. Preserve the original estimated schedule as reference data.
    if parameters.get('campaign') is not None:
        parameters['campaign']['availability_mode'] = 'immediate'
    historical_operations.initial(snapshot, parameters)
    parameters = copy.deepcopy(parameters)
    parameters['goal']['description'] = historical_goal_text(parameters)
    world = historical_operations.initial(snapshot, parameters)
    world['combat_reference'] = combat_effects.reference(world)
    scene = afsim_world.compile_scene(world, [], .001, native_rules=True)
    checkpoint = _save_draft({'id': uuid.uuid4().hex, 'kind': 'historical_configuration',
        'initial': copy.deepcopy(snapshot), 'parameters': copy.deepcopy(parameters),
        'construction': copy.deepcopy(construction), 'parent_id': parent,
        'execution_backend': execution_backend, 'definition_hash': world['mission']['definition_hash'],
        'scope': 'validated_inputs_only; cannot_create_session_until_native_load_succeeds'},world)
    try:
        evidence = _load_world(world, scene, execution_backend, cancel_check)
    except (ValueError,RuntimeError) as exc:
        raise HistoricalLoadError(str(exc),checkpoint['id']) from exc
    staged = _save_draft({'id': uuid.uuid4().hex, 'kind': 'historical_operation',
        'mission_id': world['mission']['id'], 'initial': copy.deepcopy(snapshot),
        'parameters': copy.deepcopy(parameters), 'definition_hash': world['mission']['definition_hash'],
        'combat_reference': copy.deepcopy(world['combat_reference']),
        'construction': construction, 'parent_id': parent, 'afsim': evidence, 'execution_backend': execution_backend,
        'validation': {'engine': execution_backend, 'scope': 'native_load' if evidence else 'configuration_contract_only'},
        'sustainment':sustainment.assess(world),
        'scope': 'parameterized_historical_units; partial_coverage_not_full_campaign_acceptance'}, world)
    _save_draft({k:v for k,v in {**checkpoint,'loaded_draft_id':staged['id']}.items() if k!='preview_world'},world)
    if construction.get('assembly_checkpoint_id') and not construction.get('manual_revision'):
        from . import scenario_checkpoints
        scenario_checkpoints.mark_loaded(construction['assembly_checkpoint_id'],staged['id'])
    return staged


class _IncompleteStageEvidence(ValueError):
    pass


class _InvalidStageReceipt(ValueError):
    pass


def _checked_stage_receipt(result, assembly):
    try:
        answer=h.parse_json_object(result.final_response)
    except (ValueError,TypeError) as exc:
        raise _InvalidStageReceipt('分片最终回执不是有效JSON') from exc
    if not isinstance(answer,dict) or set(answer)-{'revision','configuration_hash','explanation'}:
        raise _InvalidStageReceipt('分片只返回版本、配置哈希及说明，不返回整场配置')
    receipt=assembly.receipt()
    if any(answer.get(k)!=receipt[k] for k in ('revision','configuration_hash')):
        raise _InvalidStageReceipt('DSH分片返回过期版本或配置哈希')
    return answer


def build_historical_staged(basis,instruction,execution_backend,observer,*,resume_checkpoint=None,rebuild_failed_session=False):
    """Native registry hierarchy with bounded work, existing bridge and policies."""
    from . import scenario_assembly,scenario_checkpoints
    if observer.cancel_requested:raise RuntimeError('已取消想定生成')
    if resume_checkpoint:
        assembly,work=scenario_checkpoints.restore(resume_checkpoint,cancel_check=lambda:observer.cancel_requested)
        if (assembly.basis['initial']!=basis['initial'] or work['instruction']!=instruction
                or work['execution_backend']!=execution_backend
                or any(assembly.basis.get(k)!=basis.get(k) for k in
                       ('force_scope','campaign_window','fixed_parameters','required_models','termination_mode','time_step_constraint'))):
            scenario_assembly.close(assembly.id);raise ValueError('续接必须沿用检查点的来源、固定值、模型要求、范围与引擎')
        basis=assembly.basis
    else:
        assembly=scenario_assembly.create(basis,cancel_check=lambda:observer.cancel_requested)
        work=scenario_checkpoints.new_work(instruction,execution_backend)
    rebuilt=None
    if rebuild_failed_session:
        if not resume_checkpoint or not scenario_checkpoints.can_rebuild_failed_session({'state':assembly.export_state(),'work':work}):
            scenario_assembly.close(assembly.id);raise ValueError('只能明确重建尚未写入的失败单位分片会话；已校验片保持只读续接')
        failed_part=work['failed_part'];old=work['part_bindings'].pop(failed_part,None)
        rebuilt={'part':failed_part,'previous_session_id':old}
        work['attempts'].append({'action':'explicit_rebuild_failed_session',**rebuilt,'retained_validated_actors':len(assembly.filled)})
    bindings=work['bindings'];stages=work['stages'];explanations=work['explanations'];recoveries=0
    coordinator=bindings.get(work['coordinator']);live_bindings={}
    previous_runs=copy.deepcopy(work['runs']);previous_meta=copy.deepcopy(work['previous_meta'])
    previous_recoveries=work['recoveries'];start_validated=len(assembly.filled);skipped=[r['part'] for r in stages]
    namespace='scenario-'+assembly.id
    work.update(status='running',last_error='',operation_id=observer.operation_id)
    part=work['failed_part']
    def persist(_=None):
        work['runs']=previous_runs+[{**{k:copy.deepcopy(v) for k,v in run.items() if k!='events'},
            'events':[{'type':'tool/call','name':e.get('name')} for e in run.get('events',[]) if e.get('type')=='tool/call']}
            for run in observer.runs]
        work['previous_meta']=previous_meta+[observer.meta()]
        work['recoveries']=previous_recoveries+recoveries
        return scenario_checkpoints.save(assembly,work)
    def bind(current):
        sid=current['session_id'];bindings[sid]=copy.deepcopy(current);live_bindings[sid]=current
        work['part_bindings'][part]=sid
        if part=='globals':work['coordinator']=sid
        persist()
    assembly.on_change=persist
    try:
        persist()
        if execution_backend=='afsim':h.enable_afsim_runtime()
        if resume_checkpoint and coordinator and len(stages)<len(assembly.parts)+2:
            restored=h.restore_unit_session(coordinator,context=assembly.context('globals'),namespace=namespace,role='scenario-builder')
            live_bindings[restored['session_id']]=restored
        parts=['globals',*assembly.parts,'final']
        for index,part in enumerate(parts):
            if index<len(stages):continue
            work['failed_part']=part
            if observer.cancel_requested:raise RuntimeError('已取消想定生成；分片草稿未提交')
            observer.progress.update(phase='scenario_configuration',configuration_stage=part,
                completed_stages=index,total_stages=len(parts),completed_actors=len(assembly.filled),total_actors=len(assembly.ids))
            start=len(observer.runs)
            final=part=='final'
            audit_start=len(assembly.audit);recovery_of=None
            restored_write=bool(resume_checkpoint and not final and
                (assembly.global_ready if part=='globals' else set(assembly.assigned(part))<=assembly.filled)
                and any(r['part']==part for r in assembly.audit))
            persist()
            prompt=('这是分片想定配置任务。先调用read_scenario_skill和get_scenario_basis，遵守本次分配范围。'
                '完整配置保存在宿主，禁止重复输出完整JSON或改写历史身份。'
                + ('本次只做全量复核：本轮先调用get_scenario_basis读取当前版本与配置摘要，旧globals记忆不是当前单位配置；再调用validate_scenario_configuration，不传配置；有效回执须是完整原生模板校验，不能将分片校验称作全量通过。' if final else
                   '公共条件会话只填写公共参数；单位会话只填写已分配的单位，沿用只读公共条件。'
                   '使用update_scenario_configuration(revision=当前版本,patch=本片完整填写内容)，根据错误修正；不传整场配置。')
                +'最终仅返回JSON {"revision":工具返回的当前版本,"configuration_hash":"工具返回的配置哈希","explanation":"本片估计依据、限制或复核结论"}。'
                f'执行引擎：{execution_backend}。用户要求：'+instruction)
            if resume_checkpoint:
                prompt+='\n这是中断后的继续执行。此前回复没有完成本片工具提交。当前仅有这四个原生函数：read_scenario_skill、get_scenario_basis、update_scenario_configuration、validate_scenario_configuration。函数名不得加任何前缀或命名空间，不存在其他同名函数。先实际调用read_scenario_skill，再实际调用get_scenario_basis；根据当前revision，以update_scenario_configuration提交本片（final片改为validate_scenario_configuration）。普通文本或代码块中的调用文字不会执行，也不会被宿主接纳。收到真实工具结果后再返回简短JSON回执，不复述此前未执行的提案。'
            if part=='globals' and 'global_priors' in ((basis.get('campaign_window') or {}).get('definition',{}).get('parameter_estimates') or {}):
                prompt+='\n本公共片有已声明为估计的完整数值基线。优先只提交需要改变的字段；若基线满足用户要求，patch只更新assumptions写复核说明即可。不要重新生成整份公共JSON，不要把先验称史实。必须取得update有效revision和configuration_hash，口头复核不能代替工具提交。'
            priors=((basis.get('campaign_window') or {}).get('definition',{}).get('parameter_estimates') or {}).get('actors',{})
            if part.startswith('actors:') and all('input_prior' in priors.get(i,{}) for i in assembly.assigned(part)):
                prompt+='\n本单位片有明确标记为模型估计的可重放输入基线。先读skill、来源、范围及本片configuration，按用户要求只更新有差异的字段；相符时对本片每个actor只写assumption复核说明。patch仍覆盖本片全部actor ID，须取得有效update回执。不要重写所有相同数值，不把这些人工先验称史实。'
            parent=coordinator['session_id'] if coordinator and part.startswith('actors:') else None
            # These are product-side DSH native registry work units, using the
            # same lifecycle/event/cancel adapter as existing unit Agents.
            required={'get_scenario_basis','validate_scenario_configuration'} if final else {'read_scenario_skill','get_scenario_basis','update_scenario_configuration'}
            if restored_write:
                required={'read_scenario_skill','get_scenario_basis'}
                prompt='本片已经由宿主真实工具校验并保存，但最终回执未完成。只读恢复：调用read_scenario_skill与get_scenario_basis，禁止更新；返回当前revision、configuration_hash和explanation的JSON。不得把此前失败文本当作写入。'
            current_binding=coordinator if final else bindings.get(work['part_bindings'].get(part))
            try:
                result,binding=h.unit_run(current_binding,prompt,observer,
                    context=assembly.context(part,read_only=restored_write),namespace=namespace,role='scenario-builder',parent_session_id=parent,
                    dispose_on_failure=True,on_session=bind)
                bind(binding)
                calls={e.get('name') for run in observer.runs[start:] for e in run.get('events',[]) if e.get('type')=='tool/call'}
                if not required<=calls:
                    raise _IncompleteStageEvidence('缺少DSH分片配置实际工具调用证据：'+', '.join(sorted(required-calls))+
                        ('；普通回复中的工具标记没有执行，参数未提交' if '<tool_call>' in result.final_response else ''))
                _checked_stage_receipt(result,assembly)
            except (h.HarnessRunError,_IncompleteStageEvidence,_InvalidStageReceipt) as exc:
                failed=observer.runs[start:]
                calls={e.get('name') for run in failed for e in run.get('events',[]) if e.get('type')=='tool/call'}
                ready=(assembly.validation is not None if final else assembly.global_ready if part=='globals'
                       else set(assembly.assigned(part))<=assembly.filled)
                saved=final or any(r['part']==part for r in assembly.audit[audit_start:])
                recovery_evidence=(required-{'get_scenario_basis'} if final and isinstance(exc,_IncompleteStageEvidence) else required)
                if observer.cancel_requested or recoveries or not ready or not saved or not recovery_evidence<=calls:raise
                # Never consume failed model output. Keep only already checked
                # tool writes, then obtain a completed read-only native receipt.
                recoveries+=1;recovery_of=failed[-1]['session_id']
                failed[-1].update(accepted=False,rejection='stale_or_invalid_final_receipt' if isinstance(exc,_InvalidStageReceipt) else 'basis_read_missing_after_valid_final_template' if isinstance(exc,_IncompleteStageEvidence) else 'final_output_failed_after_valid_draft')
                observer.progress.update(phase='scenario_receipt_recovery',completed_actors=len(assembly.filled))
                recovery_start=len(observer.runs)
                result,binding=h.unit_run(None,
                    '本片参数已经由真实工具保存并通过校验，但上一个会话的最终回执或必要读取不完整，其输出未作为成功接纳。'
                    '这是只读回执复核，不是重新生成参数。只调用get_scenario_basis读取当前revision与configuration_hash，'
                    '不要调用任何更新、观测战局或执行工具。直接输出JSON {"revision":当前整数,"configuration_hash":"读取到的哈希","explanation":"已核对宿主保存的本片配置；参数依据保存在草稿"}。',
                    observer,context=assembly.context(part,read_only=True),namespace=namespace,role='scenario-builder',
                    parent_session_id=parent or (coordinator or {}).get('session_id'),dispose_on_failure=True,on_session=bind)
                bind(binding)
                if not any(e.get('type')=='tool/call' and e.get('name')=='get_scenario_basis'
                           for run in observer.runs[recovery_start:] for e in run.get('events',[])):
                    raise ValueError('回执恢复缺少实际只读工具调用证据')
            if part=='globals':
                coordinator=binding;work['coordinator']=binding['session_id']
            calls={e.get('name') for run in observer.runs[start:] for e in run.get('events',[]) if e.get('type')=='tool/call'}
            if not required<=calls:raise ValueError('缺少DSH分片配置实际工具调用证据')
            answer=_checked_stage_receipt(result,assembly)
            receipt=assembly.receipt()
            if final:configuration=assembly.finish(answer)
            elif part=='globals' and not assembly.global_ready or part.startswith('actors:') and not set(assembly.assigned(part))<=assembly.filled:
                raise ValueError('分片草稿未实际完成，不能仅凭模型声明通过')
            explanation=str(answer.get('explanation') or '')[:1200]
            if explanation:explanations.append(explanation)
            stages.append({'part':part,'session_id':binding['session_id'],'parent_session_id':parent,
                **receipt,'recovery_of':recovery_of,'restored_validated_write':restored_write,
                'run_ids':[r.get('id') for r in observer.runs[start:]]})
            work['failed_part']=None;persist()
        if len(skipped)==len(parts):configuration=assembly.finish(stages[-1])
        work.update(status='configured',failed_part=None,last_error='');persist()
        observer.progress.update(completed_stages=len(parts),completed_actors=len(assembly.ids),phase='scenario_validation')
        return configuration,{'source':'dsh_native_skill','skill':'historical-unit-configuration',
            'required_models':copy.deepcopy(basis.get('required_models', [])),
            **({'fixed_parameters':copy.deepcopy(basis['fixed_parameters'])} if basis.get('fixed_parameters') else {}),
            'workflow':'native_agent_registry_scoped_drafts','page_size':scenario_assembly.PAGE_SIZE,'recovery_count':previous_recoveries+recoveries,
            'assembly_checkpoint_id':assembly.id,
            'resume':{'resumed':bool(resume_checkpoint),'skipped_stages':skipped,'validated_actors_at_start':start_validated,'prior_operations_meta':previous_meta,
                      'rebuilt_session':rebuilt},
            'explanation':'；'.join(explanations)[:4000],'stages':stages,'draft_updates':copy.deepcopy(assembly.audit),
            'runs':extensions.safe(previous_runs+observer.runs),'meta':observer.meta()}
    except Exception as exc:
        observer.record_failure(exc)
        calls=[e.get('name') for run in observer.runs for e in run.get('events',[]) if e.get('type')=='tool/call']
        work['attempts'].append({'part':part,'session_id':work['part_bindings'].get(part),'tool_calls':calls,'error':str(exc)[:1000]})
        work.update(status='interrupted',failed_part=part,last_error=str(exc)[:1000])
        try:
            record=persist()
            exc.assembly_id=assembly.id;exc.assembly_summary=scenario_checkpoints.summary(record)
        except (ValueError,OSError,TypeError):
            pass  # Never claim the latest prefix was saved when storage failed.
        raise
    finally:
        h.dispose_unit_sessions(live_bindings)
        scenario_assembly.close(assembly.id)


class BuildRequest(BaseModel):
    mission_id:str=Field(max_length=128)
    instruction:str=Field(default='',max_length=4000)
    operation_id:str=Field(default_factory=lambda:uuid.uuid4().hex,pattern=r'^[a-f0-9]{32}$')
    execution_backend:str=Field(default='afsim',pattern=r'^(afsim|narrative)$')
    historical_draft_id:str | None=Field(default=None,pattern=r'^[a-f0-9]{32}$')


class HistoricalDeriveRequest(BaseModel):
    base_draft_id:str=Field(pattern=r'^[a-f0-9]{32}$')
    operation_id:str=Field(default_factory=lambda:uuid.uuid4().hex,pattern=r'^[a-f0-9]{32}$')
    execution_backend:str=Field(default='afsim',pattern=r'^(afsim|narrative)$')


class ValidateRequest(BaseModel):
    mission_id:str=Field(max_length=128)
    configuration:dict
    parent_draft_id:str=Field(pattern=r'^[a-f0-9]{32}$')
    operation_id:str=Field(default_factory=lambda:uuid.uuid4().hex,pattern=r'^[a-f0-9]{32}$')
    execution_backend:str=Field(default='afsim',pattern=r'^(afsim|narrative)$')


class HistoricalBuildRequest(BaseModel):
    battle: str = Field(max_length=200)
    version: str | None = Field(default=None, max_length=64)
    phase_id: str = Field(max_length=96)
    instruction: str = Field(default='', max_length=4000)
    time_step: str | None = Field(default=None, max_length=48)
    termination_mode: Literal['objectives','deadline'] = 'objectives'
    force_scope: Literal['phase','campaign'] = 'phase'
    campaign_window_id: str | None = Field(default=None,max_length=96)
    campaign_window_version: str | None = Field(default=None,max_length=64)
    required_models: list[HistoricalRequiredModel] = Field(default_factory=list, max_length=6)
    fixed_parameters: list[dict] = Field(default_factory=list,max_length=scenario_constraints.MAX_FIXED_INPUTS)
    operation_id: str = Field(default_factory=lambda: uuid.uuid4().hex, pattern=r'^[a-f0-9]{32}$')
    execution_backend: str = Field(default='afsim', pattern=r'^(afsim|narrative)$')


class HistoricalValidateRequest(BaseModel):
    parameters: dict
    required_models: list[HistoricalRequiredModel] = Field(default_factory=list, max_length=6)
    fixed_parameters: list[dict] | None = Field(default=None,max_length=scenario_constraints.MAX_FIXED_INPUTS)
    parent_draft_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    operation_id: str = Field(default_factory=lambda: uuid.uuid4().hex, pattern=r'^[a-f0-9]{32}$')
    execution_backend: str = Field(default='afsim', pattern=r'^(afsim|narrative)$')


class HistoricalRetryRequest(BaseModel):
    configuration_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    operation_id: str = Field(default_factory=lambda:uuid.uuid4().hex,pattern=r'^[a-f0-9]{32}$')


class HistoricalResumeRequest(BaseModel):
    model_config={'extra':'forbid'}
    assembly_id:str=Field(pattern=r'^[a-f0-9]{32}$')
    operation_id:str=Field(default_factory=lambda:uuid.uuid4().hex,pattern=r'^[a-f0-9]{32}$')
    rebuild_failed_session:bool=Field(default=False,strict=True)


def _load_failure(exc):
    return HTTPException(502, {'message':'想定配置已保存，装载未完成：'+str(exc)+'；可重试装载，无需重新生成。',
                               'configuration_id':exc.configuration_id})


def _assembly_failure(exc,cancelled=False):
    if not getattr(exc,'assembly_id',None):return None
    summary=exc.assembly_summary
    return HTTPException(409 if cancelled else 502,{
        'message':('已取消生成' if cancelled else '分片生成未完成：'+str(exc))+
            f'；已保存并校验{summary["validated_actors"]}/{summary["total_actors"]}个单位，可继续未完成分片。已有战局未改动。',
        'assembly_id':exc.assembly_id,'assembly_progress':summary})


def build_router(serialized):
    router=APIRouter()

    @router.get('/api/historical-scenarios/assemblies/{identity}/revision')
    def read_failed_revision(identity:str):
        from . import scenario_checkpoints
        try:
            record=scenario_checkpoints.revision_record(identity)
            state=record['state'];basis=state['basis']
            from . import scenario_assembly
            from gentactix import support_dynamics
            validation_error=None;food_errors=[]
            try:
                scenario_assembly.validate_build_constraints(state['configuration'],basis)
                historical_operations._validate(basis['initial'],state['configuration'])
            except (ValueError,KeyError,TypeError) as exc:
                validation_error=str(exc)
                if isinstance(exc,support_dynamics.FoodLoadingError):
                    for unit,actor in state['configuration']['actors'].items():
                        try:
                            support_dynamics.validate_food_loading(state['configuration'].get('support_dynamics'),
                                {'historical_unit_id':unit,'personnel':{'committed':actor['personnel']},'logistics':actor['logistics']})
                        except support_dynamics.FoodLoadingError as quoted:food_errors.append(copy.deepcopy(quoted.food_loading))
                        except (ValueError,KeyError,TypeError):pass  # Full admission still rejects other invalid fields.
            return {'id':identity,'kind':'historical_configuration_revision','requires_validation':True,
                'checkpoint_hash':record['checkpoint_hash'],'parameters':copy.deepcopy(state['configuration']),
                'initial':copy.deepcopy(basis['initial']),'execution_backend':record['work']['execution_backend'],
                'required_models':copy.deepcopy(basis.get('required_models',[])),
                'fixed_parameters':copy.deepcopy(basis.get('fixed_parameters')),
                'last_error':record['work']['last_error'],
                'validation_error':validation_error,'food_loading_errors':food_errors,
                'scope':'原DSH草稿仅供显式修订，未通过完整校验；无地图预览、无仿真执行。原草稿与原会话保留。'}
        except (ValueError,KeyError,TypeError) as exc:raise HTTPException(422,str(exc)) from exc

    @router.get('/api/historical-scenarios/drafts/{identity}')
    def read_historical(identity:str):
        try:
            parent,binding=historical_draft_base(identity)
            from gentactix import sustainment
            world=missions.from_definition(historical_operations.from_binding(binding))
            world['combat_reference']=copy.deepcopy(parent['combat_reference'])
            return {**parent,'preview_world':world,'sustainment':sustainment.assess(world)}
        except (ValueError,KeyError,TypeError) as exc:raise HTTPException(422,str(exc)) from exc

    @router.post('/api/scenarios/from-historical')
    @serialized
    def derive_historical(req:HistoricalDeriveRequest):
        observer=h.RunObserver('正在从同一历史初态派生合成演习')
        with _active_lock:_active[req.operation_id]=observer
        try:
            from gentactix import synthetic_history
            parent,binding=historical_draft_base(req.base_draft_id)
            seed=synthetic_history.seed(binding)
            construction={'source':'dsh_native_skill','skill':'historical-unit-configuration',
                'workflow':'historical_baseline_derivation','base_draft_id':parent['id'],
                'base_construction':copy.deepcopy(parent['construction']),
                'explanation':'直接继承已验证DSH历史配置，未重新调用模型或替换初始单位；后续修改作为合成演习假设。'}
            draft=stage(parent['mission_id'],seed['configuration'],construction=construction,parent=parent['id'],
                historical_base=binding,execution_backend=req.execution_backend,cancel_check=lambda:observer.cancel_requested,
                combat_reference=parent.get('combat_reference'))
            return {**seed,'preview_world':draft['preview_world'],'draft':draft}
        except (ValueError,KeyError,TypeError,RuntimeError) as exc:
            raise HTTPException(422,'历史初态派生失败：'+str(exc)) from exc
        finally:
            with _active_lock:_active.pop(req.operation_id,None)

    @router.get('/api/historical-scenarios/basis')
    def get_historical_basis(battle: str, phase_id: str | None = None, version: str | None = None, termination_mode: Literal['objectives','deadline'] | None = None, force_scope: Literal['phase','campaign']='phase', campaign_window_id: str | None=None, campaign_window_version: str | None=None):
        try:
            return historical_basis(battle, phase_id, version=version,termination_mode=termination_mode,force_scope=force_scope,campaign_window_id=campaign_window_id,campaign_window_version=campaign_window_version)
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post('/api/historical-scenarios/build')
    @serialized
    def build_historical(req: HistoricalBuildRequest):
        try:
            basis = historical_basis(req.battle, req.phase_id, time_step=req.time_step, version=req.version,termination_mode=req.termination_mode,force_scope=req.force_scope,campaign_window_id=req.campaign_window_id,campaign_window_version=req.campaign_window_version)
            if not basis['ready']: raise ValueError(basis['error'])
            from .scenario_assembly import prepare_required_models
            prepare_required_models(basis,req.required_models)
            if req.fixed_parameters:scenario_constraints.prepare(basis,req.fixed_parameters)
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc
        observer = h.RunObserver('DSH正在生成具名历史单位计算参数')
        observer.operation_id=req.operation_id
        with _active_lock:
            _active[req.operation_id] = observer
        try:
            from . import scenario_assembly
            if len(basis['actors'])>scenario_assembly.PAGE_SIZE or basis.get('interaction') or req.required_models or req.fixed_parameters:
                configuration,construction=build_historical_staged(basis,req.instruction,req.execution_backend,observer)
                scenario_assembly.validate_build_constraints(configuration,basis)
                observer.progress['phase']='afsim_load' if req.execution_backend=='afsim' else 'scenario_validation'
                return stage_historical(basis['initial'],configuration,construction=construction,
                    cancel_check=lambda:observer.cancel_requested,execution_backend=req.execution_backend)
            context = {'scenario_composer': {'kind': 'historical_operation', 'initial': basis['initial'], 'basis': basis}}
            prompt = ('调用read_scenario_skill读取本次专用skill，然后get_scenario_basis读取固定历史单位与待填写模板。'
                '不得使用教学代表编组。填写完整configuration_template，未知参数显式估计；'
                '真实调用validate_scenario_configuration校验后只输出JSON {"configuration":完整参数,"explanation":"估计范围与限制"}。'
                f'执行引擎{req.execution_backend}。用户要求：'+req.instruction)
            result = h._run_brain(prompt, None, role='scenario-builder', observer=observer, native_context=context)
            answer = h.parse_json_object(result.final_response)
            calls = {event.get('name') for run in observer.runs for event in run.get('events', []) if event.get('type') == 'tool/call'}
            if not {'read_scenario_skill','get_scenario_basis','validate_scenario_configuration'} <= calls:
                raise ValueError('缺少DSH实际skill/史料/参数校验调用证据')
            if not isinstance(answer, dict) or set(answer)-{'configuration','explanation'}:
                raise ValueError('只能返回configuration与explanation')
            construction = {'source': 'dsh_native_skill', 'skill': 'historical-unit-configuration',
                'required_models': req.required_models,
                **({'fixed_parameters':copy.deepcopy(basis['fixed_parameters'])} if basis.get('fixed_parameters') else {}),
                'explanation': str(answer.get('explanation') or '')[:2000], 'runs': extensions.safe(observer.runs), 'meta': observer.meta()}
            scenario_assembly.validate_build_constraints(answer.get('configuration'), basis)
            return stage_historical(basis['initial'], answer['configuration'], construction=construction,
                cancel_check=lambda: observer.cancel_requested, execution_backend=req.execution_backend)
        except HistoricalLoadError as exc:
            if observer.cancel_requested:raise HTTPException(409,'已取消装载；已有战局未改动') from exc
            raise _load_failure(exc) from exc
        except (ValueError, KeyError, TypeError, RuntimeError) as exc:
            saved=_assembly_failure(exc,observer.cancel_requested)
            if saved:raise saved from exc
            if observer.cancel_requested:raise HTTPException(409,'已取消历史参数生成；草稿未提交，已有战局未改动') from exc
            raise HTTPException(502, '历史参数生成未完成：'+str(exc)+'；已有战局未改动') from exc
        finally:
            with _active_lock:
                _active.pop(req.operation_id, None)

    @router.post('/api/historical-scenarios/resume')
    @serialized
    def resume_historical(req:HistoricalResumeRequest):
        from . import scenario_checkpoints,scenario_assembly
        try:
            record=scenario_checkpoints.read(req.assembly_id)
            if record['work']['loaded_draft_id']:raise ValueError('该配置已完成装载，请使用已保存的想定')
            if req.rebuild_failed_session and not scenario_checkpoints.can_rebuild_failed_session(record):
                raise ValueError('只能重建尚未写入的失败单位分片会话')
        except (ValueError,KeyError,TypeError) as exc:raise HTTPException(422,str(exc)) from exc
        basis=record['state']['basis'];work=record['work']
        observer=h.RunObserver('DSH正在继续已保存的分片配置');observer.operation_id=req.operation_id
        observer.progress.update(phase='scenario_resume',completed_actors=len(record['state']['filled']),
            total_actors=len(record['state']['configuration']['actors']))
        with _active_lock:_active[req.operation_id]=observer
        try:
            configuration,construction=build_historical_staged(basis,work['instruction'],work['execution_backend'],observer,
                resume_checkpoint=req.assembly_id,rebuild_failed_session=req.rebuild_failed_session)
            scenario_assembly.validate_build_constraints(configuration,basis)
            observer.progress['phase']='afsim_load' if work['execution_backend']=='afsim' else 'scenario_validation'
            return stage_historical(basis['initial'],configuration,construction=construction,
                cancel_check=lambda:observer.cancel_requested,execution_backend=work['execution_backend'])
        except HistoricalLoadError as exc:raise _load_failure(exc) from exc
        except (ValueError,KeyError,TypeError,RuntimeError) as exc:
            saved=_assembly_failure(exc,observer.cancel_requested)
            if saved:raise saved from exc
            raise HTTPException(409 if observer.cancel_requested else 502,'分片续接未完成：'+str(exc)+'；已有战局未改动') from exc
        finally:
            with _active_lock:_active.pop(req.operation_id,None)

    @router.post('/api/historical-scenarios/validate')
    @serialized
    def validate_historical(req: HistoricalValidateRequest):
        observer = h.RunObserver('历史配置装载验证')
        with _active_lock:
            _active[req.operation_id] = observer
        try:
            parent = load(req.parent_draft_id)
            from . import scenario_assembly
            if parent.get('kind')=='historical_assembly':
                from . import scenario_checkpoints
                parent=scenario_checkpoints.revision_record(req.parent_draft_id)
                basis=parent['state']['basis'];work=parent['work']
                if req.execution_backend!=work['execution_backend'] or sorted(req.required_models)!=sorted(basis.get('required_models',[])):
                    raise ValueError('失败配置修订须保留原执行引擎与必需模型，不能绕过原需求')
                fixed=basis.get('fixed_parameters')
                if req.fixed_parameters is not None and req.fixed_parameters!=(fixed or {}).get('values',[]):
                    raise ValueError('失败配置修订须保留原固定参数；如需改变原约束，请明确重新生成')
                scenario_assembly.validate_build_constraints(req.parameters,basis)
                construction={'source':'dsh_native_skill','skill':'historical-unit-configuration',
                    'workflow':'manual_revision_of_failed_native_configuration',
                    'required_models':copy.deepcopy(basis.get('required_models',[])),
                    'stages':copy.deepcopy(work['stages']),
                    **({'fixed_parameters':copy.deepcopy(fixed)} if fixed else {}),
                    'revision_base':{'assembly_id':parent['id'],'checkpoint_hash':parent['checkpoint_hash'],
                        'configuration_hash':missions.digest(parent['state']['configuration'])},
                    'explanation':'原DSH分片配置最终校验失败；用户显式修订后全量重新校验。原参数、会话和失败记录保留，不声称DSH生成了人工改值。'}
                initial=basis['initial']
            elif parent.get('kind')=='historical_operation' and parent['construction'].get('source')=='dsh_native_skill':
                construction=copy.deepcopy(parent['construction'])
            else:raise ValueError('缺少具名历史单位的DSH skill草稿')
            scenario_assembly.validate_required_models(req.parameters, req.required_models)
            if parent.get('kind')!='historical_assembly':initial=parent['initial']
            previous=construction.get('required_models',[])
            if previous!=req.required_models:
                construction.setdefault('generated_required_models',copy.deepcopy(previous))
            construction['required_models']=copy.deepcopy(req.required_models)
            construction['manual_revision']=True
            if req.fixed_parameters is not None:
                checked={'configuration_template':copy.deepcopy(req.parameters),'actors':[]}
                scenario_constraints.prepare(checked,req.fixed_parameters)
                # prepare validates paths; stage checks actual typed values,
                # never substitute the seeded copy for the submitted input.
                construction['fixed_parameters']=checked['fixed_parameters']
                construction['manual_revision']=True
            return stage_historical(initial, req.parameters, construction=construction, parent=parent['id'],
                cancel_check=lambda: observer.cancel_requested, execution_backend=req.execution_backend)
        except HistoricalLoadError as exc:
            if observer.cancel_requested:raise HTTPException(409,'已取消装载；已有战局未改动') from exc
            raise _load_failure(exc) from exc
        except (ValueError, KeyError, TypeError, RuntimeError) as exc:
            raise HTTPException(422, '历史配置验证失败：'+str(exc)) from exc
        finally:
            with _active_lock:
                _active.pop(req.operation_id, None)

    @router.post('/api/historical-scenarios/retry-load')
    @serialized
    def retry_historical_load(req: HistoricalRetryRequest):
        observer=h.RunObserver('正在重试已保存配置的装载')
        with _active_lock:_active[req.operation_id]=observer
        try:
            saved=load(req.configuration_id)
            if saved.get('kind')!='historical_configuration' or saved.get('construction',{}).get('source')!='dsh_native_skill':
                raise ValueError('重试只接受已保存的DSH历史配置，不能替换输入或创建无来源单位')
            spec=historical_operations.definition(saved['initial'],saved['parameters'])
            if missions.digest(spec)!=saved['definition_hash']:raise ValueError('已保存配置与冻结摘要不一致')
            observer.progress['phase']='afsim_load' if saved['execution_backend']=='afsim' else 'scenario_validation'
            result=stage_historical(saved['initial'],saved['parameters'],construction=saved['construction'],
                parent=saved['id'],execution_backend=saved['execution_backend'],cancel_check=lambda:observer.cancel_requested)
            _save_draft({**saved,'loaded_draft_id':result['id']},result['preview_world'])
            return result
        except HistoricalLoadError as exc:
            if observer.cancel_requested:raise HTTPException(409,'已取消装载；已有战局未改动') from exc
            raise _load_failure(exc) from exc
        except (ValueError,KeyError,TypeError,RuntimeError) as exc:
            raise HTTPException(422,'无法重试想定装载：'+str(exc)) from exc
        finally:
            with _active_lock:_active.pop(req.operation_id,None)

    @router.post('/api/scenarios/operations/{operation_id}/cancel')
    def cancel(operation_id:str):
        with _active_lock:
            observer=_active.get(operation_id)
        if observer is None:
            raise HTTPException(409,'想定操作已结束或尚未开始')
        return {'ok':True,'native':h.cancel_observer(observer)}

    @router.get('/api/scenarios/operations/{operation_id}/progress')
    def operation_progress(operation_id:str):
        with _active_lock:observer=_active.get(operation_id)
        return {'active':observer is not None,'cancel_requested':bool(observer and observer.cancel_requested),
                'progress':extensions.safe(dict(observer.progress)) if observer else None}

    @router.get('/api/scenarios/basis/{mission_id}')
    def get_basis(mission_id:str):
        try:
            seed=scenario_basis.exercise_seed(mission_id)
            world=missions.initial(mission_id,configuration=seed['configuration'])
            return {**seed,'preview_world':world}
        except (ValueError,KeyError) as exc:
            raise HTTPException(422,str(exc)) from exc

    @router.post('/api/scenarios/build')
    @serialized
    def build(req:BuildRequest):
        observer=h.RunObserver('DSH正在生成史实基础演习配置')
        with _active_lock:
            _active[req.operation_id]=observer
        try:
            binding=None;reference=None
            if req.historical_draft_id:
                from gentactix import synthetic_history
                historical_parent,binding=historical_draft_base(req.historical_draft_id)
                reference=historical_parent.get('combat_reference')
                seed=synthetic_history.seed(binding)
            else:seed=scenario_basis.exercise_seed(req.mission_id)
            context={'scenario_composer':{'mission_id':req.mission_id,'seed':seed,'historical_base':binding}}
            prompt=('调用read_scenario_skill，依照skill生成史实基础派生配置；'
                f'本次执行引擎为{req.execution_backend}，narrative表示全部过程由DSH推演，不运行AFSIM。'
                '调用get_scenario_basis读取本次史料基础，调用validate_scenario_configuration校验最终候选。'
                '只返回JSON {"configuration":...,"explanation":"说明估计参数"}。'
                '不生成战损结果，不把派生演习称为原始历史复原。用户需求：'+req.instruction)
            answer,config=generate_exercise_candidate(req.mission_id,prompt,context,observer,
                historical_base=binding,combat_reference=reference)
            construction={'source':'dsh_native_skill','skill':'historical-afsim-scenario',
                'explanation':str(answer.get('explanation') or '')[:2000],
                'runs':extensions.safe(observer.runs),'meta':observer.meta()}
            return stage(req.mission_id,config,construction=construction,cancel_check=lambda:observer.cancel_requested,
                execution_backend=req.execution_backend,historical_base=binding,combat_reference=reference)
        except (ValueError,KeyError,TypeError,RuntimeError) as exc:
            detail = ('AI 返回的 JSON 无法解析：' + exc.diagnostics['reason']
                      if isinstance(exc, h.JSONOutputError) else str(exc))
            raise HTTPException(502,'想定配置生成未完成：'+detail+'；已有战局未改动') from exc
        finally:
            with _active_lock:
                _active.pop(req.operation_id,None)

    @router.post('/api/scenarios/validate')
    @serialized
    def validate(req:ValidateRequest):
        observer=h.RunObserver('AFSIM想定装载验证')
        with _active_lock:
            _active[req.operation_id]=observer
        try:
            parent=load(req.parent_draft_id)
            derived=parent.get('kind')=='historical_synthetic'
            if ((not derived and parent['mission_id']!=req.mission_id) or parent['construction'].get('source')!='dsh_native_skill'):
                raise ValueError('缺少本战役的DSH skill生成基础')
            return stage(req.mission_id,req.configuration,construction=parent['construction'],parent=parent['id'],
                cancel_check=lambda:observer.cancel_requested,execution_backend=req.execution_backend,
                historical_base=parent.get('historical_base') if derived else None,combat_reference=parent.get('combat_reference'))
        except (ValueError,KeyError,TypeError,RuntimeError) as exc:
            raise HTTPException(422,'想定装载验证失败：'+str(exc)) from exc
        finally:
            with _active_lock:
                _active.pop(req.operation_id,None)
    return router
