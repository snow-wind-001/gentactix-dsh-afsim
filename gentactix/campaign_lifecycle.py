"""Continuous stage milestones over one physical world and the existing goal DAG.

This version schedules goal eligibility, not unit participation or refits. A
stage transition never copies worlds, creates actors or changes physical stock.
"""
import copy
import json
import re

VERSION='campaign-lifecycle-1'


def definition(world):
    return world.get('mission',{}).get('definition',{}).get('campaign_lifecycle')


def validate_config(value,world,plan=None):
    from . import campaign_plan as goals, historical_links
    goals._fields(value,{'version','phases','finish_policy','assumption'},'单世界阶段定义')
    if value['version']!=VERSION:raise ValueError('单世界阶段版本不支持')
    goals._text(value['assumption'],'阶段估计依据')
    if value['finish_policy'] not in ('all_phases','goal_outcomes'):raise ValueError('阶段终止策略须显式选择all_phases或goal_outcomes')
    plan=plan or world.get('mission',{}).get('definition',{}).get('campaign_plan')
    if not plan:raise ValueError('单世界阶段须绑定宿主目标图，不隐式替换旧局目标')
    phases=value['phases']
    if not isinstance(phases,list) or not 2<=len(phases)<=256:raise ValueError('阶段须为2至256项有序定义')
    nodes={n['id']:n for n in plan['nodes']};owners={};names=set()
    for index,row in enumerate(phases):
        goals._fields(row,{'id','label','goal_ids','minimum_duration_seconds','operation_ids','assumption'},'阶段')
        if not isinstance(row['id'],str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.:-]{0,79}',row['id']) or row['id'] in names:
            raise ValueError('阶段ID须唯一且有界')
        names.add(row['id']);goals._text(row['label'],'阶段名称',120);goals._text(row['assumption'],'阶段依据')
        goals._ids(row['goal_ids'],nodes,'阶段目标',empty=True)
        goals._number(row['minimum_duration_seconds'],0,315360000,'阶段最短持续时间',integer=True)
        if not row['goal_ids'] and not row['minimum_duration_seconds']:raise ValueError('无目标阶段须有明确的非零时间过程')
        if any(i in owners for i in row['goal_ids']):raise ValueError('一个目标不能属于两个阶段，请明确不同里程碑')
        owners.update({i:index for i in row['goal_ids']})
        if not isinstance(row['operation_ids'],list) or len(row['operation_ids'])>16 or any(not isinstance(i,str) for i in row['operation_ids']) or len(set(row['operation_ids']))!=len(row['operation_ids']):raise ValueError('阶段来源须为有界不重复事件列表')
        for identity in row['operation_ids']:
            if not isinstance(identity,str) or not world.get('historical_initial'):raise ValueError('阶段来源缺少冻结历史身份')
            historical_links.find(world['historical_initial'],identity)
    for identity,owner in owners.items():
        seen=set();pending=list(nodes[identity]['after']['node_ids'])
        while pending:
            parent=pending.pop()
            if parent in seen:continue
            seen.add(parent)
            if owners.get(parent,-1)>owner:raise ValueError('前阶段目标不能依赖尚未激活的后阶段目标')
            pending.extend(nodes[parent]['after']['node_ids'])
    return copy.deepcopy(value)


def _seal(state):
    from . import missions
    state['state_hash']=missions.digest({k:v for k,v in state.items() if k!='state_hash'})


def initialize(world):
    config=definition(world)
    if config is None:return
    from . import missions
    validate_config(config,world)
    rows={r['id']:dict(status='pending',entered_at=None,completed_at=None,goal_evidence={}) for r in config['phases']}
    rows[config['phases'][0]['id']].update(status='active',entered_at=0)
    state=dict(version=VERSION,definition_hash=missions.digest(config),turn=0,sample_at=0,phase_index=0,
        last_sample_phase=0,status='active',reason='',phases=rows,last_changes=[])
    _seal(state);world['campaign_lifecycle']=state


def sample_phase(world):
    state=world.get('campaign_lifecycle')
    if state is None:return None
    return state['last_sample_phase'] if state['turn']==world['mission']['turn'] else state['phase_index']


def goal_ready(world,goal_id):
    config=definition(world)
    if config is None:return True
    owner=next((i for i,r in enumerate(config['phases']) if goal_id in r['goal_ids']),None)
    return owner is None or owner<=sample_phase(world)


def validate_state(world):
    from . import missions, campaign_plan as goals
    config=definition(world);state=world.get('campaign_lifecycle')
    if config is None:
        if state is not None:raise ValueError('未绑定阶段定义，不能注入阶段状态')
        return
    validate_config(config,world)
    goals._fields(state,{'version','definition_hash','turn','sample_at','phase_index','last_sample_phase','status','reason','phases','last_changes','state_hash'},'阶段状态')
    if (state['version']!=VERSION or state['definition_hash']!=missions.digest(config)
            or state['state_hash']!=missions.digest({k:v for k,v in state.items() if k!='state_hash'})
            or state['turn']!=world['mission']['turn'] or state['sample_at']!=world['simulation_clock']['elapsed_seconds']):
        raise ValueError('阶段状态与定义、时钟或摘要不一致')
    count=len(config['phases']);index=state['phase_index']
    goals._number(index,0,count-1,'当前阶段',integer=True)
    goals._number(state['last_sample_phase'],max(0,index-1),index,'本轮实际评分阶段',integer=True)
    if state['status'] not in ('active','completed','interrupted'):raise ValueError('阶段状态非法')
    if type(state['turn']) is not int or state['turn']<0 or index+int(state['status']=='completed')>state['turn']:
        raise ValueError('完成阶段数不能超过实际物理回合，不能在零回合跳过阶段')
    if state['status']=='completed' and index!=count-1:raise ValueError('阶段链尚未完成')
    if state['status']=='interrupted' and (world['mission']['status']!='completed' or not state['reason']):raise ValueError('阶段中断缺少全局结算依据')
    goals._fields(state['phases'],{p['id'] for p in config['phases']},'阶段登记')
    prior_end=0
    for number,phase in enumerate(config['phases']):
        row=state['phases'][phase['id']]
        goals._fields(row,{'status','entered_at','completed_at','goal_evidence'},'阶段记录')
        complete=number<index or number==index and state['status']=='completed'
        expected='completed' if complete else 'active' if number==index else 'pending'
        if row['status']!=expected:raise ValueError('阶段状态顺序与当前索引不一致')
        if number>index:
            if row['entered_at'] is not None or row['completed_at'] is not None or row['goal_evidence']:raise ValueError('未来阶段不能提前登记完成')
            continue
        if row['entered_at']!=prior_end:raise ValueError('阶段进入时点不连续')
        if complete:
            goals._number(row['completed_at'],row['entered_at']+max(1,phase['minimum_duration_seconds']),state['sample_at'],'阶段完成时点',integer=True)
            if row['goal_evidence']!={i:'completed' for i in phase['goal_ids']}:raise ValueError('阶段缺少实际目标完成证据')
            prior_end=row['completed_at']
        elif row['completed_at'] is not None or row['goal_evidence']:raise ValueError('未完成阶段不得写入完成证据')
    if not isinstance(state['last_changes'],list) or len(state['last_changes'])>2:raise ValueError('阶段变化记录非法')
    seen=set()
    for change in state['last_changes']:
        goals._fields(change,{'phase_id','status','at_seconds'},'阶段变化')
        if (not isinstance(change['phase_id'],str) or change['phase_id'] not in state['phases']
                or change['status'] not in ('active','completed') or type(change['at_seconds']) is not int
                or change['at_seconds']!=state['sample_at'] or (change['phase_id'],change['status']) in seen):
            raise ValueError('阶段变化必须引用本轮已登记阶段和实际采样时点')
        seen.add((change['phase_id'],change['status']))
    return True


def evaluate(world,nodes):
    config=definition(world)
    if config is None:return True
    from . import missions
    prior=world.get('campaign_lifecycle')
    if prior is None or prior['state_hash']!=missions.digest({k:v for k,v in prior.items() if k!='state_hash'}):raise ValueError('阶段前态缺失或已改变')
    turn=world['mission']['turn'];elapsed=world['simulation_clock']['elapsed_seconds']
    if turn!=prior['turn']+1 or elapsed<=prior['sample_at']:raise ValueError('阶段须随物理世界逐轮推进，不能跳时或重复结算')
    state=copy.deepcopy(prior);index=state['phase_index'];phase=config['phases'][index];row=state['phases'][phase['id']]
    state.update(turn=turn,sample_at=elapsed,last_sample_phase=index,last_changes=[])
    if state['status']=='active' and elapsed-row['entered_at']>=phase['minimum_duration_seconds'] and all(nodes[i]['status']=='completed' for i in phase['goal_ids']):
        row.update(status='completed',completed_at=elapsed,goal_evidence={i:nodes[i]['status'] for i in phase['goal_ids']})
        state['last_changes'].append(dict(phase_id=phase['id'],status='completed',at_seconds=elapsed))
        if index+1<len(config['phases']):
            state['phase_index']=index+1;following=config['phases'][index+1]
            state['phases'][following['id']].update(status='active',entered_at=elapsed)
            state['last_changes'].append(dict(phase_id=following['id'],status='active',at_seconds=elapsed))
        else:state['status']='completed'
    _seal(state);world['campaign_lifecycle']=state
    return state['status']=='completed' or config['finish_policy']=='goal_outcomes'


def settle(world):
    state=world.get('campaign_lifecycle')
    if state and world['mission']['status']=='completed' and state['status']!='completed':
        state.update(status='interrupted',reason='全局会战已结算，阶段未全部完成：'+world['mission']['reason']);_seal(state)


def observation(world,*,offset=0,limit=8,view_version=None):
    from . import missions
    config=definition(world)
    if config is None:return {'ok':False,'error':'当前战局未配置单世界阶段链'}
    validate_state(world)
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=16:raise ValueError('阶段分页须为非负偏移和1至16条')
    state=world['campaign_lifecycle'];token=missions.digest([world['mission']['definition_hash'],state['state_hash']])
    if offset and view_version is None or view_version is not None and view_version!=token:raise ValueError('阶段观察版本已变化，请从第一页重查')
    phases=config['phases'];current=phases[state['phase_index']]
    return dict(ok=True,readonly=True,version=VERSION,turn=state['turn'],status=state['status'],reason=state['reason'],
        view_version=token,phase_index=state['phase_index'],total=len(phases),current_label=current['label'],offset=offset,
        elapsed_seconds=state['sample_at'],minimum_remaining_seconds=max(0,current['minimum_duration_seconds']-(state['sample_at']-state['phases'][current['id']]['entered_at'])),
        rows=[dict(**copy.deepcopy(p),state=copy.deepcopy(state['phases'][p['id']])) for p in phases[offset:offset+limit]],
        next_args=dict(offset=offset+limit,limit=limit,view_version=token) if offset+limit<len(phases) else None,
        scope='同一物理世界的阶段里程碑；不改单位集合、不自动下令或补员，不是已实现退场重编或完整历史会战。')


def instruction(world):
    config=definition(world)
    if config is None:return ''
    state=world['campaign_lifecycle'];phase=config['phases'][state['phase_index']]
    return ('\n【单世界会战阶段】当前第'+str(state['phase_index']+1)+'/'+str(len(config['phases']))+'阶段：'+phase['label']+
        '。阶段目标到激活后才评分，每轮最多完成一个阶段；阶段间隙仍实际推进粮弹、疲劳和时间。'+
        ('当前要求全部阶段完成后再判总目标。' if config['finish_policy']=='all_phases' else '当前双方总目标可提前结算并中断后续阶段。')+
        '所有单位与命令账沿同一世界延续；此契约不改变参战单位集合，不自动下令、补员或搬运。'
        '用get_campaign_lifecycle沿next_args查询阶段，用get_campaign_objectives核当前目标。')
