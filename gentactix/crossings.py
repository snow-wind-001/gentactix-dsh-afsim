"""Versioned formation crossing inputs and receipt guards; no turn executor.

Work is a throughput measure for an aggregate formation, not a count of individual
soldiers already on either bank. Actual paths and queue service execute in WSF.
"""
import copy,math,re
from . import missions

VERSION='formation-crossing-1'
TASK_VERSION='formation-crossing-task-1'
BOUND_TASK_VERSION='formation-crossing-task-2'
CATEGORIES=('armor','artillery','air_defense','engineer','transport')
TASK_FIELDS={'version','site_id','model_hash','from_bank','target','required_work','served_work','status','last_work','turn','source','events'}


def configuration_template(assumption):
    """Unfilled input shape, never a generated river or usable capacity."""
    point={'lat':None,'lng':None}
    return {'version':VERSION,'barrier':{k:copy.deepcopy(point) for k in ('a','b')},
            'banks':{k:copy.deepcopy(point) for k in ('a','b')},'throughput_work_per_hour':None,
            'equipment_work':{k:None for k in CATEGORIES},'build_progress_per_engineer_hour':None,
            'supply_work_per_unit':None,'assumption':assumption}


def fields(value,expected,label):
    if not isinstance(value,dict) or set(value)!=set(expected):raise ValueError(label+'字段非法')


def number(value,low=0,high=1e8,integer=False,*,label=None):
    if type(value) not in ((int,) if integer else (int,float)) or not math.isfinite(value) or not low<=value<=high:
        detail='' if label is None else f'（{label} 允许范围{low:g}至{high:g}；收到{repr(value)[:100]}）'
        raise ValueError('渡河参数必须为有界有限数值；计数不能使用布尔值'+detail)


def point(value):
    fields(value,{'lat','lng'},'渡河坐标');number(value['lat'],-85,85);number(value['lng'],-180,180)


def orientation(p,a,b):
    return (b['lng']-a['lng'])*(p['lat']-a['lat'])-(b['lat']-a['lat'])*(p['lng']-a['lng'])


def intersects(origin,target,model):
    """Finite segment intersection; touching the barrier is conservative."""
    a,b=model['barrier']['a'],model['barrier']['b']
    x,y=orientation(origin,a,b),orientation(target,a,b)
    u,v=orientation(a,origin,target),orientation(b,origin,target)
    return (x*y<=0 and u*v<=0 and abs(x-y)>1e-12 and abs(u-v)>1e-12)


def validate_model(model):
    fields(model,{'version','barrier','banks','throughput_work_per_hour','equipment_work',
                  'build_progress_per_engineer_hour','supply_work_per_unit','assumption'}|({'ferry'} if 'ferry' in model else set()),'渡河模型')
    if model['version']!=VERSION or not isinstance(model['assumption'],str) or not model['assumption'].strip():
        raise ValueError('渡河模型版本与估计依据非法')
    for key in ('barrier','banks'):
        fields(model[key],{'a','b'},'河线/两岸');point(model[key]['a']);point(model[key]['b'])
        if missions.distance(model[key]['a'],model[key]['b'])<.01:raise ValueError('河线与两岸点不能重合')
    if not intersects(model['banks']['a'],model['banks']['b'],model):raise ValueError('两岸通道必须跨越所声明有限河线')
    if any(abs(orientation(p,model['barrier']['a'],model['barrier']['b']))<1e-12 for p in model['banks'].values()):
        raise ValueError('两岸点必须位于河线两侧')
    number(model['throughput_work_per_hour'],.01,1e6,label='facility.crossing_model.throughput_work_per_hour')
    number(model['build_progress_per_engineer_hour'],.0001,1000,label='facility.crossing_model.build_progress_per_engineer_hour')
    number(model['supply_work_per_unit'],.01,1e6,label='facility.crossing_model.supply_work_per_unit')
    fields(model['equipment_work'],CATEGORIES,'装备渡运工作量')
    for key,value in model['equipment_work'].items():number(value,0,100,label='facility.crossing_model.equipment_work.'+key)
    if 'ferry' in model:
        from . import ferries
        ferries.validate_config(model['ferry'])
    return True


def get_model(world):
    return world.get('combined_arms',{}).get('bridge',{}).get('crossing_model')


def required_work(unit,model):
    """Static requested load from inputs, not movement or service allocation."""
    return unit['personnel']['current']+sum(e['operational']*model['equipment_work'][e['category']] for e in unit['equipment'])


def bank_route(origin,target,model):
    """Declared crossing corridor; this describes inputs, never runs transport."""
    if not intersects(origin,target,model):return [target]
    a,b=model['barrier']['a'],model['barrier']['b']
    bank='a' if orientation(origin,a,b)*orientation(model['banks']['a'],a,b)>=0 else 'b'
    return [model['banks'][bank],model['banks']['b' if bank=='a' else 'a'],target]


def validate_task(site,task):
    bound=isinstance(task,dict) and task.get('version')==BOUND_TASK_VERSION
    fields(task,TASK_FIELDS|({'intent_id'} if bound else set()),'编组渡运回执');model=site['crossing_model']
    if bound:validate_intent(task['intent_id'])
    if task['version'] not in (TASK_VERSION,BOUND_TASK_VERSION) or task['site_id']!=site['id'] or task['model_hash']!=missions.digest(model):
        raise ValueError('渡运任务不属于当前冻结设施/模型')
    if task['from_bank'] not in ('a','b') or task['status'] not in (('queued','transit','completed','cancelled') if bound else ('queued','transit','completed')):
        raise ValueError('渡运方向或状态非法')
    point(task['target']);number(task['required_work'],.01);number(task['served_work'],0,task['required_work'])
    number(task['last_work'],0,task['required_work']);number(task['turn'],0,10**9,True)
    if task['source'] not in ('input_estimate','afsim_native_estimate','dsh_model_estimate'):raise ValueError('渡运回执来源非法')
    if task['status'] in ('transit','completed') and abs(task['served_work']-task['required_work'])>.001:
        raise ValueError('渡运工作量未完成不能称整建制通过')
    if not isinstance(task['events'],list) or len(task['events'])>4:raise ValueError('渡运事件非法')
    for event in task['events']:
        fields(event,{'phase','seconds','lat','lng'},'渡运事件')
        if event['phase'] not in ('entered','exited'):
            raise ValueError('unit_updates[].crossing.events.phase只允许entered/exited；收到'+repr(event['phase'])+
                '。loading/boarded/landed/returned等舟艇事件放在combined_arms.bridge.ferry_state.events，不混用两个事件列表')
        number(event['seconds'],0,31*86400);point({k:event[k] for k in ('lat','lng')})
    return True


def validate_intent(identity):
    if not isinstance(identity,str) or re.fullmatch('[a-f0-9]{32}',identity) is None:raise ValueError('渡运指令标识必须由宿主命令队列提供')


def check_order(before,order):
    """Reserved metadata is supplied by the host, never model-selected."""
    if not any(k in order for k in ('intent_id','cancel_crossing')):return
    if not get_model(before):
        from . import movement_feedback
        if 'cancel_crossing' in order or not movement_feedback.continuous(before):
            raise ValueError('没有渡运模型，不接受渡运控制元数据')
    if 'intent_id' in order:
        validate_intent(order['intent_id'])
        if order.get('action')!='move':raise ValueError('仅移动指令可绑定渡运意图')
    if 'cancel_crossing' in order:
        validate_intent(order['cancel_crossing'])
        u=next(u for _,u in missions.units(before) if u['name']==order['unit'])
        if u.get('crossing',{}).get('intent_id')!=order['cancel_crossing'] or u['crossing']['status'] not in ('queued','transit'):
            raise ValueError('撤销的渡运意图不属于该单位当前未完成任务')


def plan(site,unit,target):
    """Describe a route and immutable task input; never allocate capacity."""
    model=site.get('crossing_model')
    if model is None:return None
    if 'intent_id' in target:validate_intent(target['intent_id'])
    validate_model(model);point({k:unit[k] for k in ('lat','lng')});point({k:target[k] for k in ('lat','lng')})
    previous=unit.get('crossing')
    if previous:validate_task(site,previous)
    same=(previous and missions.distance(previous['target'],target)<.000001 and previous['status'] not in ('completed','cancelled')
          and previous.get('intent_id')==target.get('intent_id') and target.get('cancel_crossing')!=previous.get('intent_id',''))
    transit=previous and previous['status']=='transit'
    if transit:
        a,b=model['barrier']['a'],model['barrier']['b'];exit_bank='b' if previous['from_bank']=='a' else 'a'
        if orientation(target,a,b)*orientation(model['banks'][exit_bank],a,b)<=0:
            raise ValueError('编组已在通道内，须先抵岸再执行回撤；不能撤销已形成的位置')
    if not same and not transit and not intersects(unit,target,model):return None
    a,b=model['barrier']['a'],model['barrier']['b']
    bank=previous['from_bank'] if same or transit else ('a' if orientation(unit,a,b)*orientation(model['banks']['a'],a,b)>=0 else 'b')
    entry=copy.deepcopy(model['banks'][bank]);exit=copy.deepcopy(model['banks']['b' if bank=='a' else 'a'])
    total=required_work(unit,model);number(total,.01)
    task=copy.deepcopy(previous) if same or transit else {'version':TASK_VERSION,'site_id':site['id'],'model_hash':missions.digest(model),
        'from_bank':bank,'target':{k:target[k] for k in ('lat','lng')},'required_work':total,'served_work':0,
        'status':'queued','last_work':0,'turn':0,'source':'input_estimate','events':[]}
    if transit:task['target']={k:target[k] for k in ('lat','lng')}
    if 'intent_id' in target:task.update(version=BOUND_TASK_VERSION,intent_id=target['intent_id'])
    elif transit:task.pop('intent_id',None);task['version']=TASK_VERSION
    enter_required=not transit
    waypoints=([entry] if enter_required else [])+[exit,{k:target[k] for k in ('lat','lng')}]
    return {'task':task,'entry':entry,'exit':exit,'enter_required':enter_required,'waypoints':waypoints}


def path_position(origin,waypoints,position,tolerance_km=.02):
    """Read-only path membership and travelled distance for observation guards."""
    done=0;best=None
    for target in waypoints:
        length=missions.distance(origin,target);part=missions.distance(origin,position)
        error=abs(part+missions.distance(position,target)-length)
        if error<=tolerance_km and (best is None or error<best[0]):best=(error,done+part)
        done+=length;origin=target
    return best[1] if best is not None else None


def validate_model_transition(before,after,updates,orders,seconds,result):
    from . import crossing_network
    if crossing_network.enabled(before):
        return crossing_network.validate_transition(before,after,updates,orders,seconds,result)
    model=get_model(before)
    if model is None:
        if updates:raise ValueError('本局没有渡运模型，不能迁入渡河状态')
        return
    if model.get('ferry'):
        from . import ferries
        validate_construction(before,after,orders,seconds,result)
        ferries.validate_transition(before,after,updates,orders,seconds,result)
        return
    site=before['combined_arms']['bridge'];new={u['name']:u for _,u in missions.units(after)};checked={o['unit']:o for o in orders}
    validate_construction(before,after,orders,seconds,result)
    used=0;requested=False;arrivals=[];eligible=[]
    limits={r['unit']:r for r in observation(before)['unit_limits']}
    for _,unit in missions.units(before):
        name=unit['name'];order=checked.get(name,{'action':'hold'});plan_for=plan(site,unit,order) if order['action']=='move' else None
        prior=plan_for['task'] if plan_for else unit.get('crossing');provided=updates.get(name)
        cancelled=bool(prior and not plan_for and prior['status']=='queued' and order.get('cancel_crossing')==prior.get('intent_id') and 'cancel_crossing' in order)
        if prior is None:
            if provided is not None:raise ValueError('没有已登记渡运任务，不能提交渡河进度')
            continue
        if plan_for:
            requested=True
            if (site['progress']>=100 and site['integrity']>=50 and prior['served_work']<prior['required_work']-.002
                    and limits[name]['entry_earliest_s'][prior['from_bank']]<seconds-1):eligible.append(name)
        if provided is None:
            if cancelled:raise ValueError('已确认撤销排队任务，须提交cancelled状态，既有服务量不退回')
            if plan_for:raise ValueError('跨河移动须提交完整渡运进度，不得直接跳到对岸')
            task=copy.deepcopy(prior);task.update(last_work=0,events=[],turn=before['mission']['turn']+1,source='dsh_model_estimate')
        else:
            if not isinstance(provided,dict):raise ValueError('渡运状态必须为对象')
            mutable={'served_work','last_work','status','events'}
            if not mutable<=set(provided) or set(provided)-TASK_FIELDS or any(provided[k]!=prior[k] for k in set(provided)-mutable):
                raise ValueError('渡运任务只能提交served_work/last_work/status/events；不得改写设施、负载或目的地')
            task={**copy.deepcopy(prior),**{k:copy.deepcopy(provided[k]) for k in mutable},'turn':before['mission']['turn']+1,'source':'dsh_model_estimate'}
            validate_task(site,task)
            if not math.isclose(task['served_work']-prior['served_work'],task['last_work'],abs_tol=.002):raise ValueError('渡运累计工作量与本轮增量不符')
            expected_status='cancelled' if cancelled else prior['status']
            if not plan_for and (task['served_work']!=prior['served_work'] or task['status']!=expected_status or task['events']):raise ValueError('未下达渡河移动不得消耗容量或改变通过状态；撤销须保留已耗工作量')
        if plan_for:
            entry,exit=plan_for['entry'],plan_for['exit'];pose=new[name];events=task['events']
            entered=next((e for e in events if e['phase']=='entered'),None);exited=next((e for e in events if e['phase']=='exited'),None)
            if [e['phase'] for e in events] not in ([],['entered'],['entered','exited'],['exited']):raise ValueError('渡运事件顺序非法')
            if any(e['seconds']>seconds for e in events) or any(a['seconds']>b['seconds'] for a,b in zip(events,events[1:])):raise ValueError('渡运事件越出当前回合')
            for event,p in ((entered,entry),(exited,exit)):
                if event and missions.distance(event,p)>.02:raise ValueError('渡运事件不在登记两岸点')
            if task['last_work']:
                if not entered:raise ValueError(name+'本轮新增渡运服务必须在events登记本轮entered事件（岸点lat/lng、相对秒数）；已在入口也不能省略，旧轮事件不代替本轮回执')
                if site['progress']<100 or site['integrity']<50:raise ValueError('设施未开放，不得取得渡运工作量')
                if task['last_work']>model['throughput_work_per_hour']*(seconds-entered['seconds'])/3600+.002:raise ValueError('渡运增量超出到达后的可用时间')
                arrivals.append((entered['seconds'],task['last_work']))
            travelled=path_position(unit,plan_for['waypoints'],pose)
            speed=missions.move_budget(before,unit)*1000/seconds
            if travelled is None or travelled*1000/max(.001,speed)+task['last_work']*3600/model['throughput_work_per_hour']>seconds+1:
                raise ValueError('行军与渡运服务总时间超出回合')
            earliest=missions.distance(unit,entry)*1000/max(.001,speed)
            if entered and entered['seconds']+1<earliest:raise ValueError(f'{name}抵达入口{entered["seconds"]}秒早于最早{math.ceil(earliest)}秒；有效速度{speed:.4f}m/s已含地形和粮食约束，不得直接用名义speed')
            if task['served_work']+1e-6<task['required_work']:
                if task['status']!='queued' or path_position(unit,[entry],pose) is None:raise ValueError('渡运工作量未完成，整建制位置不得越过入口')
            if task['status']=='completed':
                if not exited or path_position(exit,[task['target']],pose) is None:raise ValueError('未抵达出口不得声称整建制通过')
                speed=missions.move_budget(before,unit)*1000/seconds
                if entered and exited['seconds']+1<entered['seconds']+task['last_work']*3600/model['throughput_work_per_hour']+missions.distance(entry,exit)*1000/max(.001,speed):
                    raise ValueError('完成时间短于渡运服务与跨河行程')
            elif task['status']=='queued':
                if exited or path_position(unit,[entry],pose) is None:raise ValueError('排队状态不能把整建制位置移过入口')
            elif task['status']=='transit':
                if exited or path_position(entry,[exit],pose) is None:raise ValueError('通过中状态须位于登记两岸通道')
                if plan_for['enter_required'] and not entered:raise ValueError('本轮开始通过须有入口事件')
        new[name]['crossing']=task;used+=task['last_work']
    budget=model['throughput_work_per_hour']*seconds/3600
    for arrival,_ in arrivals:
        if sum(work for t,work in arrivals if t>=arrival)>model['throughput_work_per_hour']*(seconds-arrival)/3600+.003:
            raise ValueError('多编组到达后申请的共享工作量超过剩余服务时间')
    cargo=cargo_work(before,after,result,seconds)
    if eligible and used+cargo<=.000001:
        raise ValueError('通道开放且存在本轮可到入口的已确认渡运移动：'+ '、'.join(eligible)+'；没有其他服务或物资占用时，不得无故整轮零服务。应登记本轮entered事件并估计实际服务，不把继续移动改成待命')
    ledger=(result.get('combined_arms') or {}).get('bridge',{}).get('crossing_receipt')
    if ledger is None:
        if requested or cargo:raise ValueError('渡运命令或跨河到货须提交设施容量总账')
        ledger={'used_work':0,'cargo_work':0,'budget_work':budget}
    fields(ledger,{'used_work','cargo_work','budget_work'},'设施渡运容量总账')
    for v in ledger.values():number(v,0,1e9)
    if abs(ledger['used_work']-used)>.002 or abs(ledger['budget_work']-budget)>.002 or used+ledger['cargo_work']>budget+.002:
        raise ValueError('设施渡运总账不守恒或超出当前回合容量')
    if abs(ledger['cargo_work']-cargo)>.002:raise ValueError('渡运物资工作量与实际毛到货不一致')
    after['combined_arms']['bridge']['crossing_receipt']={**copy.deepcopy(ledger),'turn':before['mission']['turn']+1,'source':'dsh_model_estimate',
        'scope':'整建制渡运工作量估计，不是个体实时位置或AFSIM原生回执'}


def validate_construction(before,after,orders,seconds,result):
    site=before['combined_arms']['bridge'];following=after['combined_arms']['bridge'];model=get_model(before)
    cfg=before['mission']['definition']['combined_rules'];units={u['name']:u for _,u in missions.units(before)}
    rows={r['unit']:r for r in result['resource_ledger']['units']};limit=0;materials=0;demolitions=0
    for order in orders:
        if order['action']=='demolish':demolitions+=1
        if order['action']!='build_bridge':continue
        u=units[order['unit']];f=u['formation'];node=next(n for n in before['supply_nodes'] if n['id']==u['supply_node_id'])
        delay=cfg['command_base_s']+(100-f['signal'])*cfg['command_signal_s']+missions.distance(u,node)*cfg['command_distance_s_per_km']
        engineers=next(e['operational'] for e in u['equipment'] if e['category']=='engineer')
        spent=rows[u['name']]['spent'].get('materials',0);materials+=spent
        limit+=min(engineers*u['personnel']['current']/u['personnel']['committed']*model['build_progress_per_engineer_hour']*max(0,seconds-delay)/3600,
                   spent*cfg['build_gain']/cfg['build_materials'])
    if following['progress']<site['progress'] or max(following['progress']-site['progress'],following['integrity']-site['integrity'])>limit+.001:
        raise ValueError('施工或修桥进度超过工兵、有效时间或实际材料消耗')
    if following['integrity']<max(0,site['integrity']-50*demolitions):raise ValueError('设施损伤缺少已下达的拆除命令')
    if site['materials']-following['materials']!=materials:raise ValueError('设施施工材料与工兵实际消耗不一致')


def cargo_work(before,after,result,seconds):
    """Validate declared cargo against frozen route/transport bounds, not execute it."""
    model=get_model(before);site=before['combined_arms']['bridge'];cfg=before['mission']['definition']['combined_rules']
    old={u['name']:u for _,u in missions.units(before)};new={u['name']:u for _,u in missions.units(after)}
    nodes={n['id']:n for n in before['supply_nodes']};total=0
    for row in result['resource_ledger']['units']:
        prior=old[row['unit']];pose=new[row['unit']];node=nodes[prior['supply_node_id']]
        if not intersects(node,pose,model):continue
        mass=row['delivery']*cfg['ton_per_supply_unit']+sum(v*cfg['cargo_mass_tons'][k] for k,v in row['received'].items())
        if not mass:continue
        if site['progress']<100 or site['integrity']<50:raise ValueError('设施未开放不能宣称跨河到货')
        points=[node]+bank_route(node,pose,model)
        distance=sum(missions.distance(a,b) for a,b in zip(points,points[1:]))
        trucks=next(e['operational'] for e in prior['equipment'] if e['category']=='transport')
        capacity=trucks*cfg['transport_tons_per_truck']*prior['personnel']['current']/prior['personnel']['committed']*min(1,cfg['convoy_km_per_turn']/max(.1,distance))
        if mass>capacity+.001:raise ValueError('跨河毛到货超过运输车辆与通道能力')
        total+=mass/cfg['ton_per_supply_unit']*model['supply_work_per_unit']
    return total


def instruction(world):
    from . import crossing_network
    if crossing_network.enabled(world):
        return ('\n当前为同一河线的多渡点。每个设施独立排队并共享其人员及货运容量；全场仍共用既有部队和仓库，不复制实体。'
            '按入口→出口→目的地总距离最短选择渡点，同距按冻结顺序；同一未完成移动保持site_id，不借用另一设施工作量。'
            '工兵建设/拆除选择距现有岸点最近的设施。补给根据实际轮末位置选最短登记通道，不自动绕开关闭或受敌控制的路线。'
            '主设施结果在combined_arms.bridge；其他设施在bridge.crossing_network.sites，保持完整冻结字段和数组顺序，逐设施提交crossing_receipt。'
            '不得合并各渡点容量总账。crossing_inputs含宿主确定的site_id；不能自行换点或复用别处entered/exited事件。'
            +instruction(crossing_network.projected(world,world['combined_arms']['bridge'])))
    if not get_model(world):return ''
    if get_model(world).get('ferry'):
        return ('\n当前为formation-ferry-1舟艇通行，不采用桥式连续服务或步行跨水时间。'
            '沿入口→舟艇→出口→地面目标；先装载、按船速航行、卸载后才completed。'
            'intent_id和cancel_crossing由宿主绑定，不自行提交。unit_updates.crossing只含served_work/last_work/status/events；'
            '登船占用容量，未登岸仍是transit。人员与装备随既有计算分队，不新增兵力。'
            'combined_arms.bridge.crossing_receipt为{used_work:本轮登船占用工作量,cargo_work:0,budget_work:throughput_work_per_hour×本轮小时}，不能作为顶层字段。'
            'unit_updates[].crossing.events只允许岸点entered/exited；combined_arms.bridge.ferry_state.events才使用loading/boarded/landed/returned等舟艇事件，两个列表不可混用。'
            '泊位或装卸中的船必须在岸点，不能无命令漂移。船与乘客位置一致，空艇须返航；'
            '舟艇不受未建桥progress条件阻断，不能把本模型声称为水文、沉船或完整桥头战斗。')
    return ('\n渡河使用formation-crossing-1：有限河线barrier、两岸banks、整建制共享工作量，不采用桥梁经度或每轮固定批次。'
        'intent_id和cancel_crossing是宿主绑定的控制元数据，不自行生成或复制到orders；只输出动作及目标，宿主按确认队列绑定。'
        '确认指挥中的cancelled_crossing_tasks若无新人工命令，则本轮hold；queued任务crossing提交status=cancelled、served_work保持原值、last_work=0、events=[]，已耗容量不退回。transit保持位置与已服务量，须先抵岸才能回撤。'
        'crossing_constraints列出本轮有效速度、机动预算及抵岸最早秒数，已计地形与粮食；不要直接用unit.speed作实际速度，不把岸间行程漏出服务时间。'
        '跨河move须沿入口→出口→目标；人数加分类可用装备×equipment_work为新任务required_work；相同未完成任务继承served_work，改目标从0重新申请。'
        'unit_updates.crossing只提交{served_work,last_work,status,events}，其余设施、任务身份由宿主绑定。status可queued/transit/completed；有宿主确认的queued撤销时才可cancelled。未服务完须留在入口前，服务完后才沿通道运动，到出口方可completed。'
        'events格式{phase:"entered或exited",seconds:本轮秒数,lat:岸点纬度,lng:岸点经度}，须按实际抵达顺序；待命保留任务但不增加工作量。'
        '新增服务必须有本轮entered事件，即使单位轮初已在入口；按entry_earliest_s登记可开始服务的本轮时点，不使用旧轮事件替代。'
        '若设施轮初开放、仍有未完成渡运移动能在本轮到达入口，且没有任何编组/物资服务占用，不能将整轮服务量全部报0来规避事件校验；须履行已确认移动并申报服务。关闭设施或尚不能到入口时可合法为0，不补造通过。'
        '行军与服务时间之和不超过本轮；服务量不超过到达后吞吐×剩余小时，所有编组共享，不得各自享有全部容量。设施轮初progress<100或integrity<50不能通行或跨河补给。'
        'combined_arms.bridge.crossing_receipt必须提交{used_work:本轮编组last_work合计,cargo_work:跨河毛到货吨数/ton_per_supply_unit×supply_work_per_unit,budget_work:吞吐/小时×本轮小时}；前两者之和不超过budget_work。'
        '跨河补给路线同样经过两岸；吨数包括delivery×ton_per_supply_unit和received分类物资×cargo_mass_tons，受运输量限制，不能只算粮弹而漏掉炮弹或燃油。'
        'build_bridge依工程数×可用人员比例×build_progress_per_engineer_hour×有效小时估计，受材料配比限制，下一轮才开放；不能套用旧规则每轮50%。'
        '这是显式估计的编组通行模型，不能声称已模拟单兵分岸、舟桥突击或历史精确水文。')


def observation(world):
    """Bounded static feasibility inputs, not generated arrival/service receipts."""
    from . import crossing_network
    if crossing_network.enabled(world):return crossing_network.observation(world)
    model=get_model(world)
    if not model:return None
    cfg=world['mission']['definition']['combined_rules']
    from . import sim_clock
    seconds=sim_clock.duration_seconds(world['mission']['definition']['time_step']);limits=[]
    for _,u in missions.units(world):
        budget=missions.move_budget(world,u);speed=budget*1000/seconds;f=u['formation']
        node=next(n for n in world['supply_nodes'] if n['id']==u['supply_node_id'])
        delay=cfg['command_base_s']+(100-f['signal'])*cfg['command_signal_s']+missions.distance(u,node)*cfg['command_distance_s_per_km']
        pause=max(delay+seconds*(f['fatigue']/200+f['suppression']/250),seconds*(1-u['personnel']['current']/u['personnel']['committed']))
        limits.append({'unit':u['name'],'move_budget_km':round(budget,6),'effective_speed_mps':round(speed,6),
            'entry_earliest_s':{k:math.ceil(pause+missions.distance(u,p)*1000/max(.001,speed)) for k,p in model['banks'].items()},
            'bank_travel_min_s':math.ceil(missions.distance(model['banks']['a'],model['banks']['b'])*1000/max(.001,speed)),
            'new_task_required_work':required_work(u,model)})
    if model.get('ferry'):
        from . import ferries
        for row in limits:row.pop('bank_travel_min_s',None)
    return {'scope':'frozen_input_feasibility_bounds; not_executed_effects','unit_limits':limits,
        'capacity_budget_work':model['throughput_work_per_hour']*seconds/3600,
        **({'ferry':ferries.observation(world)} if model.get('ferry') else {}),
        'resource_rules':{k:copy.deepcopy(cfg[k]) for k in ('build_gain','build_materials','ton_per_supply_unit','cargo_mass_tons','transport_tons_per_truck','convoy_km_per_turn')}}


def pending_move(before,prior,following,order):
    """Read an already validated task when verifying a destination command."""
    if order.get('action')!='move' or not get_model(before):return False
    from . import crossing_network
    route=crossing_network.plan(before,prior,order);task=following.get('crossing')
    if not route or not task:return False
    validate_task(crossing_network.by_id(before,task['site_id']),task)
    return (task['turn']==before['mission']['turn']+1 and missions.distance(task['target'],order)<.000001
            and path_position(prior,route['waypoints'],following) is not None)


def comparison_orders(record,orders):
    """An unchanged intervention retains the factual host control identity."""
    factual=(record.get('external_execution') or {}).get('orders') or record.get('after',{}).get('mission',{}).get('last_orders',[])
    by_name={o['unit']:o for o in factual};result=copy.deepcopy(orders)
    for order in result:
        prior=by_name.get(order['unit'])
        if prior and all(order.get(k)==prior.get(k) for k in ('action','lat','lng','target','air_pool')):
            for key in ('intent_id','cancel_crossing'):
                order.pop(key,None)
                if key in prior:order[key]=prior[key]
    return result


def order_inputs(world,orders):
    """Read-only task starting conditions, never allocated service or effects."""
    if not get_model(world):return []
    from . import crossing_network
    units={u['name']:u for _,u in missions.units(world)};result=[]
    for order in orders:
        unit=units[order['unit']];route=crossing_network.plan(world,unit,order) if order['action']=='move' else None
        task=route['task'] if route else unit.get('crossing')
        if not task:continue
        operation=('continue_transit' if not route['enter_required'] else 'resume' if task['served_work'] else 'start') if route else \
            'cancel' if order.get('cancel_crossing') and task['status']=='queued' else 'preserve'
        result.append({'unit':order['unit'],'site_id':task['site_id'],'operation':operation,'start_work':task['served_work'],
                       'required_work':task['required_work'],'from_bank':task['from_bank'],
                       'target':copy.deepcopy(task['target']),
                       **({'entry':route['entry'],'exit':route['exit'],'enter_required':route['enter_required']} if route else {})})
    return result
