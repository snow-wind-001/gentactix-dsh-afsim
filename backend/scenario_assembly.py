"""Operation-owned historical configuration drafts, accessed by native DSH tools.

This module edits candidate inputs, never a live world or model transport. The
runtime bridge deep-copies every context; only an opaque scope binding crosses it.
"""
import copy
import json
import re
import threading
import uuid

from gentactix import historical_operations, missions, sim_clock, scenario_constraints

PAGE_SIZE=4
STATE_FORMAT='historical-assembly-state-1'
OPTIONAL_GLOBAL_FIELDS=('partitions','support_dynamics','supply_distribution','terrain_model','supply_schedule','operation_boundary','campaign_lifecycle','movement_feedback','fire_accounting','fire_dynamics')
_registry={}
_lock=threading.RLock()


def validate_selected_step(configuration, basis):
    constraint = basis.get('time_step_constraint')
    if constraint:
        if not isinstance(configuration, dict) or not isinstance(configuration.get('clock'), dict):
            raise ValueError('回合跨度校验需要完整计算时钟对象')
        label = configuration['clock'].get('time_step')
        if sim_clock.duration_seconds(label) != constraint['seconds']:
            raise ValueError(f'回合跨度须遵守启动页选择{constraint["label"]}；不能由生成参数覆盖。请调整截止轮数以满足阶段时间范围。')


def validate_build_constraints(configuration,basis):
    if not isinstance(configuration,dict):
        raise ValueError('configuration与回合跨度校验需要JSON对象，不能将整份JSON编码为字符串；请提交包含clock、actors、facility等字段的完整对象，不是局部补丁')
    validate_selected_step(configuration,basis)
    scenario_constraints.validate(configuration,basis.get('fixed_parameters'))
    if bool(configuration.get('campaign_scope')) != (basis.get('force_scope','phase')=='campaign'):
        raise ValueError('配置必须遵守所选会战/阶段范围；不能静默增减参战序列或绕过到场核验')
    selected_window=basis.get('campaign_window')
    submitted_window=(configuration.get('campaign_scope') or {}).get('window')
    if selected_window!=submitted_window:
        raise ValueError('配置必须保留用户所选会战窗口，不能移除、替换或注入另一窗口')
    if basis.get('termination_mode') is not None and configuration.get('goal',{}).get('termination_mode')!=basis['termination_mode']:
        raise ValueError('结束方式须遵守启动页选择；按目标完成不能改成截止轮数自动结束')
    validate_required_models(configuration, basis.get('required_models', []))
    template=(basis.get('configuration_template') or {}).get('goal') or {}
    if 'team' in template and (not isinstance(configuration,dict) or not isinstance(configuration.get('goal'),dict)
                               or 'team' not in configuration['goal']):
        raise ValueError('新建配置必须显式填写目标方goal.team；不能省略后静默按红方判定')


def validate_required_models(configuration, required_models):
    from gentactix import support_dynamics,supply_schedule,movement_feedback,combat_effects
    if support_dynamics.VERSION in required_models and support_dynamics.PERSONNEL_VERSION in required_models:
        raise ValueError('两种时间粮秣模型不能同时要求')
    if combat_effects.DENSITY_VERSION in required_models and combat_effects.CONTINUOUS_DENSITY_VERSION in required_models:
        raise ValueError('动态密度版本必须明确选择一种')
    for model in required_models:
        if model in (combat_effects.DENSITY_VERSION,combat_effects.CONTINUOUS_DENSITY_VERSION):
            if not configuration.get('fire_dynamics'):raise ValueError('用户要求动态密度火力过程：fire_dynamics缺失，不能回退轮初密度')
            combat_effects.validate_dynamics(configuration['fire_dynamics'])
            if model==combat_effects.CONTINUOUS_DENSITY_VERSION and configuration['fire_dynamics']['version']!=model:
                raise ValueError('连续压制版本须遵守用户明确选择，不能降级')
            continue
        if model==combat_effects.ACCOUNTING_VERSION:
            if not configuration.get('fire_accounting'):raise ValueError('用户要求分类炮弹计量：fire_accounting缺失，不能回退通用弹药双约束')
            combat_effects.validate_accounting(configuration['fire_accounting'])
            continue
        if model==movement_feedback.VERSION:
            if not configuration.get('movement_feedback'):raise ValueError('用户要求movement-feedback-1运动反馈：公共条件movement_feedback缺失，不能回退名义机动')
            movement_feedback.validate_config(configuration['movement_feedback'])
            continue
        if model==supply_schedule.VERSION:
            if not configuration.get('supply_schedule'):raise ValueError('用户要求定时补给：公共条件supply_schedule缺失')
            supply_schedule.validate_parameters(configuration)
            continue
        if model in support_dynamics.VERSIONS:
            cfg=(configuration or {}).get('support_dynamics')
            if not cfg:
                raise ValueError('用户显式要求'+model+'：公共条件support_dynamics缺失；不能回退每回合耗粮')
            support_dynamics.validate_config(cfg)
            if cfg['version']!=model:raise ValueError('时间粮秣模型须遵守用户显式选择：'+model)
            continue
        if model != 'formation-ferry-1':
            raise ValueError('未支持的必需模型：' + str(model))
        crossing = ((configuration or {}).get('facility') or {}).get('crossing_model') or {}
        if (crossing.get('ferry') or {}).get('version') != model:
            raise ValueError('用户显式要求' + model + '：公共条件facility.crossing_model.ferry缺失；'
                             '完整配置模式须在全部configuration中填写，分片模式须在globals阶段填写后再进入单位分片')


def prepare_required_models(basis, required_models):
    """Expose required input shapes; all unknown capacities stay null."""
    from gentactix import crossings,ferries,support_dynamics,supply_schedule,movement_feedback,combat_effects
    if support_dynamics.VERSION in required_models and support_dynamics.PERSONNEL_VERSION in required_models:
        raise ValueError('两种时间粮秣模型不能同时要求')
    if combat_effects.DENSITY_VERSION in required_models and combat_effects.CONTINUOUS_DENSITY_VERSION in required_models:
        raise ValueError('动态密度版本必须明确选择一种')
    basis['required_models']=copy.deepcopy(required_models)
    for model in required_models:
        if model in (combat_effects.DENSITY_VERSION,combat_effects.CONTINUOUS_DENSITY_VERSION):
            prior=basis['configuration_template'].get('fire_dynamics') or {}
            selected=(prior.get('version') if model==combat_effects.DENSITY_VERSION and prior.get('version')==combat_effects.CONTINUOUS_DENSITY_VERSION else model)
            basis['configuration_template']['fire_dynamics']={**prior,'version':selected,
                'assumption':prior.get('assumption') or '待说明同批现存人员与同坐标格共享密度的估计依据；连续压制版另保留时间余量，不代表历史标定或完整时间收敛。'}
            continue
        if model==combat_effects.ACCOUNTING_VERSION:
            basis['configuration_template'].setdefault('fire_accounting',{
                'version':model,'assumption':'显式聚合计量假设：通用工作量代表直射轻武器弹药；炮击／压制按分类实弹扣账，未经口径、炮班操作及历史弹耗标定。'})
            continue
        if model==movement_feedback.VERSION:
            basis['configuration_template'].setdefault('movement_feedback',{
                'version':movement_feedback.VERSION,'assumption':'待说明采用既有原生通信／机动／疲劳约束，系数未经历史或生理标定。'})
            continue
        if model==supply_schedule.VERSION:
            template=basis['configuration_template']
            template.setdefault('support_dynamics',{'version':support_dynamics.VERSION,**{k:None for k in support_dynamics.LIMITS},'assumption':'待明确按时耗粮估计。'})
            template.setdefault('supply_schedule',{'version':supply_schedule.VERSION,'period_seconds':3600,
                'passive_work_per_hour':None,'resupply_work_per_hour':None,'convoy_speed_kph':None,'loading_hours':None,
                'warehouse_tons_per_hour':{team+'-historical-supply':None for team in ((basis.get('interaction') or {}).get('active_teams') or template['support'])},
                'assumption':'待说明周期供给、已运行运输管线、未模拟具名车队在途和未经历史标定的假设。'})
            continue
        if model in support_dynamics.VERSIONS:
            template=basis['configuration_template']
            if (template.get('support_dynamics') or {}).get('version')!=model:
                template['support_dynamics']={
                    'version':model,**{k:None for k in support_dynamics.limits(model)},
                    'assumption':'待说明按时耗粮与缺粮影响的估计依据及未标定边界。'}
            continue
        if model!=ferries.VERSION:raise ValueError('未支持的必需模型：'+str(model))
        template=basis['configuration_template']
        crossing=template['facility'].setdefault('crossing_model',crossings.configuration_template('待说明有限河线、岸点与通行能力估计。'))
        crossing.setdefault('ferry',ferries.configuration_template())
        template['rules']['bridge_enabled']=True


def fixed_parameter_catalogue(basis):
    """UI-only field metadata; never duplicate this catalogue in model context."""
    rows=scenario_constraints.fields(basis['configuration_template'],basis['actors'])
    seen={tuple(r['path']) for r in rows}
    for model in ('time-sustainment-1','personnel-rations-1','scheduled-supply-1','formation-ferry-1'):
        variant={'configuration_template':copy.deepcopy(basis['configuration_template']),
                 'interaction':copy.deepcopy(basis.get('interaction'))}
        prepare_required_models(variant,[model])
        for field in scenario_constraints.fields(variant['configuration_template'],basis['actors']):
            if tuple(field['path']) not in seen:
                rows.append({**field,'required_models':[model]});seen.add(tuple(field['path']))
    return rows


class ConfigurationPatchError(ValueError):
    """Bounded Native tool feedback; no values or unrelated state are echoed."""
    def __init__(self,path,base,patch):
        is_object=isinstance(patch,dict);allowed=sorted(base)
        unexpected=sorted(set(patch)-set(base)) if is_object else []
        self.input_error={'code':'unknown_configuration_field' if is_object else 'expected_configuration_object',
            'path':list(path),'expected_type':'object','allowed_fields':allowed[:32],
            'allowed_fields_total':len(allowed),'unexpected_fields':[k[:160] for k in unexpected[:16]],
            'unexpected_fields_total':len(unexpected)}
        location='.'.join(path) or 'configuration'
        super().__init__('配置字段越界：'+location+('；不允许字段='+str(self.input_error['unexpected_fields'])
                         if is_object else '；此处须为模板中的对象'))


def _merge_known(base, patch, path=()):
    if path==('partitions','groups'):
        if not isinstance(patch,dict):raise ValueError('分队分组必须是按父历史ID索引的对象')
        return copy.deepcopy(patch)  # Full identity/allocation checks stay in the domain validator.
    if isinstance(base,dict):
        if path==('campaign',) and isinstance(patch,dict) and 'objective_policy' in patch:
            base={**base,'objective_policy':base.get('objective_policy')}
        if len(path)==3 and path[:2]==('campaign','arrivals') and isinstance(patch,dict):
            for key in ('parts','event_kind','reference_id'):
                if key in patch:base={**base,key:base.get(key)}
        if not path and isinstance(patch,dict) and base.get('format')==historical_operations.FORMAT:
            base={**base,**{key:base.get(key) for key in OPTIONAL_GLOBAL_FIELDS if key in patch}}
        if path==('facility',) and isinstance(patch,dict):
            base={**base,**{k:base.get(k) for k in ('crossing_model','crossing_network') if k in patch}}
        if path==('facility','crossing_model') and isinstance(patch,dict) and 'ferry' in patch:
            base={**base,'ferry':base.get('ferry')}
        if not isinstance(patch,dict) or set(patch)-set(base):
            raise ConfigurationPatchError(path,base,patch)
        result=copy.deepcopy(base)
        for key,value in patch.items():result[key]=_merge_known(base[key],value,path+(key,))
        return result
    return copy.deepcopy(patch)


class HistoricalAssembly:
    def __init__(self,basis,cancel_check=None,on_change=None):
        if not basis.get('ready') or not basis.get('configuration_template'):
            raise ValueError('缺少可配置的历史基础')
        self.id=uuid.uuid4().hex
        self.basis=copy.deepcopy(basis)
        self.configuration=copy.deepcopy(basis['configuration_template'])
        self.ids=list(self.configuration['actors'])
        self.revision=0;self.global_ready=False;self.filled=set();self.validation=None;self.closed=False
        self.last_validation_error=None
        self.cancel_check=cancel_check;self.lock=threading.RLock()
        self.audit=[]
        self.on_change=on_change

    def export_state(self):
        """Host-owned validated data, never messages or a runnable battle."""
        with self.lock:
            basis={k:copy.deepcopy(v) for k,v in self.basis.items() if k not in
                ('fixed_parameter_fields','pending_configurations','pending_assemblies','configuration_alternatives','available_campaign_windows')}
            return {'format':STATE_FORMAT,'id':self.id,'basis':basis,
                'configuration':copy.deepcopy(self.configuration),'revision':self.revision,
                'global_ready':self.global_ready,'filled':[i for i in self.ids if i in self.filled],
                'audit':copy.deepcopy(self.audit),'validation':copy.deepcopy(self.validation)}

    @property
    def parts(self):return [f'actors:{i}' for i in range((len(self.ids)+PAGE_SIZE-1)//PAGE_SIZE)]

    def assigned(self,part):
        if part in ('globals','final'):return []
        if part not in self.parts:raise ValueError('想定配置分片不存在')
        index=int(part.split(':')[1])*PAGE_SIZE
        return self.ids[index:index+PAGE_SIZE]

    def context(self,part,*,read_only=False):
        self.assigned(part)
        return {'scenario_composer':{'kind':'historical_operation','assembly_id':self.id,'part':part,'read_only':read_only}}

    def receipt(self):
        return {'revision':self.revision,'configuration_hash':missions.digest(self.configuration),
                'completed_actors':len(self.filled),'total_actors':len(self.ids),
                'global_ready':self.global_ready,'status':'configuration_draft; no_live_battle_write'}

    def _view(self,part):
        ids=self.assigned(part)
        actors=[copy.deepcopy(r) for r in self.basis['actors'] if r['id'] in ids]
        phase=copy.deepcopy(self.basis['phase'])
        used=set()
        def visit(value):
            if isinstance(value,dict):
                if isinstance(value.get('source_id'),str):used.add(value['source_id'])
                for v in value.values():visit(v)
            elif isinstance(value,list):
                for v in value:visit(v)
        visit(actors);visit(phase)
        globals_={k:copy.deepcopy(v) for k,v in self.configuration.items() if k!='actors'}
        window=(globals_.get('campaign_scope') or {}).pop('window',None)
        counts={team:sum(r['team']==team for r in self.basis['actors']) for team in ('red','blue')}
        view={'ok':True,'workflow':'staged_historical_configuration','part':part,**self.receipt(),
              'battle':self.basis['battle'],'phase':phase,'execution_window':self.basis.get('execution_window'),
              'interaction':copy.deepcopy(self.basis.get('interaction')),
              'force_scope':self.basis.get('force_scope','phase'),
              'organization_coverage':[copy.deepcopy(r) for r in self.basis.get('organization_coverage',[])
                  if part in ('globals','final') or set(r['selected_descendant_ids']).intersection(ids)],
              'assigned_actor_ids':ids,'actor_counts':counts,'actors':actors,
              'sources':{k:copy.deepcopy(v) for k,v in self.basis.get('sources',{}).items() if k in used},
              'geo_references':copy.deepcopy(self.basis.get('geo_references',[])[:24]),
              'geo_reference_total':len(self.basis.get('geo_references',[])),
              'goal_semantics':copy.deepcopy(self.basis.get('goal_semantics',{})),
              'time_step_constraint':copy.deepcopy(self.basis.get('time_step_constraint')),
              'required_models':copy.deepcopy(self.basis.get('required_models', [])),
              'fixed_parameters':scenario_constraints.view(self.basis.get('fixed_parameters'),ids,final=part=='final'),
              'movement_rule':'行军上限=速度km/h×回合小时数÷terrain_factor；1为基准，>1降低可达距离，<1提高可达距离。通信、疲劳和资源仍会限制实际机动。',
              'readonly_binding':'身份和来源由宿主固定；仅通过update_scenario_configuration填写本片草稿。最终返回revision、configuration_hash、explanation，不重复完整配置。'}
        support=self.configuration.get('support_dynamics') or {}
        if support.get('version')=='personnel-rations-1':
            view['food_loading_contract']={k:copy.deepcopy(support[k]) for k in
                ('food_kg_per_work','carried_kg_per_committed_person','ration_kg_per_person_day')}
            view['food_loading_contract']['instruction']=('food_kg_per_work已包含food_mass_share，不能重复乘除质量份额。'
                '初态food工作量=估计粮食kg/food_kg_per_work；容量工作量=人数×kg/人携行容量/food_kg_per_work。'
                '初态分队另按各自resource_scale换算；不得新增food_kg权威库存。')
        if window:
            w=window['definition']
            view['readonly_campaign_window']={k:copy.deepcopy(window[k]) for k in ('id','version','definition_hash')}
            view['readonly_campaign_window'].update(label=w['label'],bounds=copy.deepcopy(w['bounds']),
                historical_initial=copy.deepcopy(w['historical_initial']),
                phase_ids=list(w['phase_ids']),limitations=w['limitations'],
                instruction='完整只读窗口由宿主保留；patch中省略campaign_scope.window。不得改窗口、史料版本、起点和规划边界；各片window_scope的缺载部署仍须显式估计。')
            if part in ('globals','final'):
                view['readonly_campaign_window']['sectors']=copy.deepcopy(w['sectors'])
                if 'opening_command' in w:
                    view['readonly_campaign_window']['opening_command']=copy.deepcopy(w['opening_command'])
                    view['readonly_campaign_window']['instruction']+=(
                        ' 本窗口显式采用起始来源阶段的指挥关系；填写initial_command.assumption说明采用依据。'
                        '关系身份由宿主冻结，不是零时实际发令证据，后续日期不自动转隶。')
            if 'parameter_estimates' in w:
                estimates=w['parameter_estimates']
                view['readonly_campaign_window']['parameter_estimates']={k:copy.deepcopy(estimates[k])
                    for k in ('version','historically_calibrated','assumption','area')}
                if 'goal_regions' in estimates:
                    view['readonly_campaign_window']['parameter_estimates']['goal_regions']=copy.deepcopy(estimates['goal_regions'])
                if 'global_priors' in estimates:
                    view['readonly_campaign_window']['review_ready_global_priors']=True
                    view['readonly_campaign_window']['global_prior_instruction']='公共配置已有明确估计的数值基线。读取后仅提交与用户要求不同的字段；若无需数值修改，只更新assumptions写明复核范围。不可口头声称已保存，仍须取得update工具有效revision；不要重复整份公共JSON。单位人数与部署仍由各分片填写。'
        if part in ('globals','final'):view['objective_guidance']=copy.deepcopy(self.basis.get('objective_guidance'))
        if part=='globals':
            view['optional_patch_fields']=list(OPTIONAL_GLOBAL_FIELDS)
            if 'campaign' in globals_:
                view['actor_index']=[{k:r[k] for k in ('id','name','team','echelon')} for r in self.basis['actors']]
            view['configuration']={k:v for k,v in globals_.items() if k not in ('format','phase_id')}
            view['readonly_identity']={k:globals_[k] for k in ('format','phase_id')}
            # Known position references inform theater selection without loading
            # the full OOB or implying that modern area centers are unit positions.
            positions=[r['facts']['position']['value'] for r in self.basis['actors'] if r['facts']['position']['value']]
            view['known_position_references']=[copy.deepcopy(p) for p in positions[:16]]
            view['known_position_reference_total']=len(positions)
            if positions:
                view['known_reference_extent']={'min_lat':min(p['lat'] for p in positions),'max_lat':max(p['lat'] for p in positions),
                    'min_lng':min(p['lng'] for p in positions),'max_lng':max(p['lng'] for p in positions),
                    'max_uncertainty_km':max(p.get('uncertainty_km',0) for p in positions),
                    'kind':'all_source_position_reference_bounds; not_surveyed_unit_deployments'}
        elif part=='final':
            view['configuration_summary']={'area':globals_['area'],'clock':globals_['clock'],'goal':globals_['goal']}
            view['missing_actor_ids']=[i for i in self.ids if i not in self.filled][:8]
        else:
            view['configuration']={'actors':{i:copy.deepcopy(self.configuration['actors'][i]) for i in ids}}
            view['readonly_global_configuration']=globals_
            priors=((window or {}).get('definition',{}).get('parameter_estimates') or {}).get('actors',{})
            if ids and all('input_prior' in priors.get(i,{}) for i in ids):view['review_ready_actor_priors']=True
        return view

    def _update(self,part,args):
        ids=self.assigned(part);patch=None;normalized=None
        try:
            if set(args)!={'revision','patch'} or type(args['revision']) is not int or args['revision']!=self.revision:
                raise ValueError('草稿版本已变化，请重新读取当前revision')
            patch=args['patch']
            if isinstance(patch,str):
                # Some Messages-compatible models encode this object once more.
                # Decode exactly once, then enforce the SAME scope and schema.
                patch=json.loads(patch);normalized='json_object_string'
            if not isinstance(patch,dict) or not patch:raise ValueError('patch须为非空JSON对象，不能是数组、null或空值')
            if part=='globals':
                if self.filled:raise ValueError('单位配置开始后公共条件已锁定')
                if set(patch)-set(self.configuration)-set(OPTIONAL_GLOBAL_FIELDS) or set(patch)&{'actors','format','phase_id'}:
                    raise ValueError('总配置不能改写单位或只读历史身份')
            elif part=='final':raise ValueError('最终复核会话只读，不能更改配置')
            else:
                if not self.global_ready:raise ValueError('先完成公共条件配置')
                if set(patch)!={'actors'} or not isinstance(patch['actors'],dict) or set(patch['actors'])!=set(ids):
                    raise ValueError('只能完整提交本片已分配的真实单位，不能增删或访问其他分片')
            json.dumps(patch,allow_nan=False)
            candidate=_merge_known(self.configuration,patch)
            validate_build_constraints(candidate, self.basis)
            historical_operations._validate(self.basis['initial'],candidate,actor_ids=ids)
            previous=(self.configuration,self.revision,self.validation,self.global_ready,self.filled.copy(),len(self.audit),self.last_validation_error)
            self.configuration=candidate;self.revision+=1;self.validation=None;self.last_validation_error=None
            if part=='globals':self.global_ready=True
            else:self.filled.update(ids)
            self.audit.append({'part':part,'revision':self.revision,'actors':ids,
                               'configuration_hash':missions.digest(self.configuration)})
            try:
                if self.on_change:self.on_change(self)
            except Exception:
                self.configuration,self.revision,self.validation,self.global_ready,self.filled,length,self.last_validation_error=previous
                del self.audit[length:]
                raise
            return {'ok':True,'updated':True,**self.receipt(),'normalized_patch':normalized,'part_complete':True,
                    'scope':'candidate_configuration_only; not_live_load','next_action':'finish',
                    'instruction':'本片参数已保存并通过局部校验。现在只返回revision、configuration_hash、explanation结束本片；不要重复更新。完整校验和实际AFSIM装载由后续阶段处理。'}
        except (ValueError,KeyError,TypeError) as exc:
            input_error = ({'code':'encoded_patch_invalid_json','line':exc.lineno,
                            'column':exc.colno,'offset':exc.pos}
                           if isinstance(exc,json.JSONDecodeError) else
                           copy.deepcopy(exc.input_error) if isinstance(exc,ConfigurationPatchError) else None)
            supplied=patch.get('actors',{}) if isinstance(patch,dict) else {}
            supplied=supplied if isinstance(supplied,dict) else {}
            return {'ok':True,'updated':False,'error':str(exc),**self.receipt(),
                    **({'food_loading':copy.deepcopy(exc.food_loading)} if hasattr(exc,'food_loading') else {}),
                    **({'fixed_parameter_conflicts':copy.deepcopy(exc.conflicts)} if isinstance(exc,scenario_constraints.FixedParameterConflict) else {}),
                    **({'input_error':input_error} if input_error else {}),
                    'expected_patch_top_level':['actors'] if ids else sorted((set(self.configuration)|set(OPTIONAL_GLOBAL_FIELDS))-{'actors','format','phase_id'}),
                    'required_actor_ids':ids,'missing_actor_ids':[i for i in ids if i not in supplied],
                    'unexpected_actor_ids':[i for i in supplied if i not in ids],
                    'instruction':(('粮食质量换算已包含质量份额，不能重复乘除；按food_loading核对本单位库存和冻结容量，草稿未改变。' if hasattr(exc,'food_loading') else '')+
                        ('patch被字符串化且内部JSON解析失败。请直接提交JSON对象，避免手工转义、拼接字符串；草稿未改变，沿用当前revision。' if isinstance(exc,json.JSONDecodeError) else
                        '按input_error.path核对该对象及allowed_fields，只修正不允许的键或对象形状；数量截断时重新读取模板。草稿未改变，仍使用返回的revision。' if isinstance(exc,ConfigurationPatchError) else '')+
                        ('patch直接包含actors对象且覆盖required_actor_ids全部ID；不要加configuration、assigned_actor_ids等包装。'
                        '每个单位使用get_scenario_basis返回的完整本片模板，修正后仍使用当前revision。' if ids else
                        'patch直接包含可编辑公共条件；不要添加configuration、actors、format或phase_id。'))}

    def _validate(self,part,args):
        try:
            if args:raise ValueError('分片校验直接读取宿主草稿，不传完整configuration')
            validate_build_constraints(self.configuration, self.basis)
            if part=='final':
                if not self.global_ready or self.filled!=set(self.ids):raise ValueError('公共条件或历史单位尚未全部填写')
                from . import afsim_world
                world=historical_operations.initial(self.basis['initial'],self.configuration)
                scene=afsim_world.compile_scene(world,[],.001,native_rules=True)
                self.validation={**self.receipt(),'definition_hash':world['mission']['definition_hash'],
                                 'entities':len(scene['entities'])}
                self.last_validation_error=None
                from gentactix import sustainment, resource_readiness
                return {'ok':True,'valid':True,**copy.deepcopy(self.validation),
                        'sustainment':sustainment.assess(world),
                        'resource_readiness':resource_readiness.assess(world),
                        'scope':'complete_configuration_and_native_template; not_live_load'}
            historical_operations._validate(self.basis['initial'],self.configuration,actor_ids=self.assigned(part))
            return {'ok':True,'valid':True,**self.receipt(),'scope':'global_contract_only' if part=='globals' else 'assigned_actors_only'}
        except (ValueError,KeyError,TypeError) as exc:
            if part=='final':self.last_validation_error=str(exc)
            return {'ok':True,'valid':False,'error':str(exc),**self.receipt(),
                    **({'food_loading':copy.deepcopy(exc.food_loading)} if hasattr(exc,'food_loading') else {})}

    def tool(self,part,tool,args,*,read_only=False):
        with self.lock:
            if self.closed or self.cancel_check and self.cancel_check():raise ValueError('想定配置操作已结束或取消')
            self.assigned(part)
            if tool=='get_scenario_basis':
                if args:raise ValueError('分片由宿主分配，不能请求其他分片')
                return {**self._view(part),'write_allowed':not read_only,
                        'next_action':'return_receipt_only' if read_only else 'fill_assigned_configuration'}
            if read_only and tool=='update_scenario_configuration':raise ValueError('回执复核会话只读，不得修改已校验草稿')
            if tool=='update_scenario_configuration':return self._update(part,args)
            if tool=='validate_scenario_configuration':return self._validate(part,args)
            raise ValueError('分片配置不支持该工具')

    def finish(self,receipt):
        with self.lock:
            if not self.validation and self.last_validation_error:
                raise ValueError('最终校验未通过：'+self.last_validation_error)
            if (self.closed or not self.validation or self.validation['revision']!=self.revision
                    or any(receipt.get(k)!=self.validation[k] for k in ('revision','configuration_hash'))):
                raise ValueError('最终校验回执缺失或版本不一致')
            return copy.deepcopy(self.configuration)


def create(basis,*,cancel_check=None,on_change=None):
    assembly=HistoricalAssembly(basis,cancel_check,on_change)
    with _lock:_registry[assembly.id]=assembly
    return assembly


def inspect_state(state,*,cancel_check=None,on_change=None):
    """Check provenance and write structure without accepting input parameters.

    A legacy failed final may contain inputs today's domain validator rejects.
    Its candidate can be inspected for explicit revision, never resumed or loaded
    through this function. It is deliberately not registered as a tool context.
    """
    keys={'format','id','basis','configuration','revision','global_ready','filled','audit','validation'}
    if (not isinstance(state,dict) or set(state)!=keys or state['format']!=STATE_FORMAT
            or not isinstance(state['id'],str) or not re.fullmatch(r'[a-f0-9]{32}',state['id'])):
        raise ValueError('分片检查点版本或身份非法')
    value=HistoricalAssembly(state['basis'],cancel_check,on_change)
    historical_operations.historical_initial.restore(value.basis['initial'])
    expected=historical_operations.partition(value.basis['initial'],value.basis.get('force_scope','phase'),window=value.basis.get('campaign_window'))
    if value.ids!=expected:raise ValueError('分片模板的历史单位身份或顺序已改变')
    configuration=state['configuration'];revision=state['revision'];audit=state['audit'];filled=state['filled']
    if (type(revision) is not int or revision<0 or not isinstance(audit,list) or revision!=len(audit)
            or type(state['global_ready']) is not bool or not isinstance(filled,list)
            or len(filled)!=len(set(filled)) or not set(filled)<=set(value.ids)):
        raise ValueError('分片检查点版本号、写入记录或完成单位不一致')
    seen=set();global_ready=False
    for index,row in enumerate(audit,1):
        if not isinstance(row,dict) or set(row)!={'part','revision','actors','configuration_hash'} or row['revision']!=index:
            raise ValueError('分片检查点写入记录不连续')
        if row['part']=='globals':
            if seen:raise ValueError('单位开始后不能重写公共参数')
            global_ready=True
        elif not global_ready or row['part'] not in value.parts:raise ValueError('分片写入先后或范围非法')
        if row['actors']!=value.assigned(row['part']) or not re.fullmatch(r'[a-f0-9]{64}',str(row['configuration_hash'])):
            raise ValueError('分片写入单位或配置摘要非法')
        seen.update(row['actors'])
    if seen!=set(filled) or global_ready!=state['global_ready']:
        raise ValueError('分片完成标记不能超过真实校验写入记录')
    if not isinstance(configuration,dict) or set(configuration.get('actors',{}))!=set(value.ids):
        raise ValueError('分片检查点不能丢失或新增历史单位')
    for identity in set(value.ids)-seen:
        if configuration['actors'][identity]!=value.configuration['actors'][identity]:
            raise ValueError('未校验单位已被改动，不能当作已保存输入')
    if global_ready:
        if audit[-1]['configuration_hash']!=missions.digest(configuration):raise ValueError('分片配置与最后有效写入不一致')
    elif configuration!=value.configuration or state['validation'] is not None:
        raise ValueError('尚未校验公共条件的草稿只能保留原输入模板')
    value.id=state['id'];value.configuration=copy.deepcopy(configuration);value.revision=revision
    value.audit=copy.deepcopy(audit);value.filled=seen;value.global_ready=global_ready
    return value


def restore(state,*,cancel_check=None,on_change=None):
    """Revalidate a host checkpoint; unknown/unfilled values stay unchanged."""
    value=inspect_state(state,cancel_check=cancel_check,on_change=on_change)
    if value.global_ready:
        validate_build_constraints(value.configuration,value.basis)
        historical_operations._validate(value.basis['initial'],value.configuration,actor_ids=list(value.filled))
    if state['validation'] is not None:
        if value.filled!=set(value.ids):raise ValueError('未完成单位不能冒充最终校验')
        checked=value._validate('final',{})
        if not checked.get('valid') or value.validation!=state['validation']:raise ValueError('分片最终校验回执已失效')
    with _lock:
        if value.id in _registry:raise ValueError('该分片草稿仍在使用，不能并发恢复')
        _registry[value.id]=value
    return value


def get(identity):
    with _lock:assembly=_registry.get(identity)
    if assembly is None:raise ValueError('想定配置操作不存在或已结束')
    return assembly


def close(identity):
    with _lock:assembly=_registry.pop(identity,None)
    if assembly:
        with assembly.lock:assembly.closed=True
