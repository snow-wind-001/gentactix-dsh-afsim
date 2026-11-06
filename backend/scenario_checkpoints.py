"""Host configuration checkpoints in the existing draft store; no battle executor."""
import copy
import re
import time
from gentactix import missions,campaign_windows

FORMAT='historical-assembly-checkpoint-1'


def new_work(instruction,execution_backend):
    if execution_backend not in ('afsim','narrative') or not isinstance(instruction,str) or len(instruction)>4000:
        raise ValueError('分片续接的输入或执行引擎非法')
    return {'instruction':instruction,'execution_backend':execution_backend,'stages':[],
        'bindings':{},'part_bindings':{},'coordinator':None,'attempts':[],'runs':[],
        'recoveries':0,'status':'running','failed_part':None,'last_error':'',
        'operation_id':None,'loaded_draft_id':None,'previous_meta':[],'explanations':[]}


def save(assembly,work):
    from . import scenario_builder
    record={'id':assembly.id,'kind':'historical_assembly','format':FORMAT,
        'state':assembly.export_state(),'work':copy.deepcopy(work),'saved_at':time.time()}
    record['checkpoint_hash']=missions.digest(record)
    scenario_builder._save_draft(record,None)
    return record


def read(identity):
    from . import scenario_builder
    record=scenario_builder.load(identity)
    if (record.get('kind')!='historical_assembly' or record.get('format')!=FORMAT
            or set(record)!={'id','kind','format','state','work','saved_at','checkpoint_hash'}
            or record['id']!=identity or record['state'].get('id')!=identity
            or record['checkpoint_hash']!=missions.digest({k:v for k,v in record.items() if k!='checkpoint_hash'})):
        raise ValueError('分片检查点版本、摘要或身份不一致，不能续接')
    work=record['work'];keys=set(new_work('','narrative'))
    if not isinstance(work,dict) or set(work)!=keys:raise ValueError('分片工作记录不完整')
    new_work(work['instruction'],work['execution_backend'])
    if (work['status'] not in ('running','interrupted','configured','loaded')
            or type(work['recoveries']) is not int or work['recoveries']<0
            or not isinstance(work['stages'],list) or not isinstance(work['bindings'],dict)
            or not isinstance(work['part_bindings'],dict) or not isinstance(work['attempts'],list)
            or not isinstance(work['runs'],list)):
        raise ValueError('分片工作状态或原生会话索引非法')
    prefix='gentactix-unit-scenario-'+identity+'-'
    for sid,binding in work['bindings'].items():
        if (not isinstance(sid,str) or not sid.startswith(prefix) or not isinstance(binding,dict)
                or binding.get('session_id')!=sid):raise ValueError('分片原生会话不属于此检查点')
    if (work['coordinator'] is not None and work['coordinator'] not in work['bindings']
            or any(sid not in work['bindings'] for sid in work['part_bindings'].values())):
        raise ValueError('分片原生父子会话绑定缺失')
    return record


def restore(identity,*,cancel_check=None):
    from . import scenario_assembly
    record=read(identity)
    if record['work']['loaded_draft_id']:raise ValueError('该分片草稿已完成装载，请使用已生成的想定')
    assembly=scenario_assembly.restore(record['state'],cancel_check=cancel_check)
    try:
        _validate_stages(assembly,record['work'])
    except Exception:
        scenario_assembly.close(assembly.id);raise
    return assembly,copy.deepcopy(record['work'])


def _validate_stages(assembly,work):
    parts=['globals',*assembly.parts,'final'];stages=work['stages']
    if len(stages)>len(parts):raise ValueError('分片完成记录超出配置范围')
    for index,stage in enumerate(stages):
        if not isinstance(stage,dict) or stage.get('part')!=parts[index] or stage.get('session_id') not in work['bindings']:
            raise ValueError('分片完成记录或原生会话不连续')
        receipt=assembly.validation if stage['part']=='final' else next((r for r in assembly.audit
            if r['part']==stage['part'] and r['revision']==stage.get('revision')),None)
        if not receipt or any(stage.get(k)!=receipt[k] for k in ('revision','configuration_hash')):
            raise ValueError('分片完成回执没有对应的有效工具写入')
    if work['failed_part'] not in (None,*parts):raise ValueError('待续接分片不存在')


def can_revise_configuration(record):
    """A UI affordance, not parameter admission or a successful final receipt."""
    state=record['state'];work=record['work']
    from .scenario_assembly import PAGE_SIZE
    return (work['status']=='interrupted' and work['failed_part']=='final'
        and not work['loaded_draft_id'] and state['validation'] is None and state['global_ready']
        and set(state['filled'])==set(state['configuration']['actors'])
        and len(work['stages'])==1+(len(state['configuration']['actors'])+PAGE_SIZE-1)//PAGE_SIZE)


def revision_record(identity):
    """Read an immutable failed source; all revised values need full admission."""
    from . import scenario_assembly,scenario_builder
    record=read(identity)
    with scenario_builder._active_lock:
        active=record['work']['operation_id'] in scenario_builder._active
    if active or not can_revise_configuration(record):
        raise ValueError('仅可显式修订已结束且全部单位已写入、最终校验失败的配置；原草稿不改动')
    candidate=scenario_assembly.inspect_state(record['state'])
    _validate_stages(candidate,record['work'])
    return record


def summary(record):
    state=record['state'];work=record['work'];basis=state['basis'];parameters=state['configuration']
    return {'id':record['id'],'execution_backend':work['execution_backend'],
        'time_step':parameters['clock']['time_step'],'termination_mode':parameters['goal'].get('termination_mode','deadline'),
        'required_models':basis.get('required_models',[]),'fixed_count':len((basis.get('fixed_parameters') or {}).get('values',[])),
        'validated_actors':len(state['filled']),'total_actors':len(parameters['actors']),
        'completed_stages':len(work['stages']),'failed_part':work['failed_part'],
        'status':work['status'],'saved_at':record['saved_at'],'last_error':work['last_error'],
        'can_rebuild_failed_session':can_rebuild_failed_session(record),
        'can_revise_configuration':can_revise_configuration(record)}


def can_rebuild_failed_session(record):
    work=record['work'];state=record['state'];part=work['failed_part']
    if work['status']!='interrupted' or not isinstance(part,str) or not re.fullmatch(r'actors:[0-9]+',part):return False
    from .scenario_assembly import PAGE_SIZE
    start=int(part.split(':')[1])*PAGE_SIZE
    assigned=list(state['configuration']['actors'])[start:start+PAGE_SIZE]
    return bool(assigned) and not set(assigned).intersection(state['filled'])


def mark_loaded(identity,draft_id):
    from . import scenario_builder
    record=read(identity)
    if record['work']['loaded_draft_id']:return
    record['work'].update(status='loaded',loaded_draft_id=draft_id,last_error='',failed_part=None)
    record.pop('checkpoint_hash');record['saved_at']=time.time();record['checkpoint_hash']=missions.digest(record)
    scenario_builder._save_draft(record,None)


def pending(snapshot,*,force_scope=None,window=None):
    from . import scenario_builder
    rows=[]
    for path in scenario_builder.directory().glob('*.json'):
        try:
            record=read(path.stem);state=record['state'];basis=state['basis']
            if (record['work']['loaded_draft_id'] or basis['initial']!=snapshot
                    or force_scope is not None and basis.get('force_scope','phase')!=force_scope
                    or not campaign_windows.equivalent_pins(basis.get('campaign_window'),window)):continue
            row=summary(record)
            with scenario_builder._active_lock:row['active']=record['work']['operation_id'] in scenario_builder._active
            rows.append(row)
        except (ValueError,KeyError,TypeError,OSError):continue
    return sorted(rows,key=lambda r:r['saved_at'],reverse=True)[:20]
