"""Explicit aviation inputs and account validation; never a flight/effects executor."""
import copy
import math
import re
from . import missions

FORMAT='explicit-air-assets-1'
STATE_VERSION='afsim-air-assets-2'
DEFAULT_RULES={'package':2,'fuel_per_aircraft':2,'preparation_s':60,'speed_mps':120,
    'altitude_m':3000,'target_radius_km':.5,'personnel_per_effective_aircraft':8,
    'equipment_per_effective_aircraft':1}
COUNTS=('committed','ready','destroyed','sorties','ordnance','fuel')
META=('name','team','historical_unit_id')


def _fields(value,keys,message):
    if not isinstance(value,dict):raise ValueError(message+'；必须为对象')
    if set(value)!=set(keys):
        raise ValueError(message+'；缺少字段='+str(sorted(set(keys)-set(value),key=str))
                         +'；多余字段='+str(sorted(set(value)-set(keys),key=str)))


def _number(value,low,high,integer=False):
    if type(value) not in ((int,) if integer else (int,float)) or not math.isfinite(value) or not low<=value<=high:
        raise ValueError('航空参数必须为有界有限数值；数量须为非布尔整数')


def validate_definition(value):
    _fields(value,{'format','pools'},'航空输入字段非法')
    if value['format']!=FORMAT or not isinstance(value['pools'],dict) or not 1<=len(value['pools'])<=32:
        raise ValueError('航空输入版本或资源池数量非法')
    for identity,pool in value['pools'].items():
        if not isinstance(identity,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}',identity):
            raise ValueError('航空资源池ID非法')
        _fields(pool,{'name','team','historical_unit_id','initial','entry','rules','assumption','evidence'}
                |({'availability'} if 'availability' in pool else set()),'航空资源池字段非法')
        if 'availability' in pool:
            from . import air_availability
            air_availability.validate(pool['availability'])
        if (not isinstance(pool['name'],str) or not pool['name'].strip() or len(pool['name'])>160
                or pool['team'] not in ('red','blue') or pool['historical_unit_id']!=identity):
            raise ValueError('航空身份或阵营非法')
        if not isinstance(pool['assumption'],str) or not pool['assumption'].strip():raise ValueError('航空估计须说明依据与范围')
        if not isinstance(pool['evidence'],list) or not pool['evidence']:raise ValueError('航空身份缺少来源')
        for evidence in pool['evidence']:
            if not isinstance(evidence,dict) or not evidence.get('source_id') or not evidence.get('locator'):
                raise ValueError('航空来源定位非法')
        _fields(pool['initial'],{'committed','ordnance','fuel'},'航空初始投入字段非法')
        for k,v in pool['initial'].items():_number(v,0,10000000 if k!='committed' else 100000,True)
        _fields(pool['entry'],{'lat','lng'},'航空入场点字段非法')
        _number(pool['entry']['lat'],-90,90);_number(pool['entry']['lng'],-180,180)
        rules=pool['rules'];_fields(rules,DEFAULT_RULES,'航空规则字段非法')
        _number(rules['package'],1,100,True);_number(rules['fuel_per_aircraft'],1,100000,True)
        _number(rules['preparation_s'],0,86400);_number(rules['speed_mps'],1,1500)
        _number(rules['altitude_m'],1,30000);_number(rules['target_radius_km'],.001,20)
        for k in ('personnel_per_effective_aircraft','equipment_per_effective_aircraft'):_number(rules[k],0,10000,True)
    return True


def aggregate(pools):
    result={team:{k:0 for k in COUNTS} for team in ('red','blue')}
    for pool in pools.values():
        for k in COUNTS:result[pool['team']][k]+=pool[k]
    return result


def initial(definition):
    validate_definition(definition)
    pools={identity:{**{k:copy.deepcopy(p[k]) for k in META},'committed':p['initial']['committed'],
        'ready':p['initial']['committed'],'destroyed':0,'sorties':0,
        'ordnance':p['initial']['ordnance'],'fuel':p['initial']['fuel']} for identity,p in definition['pools'].items()}
    return {'version':STATE_VERSION,'config_hash':missions.digest(definition),
        'assumptions':'具名航空资源；缺载数量、入场点、油弹工作量与效能为显式估计，非历史实到量或武器标定。',
        'pools':pools,'assets':aggregate(pools),'missions':[],'recent_missions':[],'last_turn':0}


def validate_state(definition,state):
    validate_definition(definition)
    _fields(state,{'version','config_hash','assumptions','pools','assets','missions','recent_missions','last_turn'},'航空状态字段非法')
    if state['version']!=STATE_VERSION or state['config_hash']!=missions.digest(definition):raise ValueError('航空模型版本或冻结参数已改变')
    if not isinstance(state['assumptions'],str) or not state['assumptions'].strip():raise ValueError('航空来源说明缺失')
    if not isinstance(state['pools'],dict) or set(state['pools'])!=set(definition['pools']):raise ValueError('航空部队资源池丢失或被替换')
    for identity,pool in state['pools'].items():
        spec=definition['pools'][identity];_fields(pool,{*COUNTS,*META},'航空资源账字段非法')
        if any(pool[k]!=spec[k] for k in META):raise ValueError('航空身份或阵营在推演中被改写')
        for k in COUNTS:_number(pool[k],0,10**12,True)
        if pool['committed']!=spec['initial']['committed'] or pool['ready']+pool['destroyed']!=pool['committed']:
            raise ValueError('航空飞机账不守恒')
        if any(pool[k]>spec['initial'][k] for k in ('ordnance','fuel')):raise ValueError('航空库存超过本局初始投入')
    _fields(state['assets'],{'red','blue'},'航空阵营汇总字段非法')
    for pool in state['assets'].values():
        _fields(pool,COUNTS,'航空阵营汇总字段非法')
        for k in COUNTS:_number(pool[k],0,10**12,True)
    if state['assets']!=aggregate(state['pools']):raise ValueError('航空阵营汇总与逐部队资源账不符')
    for key,limit in (('missions',256),('recent_missions',16)):
        if not isinstance(state[key],list) or len(state[key])>limit:raise ValueError('航空任务列表非法')
    _number(state['last_turn'],0,10**12,True)
    return True


def select(definition,state,team,pool_id=None):
    validate_state(definition,state)
    ids=[identity for identity,p in definition['pools'].items() if p['team']==team]
    if pool_id is None:
        if not ids:raise ValueError('本方没有登记航空兵力')
        if len(ids)!=1:raise ValueError('本方有多个航空资源池，请明确air_pool ID')
        pool_id=ids[0]
    if not isinstance(pool_id,str) or pool_id not in ids:raise ValueError('航空资源池未知或不属于本方')
    return pool_id,copy.deepcopy(definition['pools'][pool_id])


def world_definition(world):
    return world.get('mission',{}).get('definition',{}).get('air_definition')


def world_state(world):
    definition=world_definition(world)
    if definition is None:return None
    value=world.get('air_operations')
    if value is None:value=initial(definition)
    validate_state(definition,value)
    return copy.deepcopy(value)


def available(world,team):
    """Bounded choices for command validation/observation, not a reservation."""
    definition=world_definition(world)
    if definition is None:return []
    state=world_state(world);result=[]
    for identity,spec in definition['pools'].items():
        if spec['team']!=team:continue
        from . import air_availability
        if air_availability.status(world,spec)!='active':continue
        pool=state['pools'][identity];cfg=spec['rules'];n=cfg['package']
        if pool['ready']>=n and pool['ordnance']>=n and pool['fuel']>=n*cfg['fuel_per_aircraft']:
            result.append({'id':identity,'name':spec['name'],'package':n})
    return result
