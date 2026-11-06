"""Frozen ferry inputs and receipt validation. No transport/turn executor."""
import copy
import math
import re

from . import crossings, missions

VERSION = 'formation-ferry-1'
PHASES = ('idle', 'loading', 'outbound', 'unloading', 'returning')
FIELDS = {'id', 'lat', 'lng', 'bank', 'from_bank', 'phase', 'remaining_s',
          'passenger', 'manifest_personnel', 'manifest_equipment_work', 'trips'}


def configuration_template():
    return {'version':VERSION,'assumption':'待说明舟艇能力估计；不是史实船型。','boats':[
        {**{key:None for key in ('id','name','team','seats','equipment_work_capacity','speed_mps',
                                'load_seconds','unload_seconds','initial_bank')},
         'assumption':'待填写计算舟艇及能力依据，不是已生成的船舶。'}]}


def config(world):
    return (crossings.get_model(world) or {}).get('ferry')


def validate_config(value):
    crossings.fields(value, {'version', 'boats', 'assumption'}, '舟艇配置')
    if value['version'] != VERSION or not isinstance(value['assumption'], str) or not value['assumption'].strip():
        raise ValueError('舟艇模型须声明版本和能力估计依据')
    if not isinstance(value['boats'], list) or not 1 <= len(value['boats']) <= 8:
        raise ValueError('每处渡口须明确1至8艘计算舟艇')
    seen = set()
    for boat in value['boats']:
        crossings.fields(boat, {'id', 'name', 'team', 'seats', 'equipment_work_capacity', 'speed_mps',
                               'load_seconds', 'unload_seconds', 'initial_bank', 'assumption'}, '舟艇能力')
        if (not isinstance(boat['id'], str) or not re.fullmatch('[a-z0-9_]{1,32}', boat['id'])
                or boat['id'] in seen or boat['team'] not in ('red', 'blue') or boat['initial_bank'] not in ('a', 'b')):
            raise ValueError('舟艇身份、归属或初始岸点非法')
        seen.add(boat['id'])
        for key in ('name', 'assumption'):
            if not isinstance(boat[key], str) or not boat[key].strip() or len(boat[key]) > 2000:
                raise ValueError('舟艇名称和估计依据不能为空')
        crossings.number(boat['seats'], 1, 10000, True)
        crossings.number(boat['equipment_work_capacity'], 0, 100000)
        crossings.number(boat['speed_mps'], .01, 30)
        for key in ('load_seconds', 'unload_seconds'):
            crossings.number(boat[key], 1, 86400)


def initialize(world):
    value = config(world)
    if value is None:
        return
    validate_config(value)
    banks = crossings.get_model(world)['banks']
    world['combined_arms']['bridge']=copy.deepcopy(world['combined_arms']['bridge'])
    world['combined_arms']['bridge']['ferry_state'] = {'version': VERSION, 'turn': 0,
        'source': 'input_estimate', 'events': [], 'boats': [
            {'id': b['id'], **copy.deepcopy(banks[b['initial_bank']]), 'bank': b['initial_bank'],
             'from_bank': b['initial_bank'], 'phase': 'idle', 'remaining_s': 0, 'passenger': None,
             'manifest_personnel': 0, 'manifest_equipment_work': 0, 'trips': 0} for b in value['boats']]}


def state(world):
    return world.get('combined_arms', {}).get('bridge', {}).get('ferry_state')


def carrier(world, name):
    return next((b for b in (state(world) or {}).get('boats', []) if b['passenger'] == name), None)


def validate(world):
    value, actual = config(world), state(world)
    if value is None:
        if actual is not None:
            raise ValueError('无冻结舟艇配置，不能迁入舟艇状态')
        return
    validate_config(value)
    crossings.fields(actual, {'version', 'turn', 'source', 'events', 'boats'}, '舟艇回执')
    if actual['version'] != VERSION or actual['source'] not in ('input_estimate', 'afsim_native_estimate', 'dsh_model_estimate'):
        raise ValueError('舟艇回执版本或来源非法')
    crossings.number(actual['turn'], 0, 10**9, True)
    if not isinstance(actual['boats'], list) or [b.get('id') for b in actual['boats']] != [b['id'] for b in value['boats']]:
        raise ValueError('舟艇身份或数量被改写')
    units = {u['name']: (team, u) for team, u in missions.units(world)}
    banks = crossings.get_model(world)['banks']
    passengers = set()
    for boat, spec in zip(actual['boats'], value['boats']):
        crossings.fields(boat, FIELDS, '舟艇状态')
        crossings.point({k: boat[k] for k in ('lat', 'lng')})
        if boat['phase'] not in PHASES or boat['bank'] not in ('a', 'b') or boat['from_bank'] not in ('a', 'b'):
            raise ValueError('舟艇阶段或岸点非法')
        near_origin = boat['phase'] in ('idle', 'loading', 'outbound')
        if (boat['bank'] == boat['from_bank']) != near_origin:
            raise ValueError(boat['id']+'.bank/from_bank与阶段不符；from_bank保留该次原始出发岸，登陆后不能改成出口岸')
        crossings.number(boat['remaining_s'], 0, 86400)
        if boat['phase'] not in ('loading','unloading') and boat['remaining_s']!=0:
            raise ValueError(boat['id']+'.remaining_s仅表示装卸等待；idle/outbound/returning必须为0，不是剩余航程秒数')
        crossings.number(boat['manifest_personnel'], 0, spec['seats'], True)
        crossings.number(boat['manifest_equipment_work'], 0, spec['equipment_work_capacity'])
        crossings.number(boat['trips'], 0, 10**9, True)
        if crossings.path_position(banks['a'], [banks['b']], boat, .002) is None:
            raise ValueError('舟艇位置不在登记水上通道')
        if boat['phase'] in ('idle','loading','unloading') and missions.distance(boat,banks[boat['bank']])>.002:
            raise ValueError('靠岸、装卸状态的舟艇不能在河中漂移')
        loaded = boat['phase'] in ('loading', 'outbound', 'unloading')
        if loaded:
            name = boat['passenger']
            if not isinstance(name, str) or name not in units or name in passengers or units[name][0] != spec['team']:
                raise ValueError('乘载编组不存在、重复登船或舟艇归属不符')
            passengers.add(name)
            unit = units[name][1]
            equipment_work=sum(e['operational']*crossings.get_model(world)['equipment_work'][e['category']] for e in unit['equipment'])
            if boat['manifest_equipment_work']+.001<equipment_work:raise ValueError('舟艇载荷漏记可用装备')
            if boat['manifest_personnel'] < unit['personnel']['current'] or boat['manifest_personnel'] > unit['personnel']['committed']:
                raise ValueError('舟艇乘载人数与编组不守恒')
            if boat['phase'] != 'loading' and missions.distance(unit, boat) > .002:
                raise ValueError('登船后编组须与实际舟位一致，不能独立走过河')
        elif boat['passenger'] is not None or boat['manifest_personnel'] or boat['manifest_equipment_work']:
            raise ValueError('空艇或返航不得保留乘客/重复载荷')
    if not isinstance(actual['events'], list) or len(actual['events']) > 10000:
        raise ValueError('舟艇事件必须有界')
    for event in actual['events']:
        crossings.fields(event, {'boat_id', 'unit', 'phase', 'seconds', 'lat', 'lng'}, '舟艇事件')
        if event['boat_id'] not in {b['id'] for b in value['boats']} or event['phase'] not in ('loading', 'boarded', 'landed', 'returned', 'cancelled', 'repositioning'):
            raise ValueError('舟艇事件身份或阶段非法')
        if event['unit'] is not None and event['unit'] not in units:
            raise ValueError('舟艇事件引用未知编组')
        crossings.number(event['seconds'], 0, 31*86400)
        crossings.point({k: event[k] for k in ('lat', 'lng')})


def can_board(world, unit, boat):
    model = crossings.get_model(world)
    work = sum(e['operational']*model['equipment_work'][e['category']] for e in unit['equipment'])
    return unit['personnel']['current'] <= boat['seats'] and work <= boat['equipment_work_capacity']


def observation(world):
    if config(world) is None:
        return None
    banks=crossings.get_model(world)['banks']
    return {'config': copy.deepcopy(config(world)), 'state': copy.deepcopy(state(world)),
            'static_bounds':{'bank_distance_m':round(missions.distance(banks['a'],banks['b'])*1000,3),
              'boats':[{'id':b['id'],'one_way_min_s':math.ceil(missions.distance(banks['a'],banks['b'])*1000/b['speed_mps']),
                        'remaining_route_m':round(missions.distance(s,banks['b' if s['from_bank']=='a' else 'a'] if s['phase']=='outbound' else banks[s['from_bank']])*1000,3)}
                        for b,s in zip(config(world)['boats'],state(world)['boats'])]},
            'scope': '显式计算舟艇；人员/装备随所属分队，不额外生成船员兵力；未建波浪、水流、沉船、船上射击与仓库货运。'}


def route(world, unit, target):
    if config(world) is None:
        return None
    return crossings.plan(world['combined_arms']['bridge'], unit, target)


def ground_distance(world, unit, target):
    path = route(world, unit, target)
    if path is None:
        return missions.distance(unit, target)
    if not carrier(world, unit['name']):
        team = next(t for t,u in missions.units(world) if u['name']==unit['name'])
        if not any(b['team']==team and can_board(world,unit,b) for b in config(world)['boats']):
            raise ValueError('计算分队人数或装备超出全部己方舟艇容量；请在初态划分可乘载分队或核对艇能力')
    m=crossings.get_model(world)
    bank='b' if path['task']['from_bank']=='a' else 'a'
    if crossings.orientation(target,m['barrier']['a'],m['barrier']['b'])*crossings.orientation(m['banks'][bank],m['barrier']['a'],m['barrier']['b'])<=0:
        raise ValueError('舟艇目的地必须位于出口岸一侧')
    return (missions.distance(unit,path['entry']) if path['enter_required'] else 0)+missions.distance(path['exit'],target)


def step_target(world, unit, target, ground_budget):
    path=route(world,unit,target)
    if path is None:
        return None
    from .commands import towards
    approach=missions.distance(unit,path['entry']) if path['enter_required'] else 0
    if approach>ground_budget:
        return towards(unit,path['entry'],ground_budget)
    return towards(path['exit'],target,max(0,ground_budget-approach))


def validate_transition(before, after, updates, orders, seconds, result):
    """Check model-declared transport evidence; never generate boat motion."""
    old_state=state(before); supplied=(result.get('combined_arms') or {}).get('bridge',{}).get('ferry_state')
    if supplied is None:
        if any(b['phase']!='idle' for b in old_state['boats']) or any(o['action']=='move' and route(before,next(u for _,u in missions.units(before) if u['name']==o['unit']),o) for o in orders):
            raise ValueError('舟艇作业须提交完整ferry_state及登乘/登岸事件，不得退回普通走河')
        following=copy.deepcopy(old_state);following['events']=[]
    else:
        following=copy.deepcopy(supplied)
    following.update(source='dsh_model_estimate',turn=before['mission']['turn']+1)
    after['combined_arms']['bridge']['ferry_state']=following
    validate(after)
    by_name={u['name']:(t,u) for t,u in missions.units(before)}
    commanded={o['unit']:o for o in orders}
    boarded={};landed=set();cancelled=set()
    model=crossings.get_model(before);bank_distance=missions.distance(model['banks']['a'],model['banks']['b'])*1000
    entry_limits={r['unit']:r for r in crossings.observation(before)['unit_limits']}
    for old,new,spec in zip(old_state['boats'],following['boats'],config(before)['boats']):
        if missions.distance(old,new)*1000>spec['speed_mps']*seconds+2:
            raise ValueError('舟艇位移超出船速和回合时间')
        ev=[e for e in following['events'] if e['boat_id']==old['id']]
        if any(e['seconds']>seconds for e in ev) or any(a['seconds']>b['seconds'] for a,b in zip(ev,ev[1:])):
            raise ValueError('舟艇事件倒序或越出回合')
        phase=old['phase'];passenger=old['passenger'];origin=old['from_bank'];bank=old['bank']
        ready=old['remaining_s'] if phase in ('loading','unloading') else 0
        if phase=='outbound':ready=missions.distance(old,model['banks']['b' if origin=='a' else 'a'])*1000/spec['speed_mps']+spec['unload_seconds']
        if phase=='returning':ready=missions.distance(old,model['banks'][origin])*1000/spec['speed_mps']
        trips=old['trips']
        for event in ev:
            t=event['seconds'];name=event['unit'];kind=event['phase']
            if kind=='repositioning':
                if phase!='idle' or name is not None:raise ValueError('仅空闲空艇可调往另一岸')
                origin='b' if old['bank']=='a' else 'a'
                if not any(o['action']=='move' and by_name[o['unit']][0]==spec['team'] and can_board(before,by_name[o['unit']][1],spec) and (route(before,by_name[o['unit']][1],o) or {}).get('task',{}).get('from_bank')==origin for o in orders):
                    raise ValueError('空艇调岸缺少对岸登乘请求')
                phase='returning';ready=t+bank_distance/spec['speed_mps']
            elif kind=='loading':
                if phase!='idle' or name not in commanded or commanded[name]['action']!='move':raise ValueError('登乘没有己方已确认渡运命令')
                team,u=by_name[name];path=route(before,u,commanded[name])
                if path is None or team!=spec['team'] or not can_board(before,u,spec):raise ValueError('登乘超载或方向不属于当前舟艇')
                origin=path['task']['from_bank']
                if bank!=origin:raise ValueError('舟艇尚未调到登乘岸，不能隔岸装载')
                if missions.distance(event,model['banks'][origin])>.002:raise ValueError('登乘不在入口岸')
                if t+1<entry_limits[name]['entry_earliest_s'][origin]:raise ValueError('登乘早于命令交付和实际抵达入口')
                passenger=name;phase='loading';ready=t+spec['load_seconds']
            elif kind=='boarded':
                if phase!='loading' or name!=passenger or t+1<ready or name in boarded:raise ValueError('未完成装载、重复或错误登船')
                if missions.distance(event,model['banks'][origin])>.002:raise ValueError('登船离开了登记岸点')
                boarded[name]=event;phase='outbound';ready=t+bank_distance/spec['speed_mps']+spec['unload_seconds']
            elif kind=='landed':
                if phase not in ('outbound','unloading') or name!=passenger:
                    raise ValueError('登岸缺少对应载客航行或卸载状态')
                if t+1<ready:
                    raise ValueError(old['id']+' landed登记为'+str(t)+'秒，最早须到'+format(ready,'.3f')+
                                     '秒才完成卸载；到岸时刻不是landed，单位exited也须在卸载完成后')
                if missions.distance(event,model['banks']['b' if origin=='a' else 'a'])>.002:raise ValueError('未在出口岸登岸')
                landed.add(name);passenger=None;trips+=1;phase='returning';bank='b' if origin=='a' else 'a';ready=t+bank_distance/spec['speed_mps']
            elif kind=='returned':
                if phase!='returning' or name is not None or t+1<ready:raise ValueError('未完成空艇返航')
                if missions.distance(event,model['banks'][origin])>.002:raise ValueError('空艇未返回原岸')
                phase='idle';bank=origin
            elif kind=='cancelled':
                order=commanded.get(name,{})
                if phase!='loading' or name!=passenger or not order.get('cancel_crossing'):raise ValueError('装载撤销缺少已确认取消')
                cancelled.add(name);phase='idle';passenger=None
        if not (new['phase']==phase or phase=='outbound' and new['phase']=='unloading'):
            raise ValueError(old['id']+'.phase与已声明事件不符，事件后为'+phase+'；不要凭空补调艇事件来表示连续航行')
        if new['passenger']!=passenger:
            raise ValueError(old['id']+'.passenger与登乘事件不符；预期'+repr(passenger))
        if new['from_bank']!=origin:
            raise ValueError(old['id']+'.from_bank须保持'+origin+'；这是原始出发岸/空艇返航目标，不是最新到达岸')
        expected_bank=('b' if origin=='a' else 'a') if new['phase']=='unloading' else bank
        if new['bank']!=expected_bank:
            raise ValueError(old['id']+'.bank须为'+expected_bank+'，与实际抵岸事件不符')
        if new['trips']!=trips:
            raise ValueError(old['id']+'.trips='+str(new['trips'])+'，期望'+str(trips)+'；只在landed后增加完成航次，boarded或正在航行不增加')
        if new['phase']=='loading' and abs(new['remaining_s']-max(0,ready-seconds))>2:
            raise ValueError('装载等待时间不连续')
        if new['phase']=='unloading' and (new['remaining_s']>spec['unload_seconds'] or new['remaining_s']+seconds+1<ready):
            raise ValueError('卸载剩余时间不符合航行预算')
        if old['phase'] in ('outbound','returning') and new['phase']==old['phase'] and not ev:
            end_bank=('b' if origin=='a' else 'a') if old['phase']=='outbound' else origin
            required=min(missions.distance(old,model['banks'][end_bank])*1000,spec['speed_mps']*seconds)
            if missions.distance(old,new)*1000+2<required:raise ValueError('已启航的舟艇不得整轮无故停留或遗漏航程')
        if old['phase']=='idle' and new['phase']=='idle' and not ev:
            for order in orders:
                if order['action']!='move':continue
                team,u=by_name[order['unit']];path=route(before,u,order)
                if path and team==spec['team'] and can_board(before,u,spec) and entry_limits[u['name']]['entry_earliest_s'][path['task']['from_bank']]<seconds-1:
                    raise ValueError('有可达入口的适载渡运请求，空艇不能无故整轮零作业；应装载或空艇调岸')
    used=0
    for name,(team,u) in by_name.items():
        order=commanded.get(name,{'action':'hold'});path=route(before,u,order) if order['action']=='move' else None
        prior=path['task'] if path else u.get('crossing')
        if prior is None:
            if name in updates:raise ValueError('无舟艇渡运任务却提交渡运状态')
            continue
        values=updates.get(name,{})
        if not isinstance(values,dict) or set(values)-{'served_work','last_work','status','events'}:
            raise ValueError('舟艇任务只允许提交工作量、状态和岸点事件')
        task={**copy.deepcopy(prior),**copy.deepcopy(values),'source':'dsh_model_estimate','turn':before['mission']['turn']+1}
        if not values:task.update(last_work=0,events=[])
        crossings.validate_task(after['combined_arms']['bridge'],task)
        delta=prior['required_work']-prior['served_work'] if name in boarded else 0
        if abs(task['last_work']-delta)>.002 or abs(task['served_work']-prior['served_work']-delta)>.002:raise ValueError('登船容量与任务工作量不守恒')
        boat=carrier(after,name)
        expected='completed' if name in landed else 'cancelled' if name in cancelled else 'transit' if boat and boat['phase'] in ('outbound','unloading') else prior['status']
        if task['status']!=expected:raise ValueError('任务通过状态与舟艇登岸证据不符')
        after_u=next(v for _,v in missions.units(after) if v['name']==name)
        after_u['crossing']=task;used+=delta
        if path and crossings.path_position(u,path['waypoints'],after_u) is None:raise ValueError('乘客位置偏离登记路径')
    if crossings.cargo_work(before,after,result,seconds)>0:raise ValueError('舟艇版本尚未实现仓库跨河货运，不得填造到货')
    capacity=(result.get('combined_arms') or {}).get('bridge',{}).get('crossing_receipt')
    budget=model['throughput_work_per_hour']*seconds/3600
    if capacity is None or set(capacity)!={'used_work','cargo_work','budget_work'} or any(type(v) not in (int,float) or not math.isfinite(v) for v in capacity.values()):
        raise ValueError('舟艇须提交有限容量总账')
    if abs(capacity['used_work']-used)>.002 or capacity['cargo_work'] or abs(capacity['budget_work']-budget)>.002 or used>budget+.002:
        raise ValueError('舟艇总账：used_work须等于本轮登船工作量'+str(used)+'，cargo_work须为0；budget_work须为吞吐每小时×'+str(seconds)+'/3600='+str(budget))
    after['combined_arms']['bridge']['crossing_receipt']={**capacity,'turn':before['mission']['turn']+1,'source':'dsh_model_estimate','scope':'登船已占用容量，完成渡河还须实际航行和卸载；DSH估计'}
