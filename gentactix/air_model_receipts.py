"""Validate DSH-proposed aviation receipts; no flight or damage calculation.

The model supplies outcomes AND resource balances. The host only checks identities,
causal links and conservation, and labels these estimates separately from WSF.
"""
import copy
import hashlib
from . import air_assets,missions


def package_cost(spec,outcome):
    """A resource quote, not a flight or damage outcome."""
    if outcome not in ('strike','aborted'):raise ValueError('未知航空任务结算类型')
    n=spec['rules']['package']
    return dict(sorties=n,ordnance=n if outcome=='strike' else 0,fuel=n*spec['rules']['fuel_per_aircraft'])


def resource_context(world):
    definition=air_assets.world_definition(world)
    if definition is None:return None
    from . import air_availability
    state=air_assets.world_state(world)
    return dict(source='current_configured_air_resources',turn=state['last_turn'],
        scope='当前运行计数及单任务资源报价；不是历史实力或固定航空战果，分队份额不缩放共享航空池',
        pools={identity:dict(current={k:pool[k] for k in ('ready','destroyed','sorties','ordnance','fuel')},
            availability=air_availability.status(world,definition['pools'][identity]),
            per_package={outcome:package_cost(definition['pools'][identity],outcome) for outcome in ('strike','aborted')})
            for identity,pool in state['pools'].items()})


def validate(before, after, proposal, orders, seconds):
    definition=air_assets.world_definition(before)
    if definition is None:
        if proposal is not None:raise ValueError('本局没有具名航空资源，不能提交航空资源变化')
        return None
    prior=air_assets.world_state(before);value=copy.deepcopy(prior)
    requested={o['unit']:o for o in orders if o['action']=='air_support'}
    if proposal is None:
        if requested:raise ValueError('航空命令缺少模型任务回执和独立资源收支，不能免费空袭')
        value.update(missions=[],last_turn=before['mission']['turn']+1)
        return value
    air_assets._fields(proposal,{'pools','missions'},'航空模型回执字段非法')
    air_assets._fields(proposal['pools'],definition['pools'],'航空模型回执须覆盖全部航空资源池')
    for identity,pool in proposal['pools'].items():
        air_assets._fields(pool,{'ready','destroyed','sorties','ordnance','fuel'},'航空模型收支字段非法')
        for amount in pool.values():air_assets._number(amount,0,10**12,True)
        value['pools'][identity].update(copy.deepcopy(pool))
    value['assets']=air_assets.aggregate(value['pools'])
    receipts=proposal['missions']
    if not isinstance(receipts,list) or len(receipts)!=len(requested):raise ValueError('航空模型任务须与本轮航空命令逐项对应')
    units={u['name']:(team,u) for team,u in missions.units(before)}
    current={u['name']:u for _,u in missions.units(after)}
    expected=copy.deepcopy(prior['pools']);tasks=[];seen=set();effects={}
    for receipt in receipts:
        air_assets._fields(receipt,{'requester','target','pool_id','outcome','aircraft_lost','personnel_effect','equipment_effect','events'},'航空任务模型回执字段非法')
        name=receipt['requester']
        if not isinstance(name,str) or name not in requested or name in seen:raise ValueError('航空任务重复或没有对应下令单位')
        seen.add(name);order=requested[name];team=units[name][0]
        identity,spec=air_assets.select(definition,prior,team,order.get('air_pool'))
        if receipt['pool_id']!=identity or receipt['target']!=order['target']:raise ValueError('航空任务与命令的资源池或目标不一致')
        cfg=spec['rules'];n=cfg['package'];outcome=receipt['outcome']
        if outcome not in ('strike','aborted'):raise ValueError('航空任务必须完成打击或中止后返场')
        for key,high in (('aircraft_lost',n),('personnel_effect',n*cfg['personnel_per_effective_aircraft']),('equipment_effect',n*cfg['equipment_per_effective_aircraft'])):
            air_assets._number(receipt[key],0,high,True)
        survivors=n-receipt['aircraft_lost']
        if (receipt['personnel_effect']>survivors*cfg['personnel_per_effective_aircraft'] or
                receipt['equipment_effect']>survivors*cfg['equipment_per_effective_aircraft']):
            raise ValueError('航空战果超过通过防空后的有效飞机预算')
        if any(receipt[k] for k in ('personnel_effect','equipment_effect')) and not any(
                e.get('attacker')==name and e.get('weapon_action')=='air_support' and e.get('target',order['target'])==order['target']
                for e in after.get('engagements',[])):
            raise ValueError('航空战果缺少对应目标的交战记录')
        if outcome=='aborted' and any(receipt[k] for k in ('aircraft_lost','personnel_effect','equipment_effect')):
            raise ValueError('中止任务不能产生航空战果')
        events=receipt['events'];phases=['launch','air_defense','strike','returned'] if outcome=='strike' else ['launch','abort_target_moved','returned']
        if not isinstance(events,list) or len(events)!=len(phases):raise ValueError('航空任务缺少完整起飞、目标处理和返场过程')
        target=units[order['target']][1];aim={k:target[k] for k in ('lat','lng')}
        last=-1
        for event,phase in zip(events,phases):
            air_assets._fields(event,{'phase','seconds','lat','lng'},'航空模型事件字段非法')
            air_assets._number(event['seconds'],0,seconds);air_assets._number(event['lat'],-90,90);air_assets._number(event['lng'],-180,180)
            point=spec['entry'] if phase in ('launch','returned') else aim
            if event['phase']!=phase or event['seconds']<last or missions.distance(event,point)>.1:
                raise ValueError('航空任务事件顺序或位置不符；不能虚构到达与返场')
            last=event['seconds']
        travel=missions.distance(spec['entry'],aim)*1000/cfg['speed_mps']
        if events[0]['seconds']<cfg['preparation_s'] or events[1]['seconds']+1<events[0]['seconds']+travel or events[-1]['seconds']+1<events[-2]['seconds']+travel:
            raise ValueError('航空任务超过回合或短于准备与航路所需时间')
        from . import air_availability
        air_availability.require(before,spec,events[-1]['seconds'])
        pool=expected[identity];pool['ready']-=receipt['aircraft_lost'];pool['destroyed']+=receipt['aircraft_lost']
        cost=package_cost(spec,outcome)
        pool['sorties']+=cost['sorties'];pool['ordnance']-=cost['ordnance'];pool['fuel']-=cost['fuel']
        if pool['ready']<0 or pool['ordnance']<0 or pool['fuel']<0:raise ValueError('航空任务超出该部队的飞机或独立油弹')
        # Concurrent reservations cannot reuse aircraft that already flew in this turn.
        used=sum(t['package'] for t in tasks if t['pool_id']==identity)+n
        if used>prior['pools'][identity]['ready']:raise ValueError('航空任务重复占用同一批飞机')
        turn=before['mission']['turn']+1
        tasks.append({**copy.deepcopy(receipt),'id':'dsha-'+hashlib.sha256(f'{turn}:{name}:{identity}'.encode()).hexdigest()[:20],
            'team':team,'turn':turn,'package':n,'entry':copy.deepcopy(spec['entry']),'aim':aim,'altitude_m':cfg['altitude_m'],
            'source':'dsh_model_estimate','status':'returned','hit':outcome=='strike',
            'ordnance_spent':n if outcome=='strike' else 0,'fuel_spent':n*cfg['fuel_per_aircraft'],
            'effect_basis':'DSH提交的航空过程与战果估计；宿主只校验命令、航路边界及收支，不代表AFSIM原生执行或历史标定'})
        target_effect=effects.setdefault(order['target'],[0,0]);target_effect[0]+=receipt['personnel_effect'];target_effect[1]+=receipt['equipment_effect']
    if value['pools']!=expected:
        differences=[f'{identity}.{key}：提交{value["pools"][identity][key]}，应为{pool[key]}（期初{prior["pools"][identity][key]}）'
            for identity,pool in expected.items() for key in ('ready','destroyed','sorties','ordnance','fuel')
            if value['pools'][identity][key]!=pool[key]]
        detail='；'.join(differences[:16])+(f'；另有{len(differences)-16}项差额' if len(differences)>16 else '')
        raise ValueError('航空库存与模型任务收支不守恒：'+detail+'。sorties为累计架次，按package增加；共享航空池不乘地面分队份额。请修正候选，不补造库存。')
    for name,(personnel,equipment) in effects.items():
        original=units[name][1];unit=current[name]
        loss=unit['personnel']['casualties']-original['personnel']['casualties']
        destroyed=sum(e['destroyed'] for e in unit['equipment'])-sum(e['destroyed'] for e in original['equipment'])
        ground=any(o.get('target')==name and o['action'] in ('fire','bombard','suppress') for o in orders)
        captured=0
        if before['mission']['definition'].get('campaign_definition') and any(o.get('target')==name and o['action']=='capture' for o in orders):
            from . import combat_effects
            delta=combat_effects._count_delta(original['personnel'],unit['personnel'],'captured')
            if delta is not None:captured=delta
        # Campaign validation subsequently binds this delta to a valid receiving
        # unit, range and current-turn capture receipt. No raw air claim grants it.
        combat_loss=loss-captured
        if personnel>combat_loss or equipment>destroyed or not ground and (personnel!=combat_loss or equipment!=destroyed):
            raise ValueError(name+'：航空战果与目标实际变化不一致：航空人员效应/新增战斗减员='+str(personnel)+'/'+str(loss)
                +'，另有待战役校验的受降='+str(captured)
                +'，航空装备效应/新增毁坏='+str(equipment)+'/'+str(destroyed)
                +'。equipment_effect只计新增destroyed，不含待修damaged；双方账须对应，不自动改写')
        for task in tasks:
            if task['target']==name:
                task['target_turn_effects']={'basis':'同目标当轮DSH估计合计，不跨任务相加','air_casualties':personnel,
                    'ground_casualties':loss-personnel-captured,'captured':captured,'air_equipment_destroyed':equipment}
    value.update(missions=tasks,recent_missions=(prior.get('recent_missions',[])+copy.deepcopy(tasks))[-16:],last_turn=before['mission']['turn']+1)
    air_assets.validate_state(definition,value)
    return value


def instruction(world):
    import json
    definition=air_assets.world_definition(world)
    if definition is None:return ''
    return ('\n具名航空计算参数：'+json.dumps(definition,ensure_ascii=False)
        +'\n航空当前资源与单任务报价：'+json.dumps(resource_context(world),ensure_ascii=False)
        +'\n航空命令用air_support并附敌方target和本方air_pool；不得调用无资源阵营。油弹独立记账，不扣请求者地面ammo。'
        '有航空命令时返回aviation={"pools":{"池ID":{"ready":0,"destroyed":0,"sorties":0,"ordnance":0,"fuel":0}},'
        '"missions":[{"requester":"下令单位精确名","target":"命令目标","pool_id":"池ID","outcome":"strike或aborted",'
        '"aircraft_lost":0,"personnel_effect":0,"equipment_effect":0,"events":[{"phase":"launch","seconds":60,"lat":0,"lng":0}]}]}。'
        'pools覆盖全部池并填写任务后余额；每任务增加package架次，消耗package×fuel_per_aircraft燃油；投弹消耗package弹药，中止不投弹。'
        'ready+destroyed守恒，不能跨池借用；同轮任务包总数不大于轮初ready。missions逐项对应所有航空命令，requester不重复。'
        'events完整顺序为launch、air_defense、strike、returned；中止则launch、abort_target_moved、returned。'
        '坐标为登记entry→轮初target点→entry，seconds为本轮偏移，满足preparation_s及各段距离/speed_mps且完成于回合内。'
        '如航空池声明availability，必须在其可用时段开始后下令，并在end之前返场；未到场和已退出资源不能借用，end为空才表示持续可用。'
        'personnel_effect为目标本轮航空战斗减员，equipment_effect只计新增destroyed，不含待修damaged，须与unit_updates和air_support交战对应。'
        'personnel.casualties是整数合计，killed/wounded等与casualties同级，绝不在casualties内嵌分类对象。'
        '中止任务的效应和飞机损失为0。交战weapon_action必须为air_support；不能以bombard表示航空投弹，bombard是地面间瞄火力。不填宿主派生id/source等字段，不声称原生AFSIM执行。无任务可省略aviation，不能产生航空战果。')
