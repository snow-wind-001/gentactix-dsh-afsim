"""Construction work contracts and read-only conservation checks, never an executor.

One work unit is one model point times one committed-person equivalent. Packet
credit is physical prepaid work and must be apportioned when a formation splits;
it is not copied like an intensive entrenchment value. Rates are explicit model
estimates and do not establish historical labour, material mass or effectiveness.
"""
import re

VERSION = 'fixed-time-fortification-1'
STATE_VERSION = 'fortification-work-state-1'
RECEIPT_VERSION = 'fortification-work-receipt-1'
SCALE = 1_000_000
CAP = 100*SCALE
HOUR_MS = 3_600_000
MAX_ELAPSED_MS = 31*86_400_000
MAX_EXACT_INTEGER = 2**53-1
STATE_FIELDS = {'version','root_id','root_committed','committed','base_ticks','point_remainder',
                'work_remainder','material_credit_work','materials','intent_id',
                'wait_remaining_ms'}
CONTROL_FIELDS = {'entity_id','configuration','state','current','fortify','intent_id',
                  'command_delay_ms'}
RECEIPT_FIELDS = {'version','entity_id','elapsed_ms','waited_ms','available_ms',
                  'work_added','packets_reserved','discarded_numerator',
                  'cap_excess_micro_work','after'}


def _fields(value, fields, label):
    if not isinstance(value,dict) or set(value)!=fields:
        raise ValueError(label+'字段缺失或越界')


def _integer(value, minimum, maximum, label):
    if type(value) is not int or not minimum<=value<=maximum:
        raise ValueError(label+'须为范围内整数')


def _intent(value):
    if value is not None and (not isinstance(value,str) or re.fullmatch('[a-f0-9]{32}',value) is None):
        raise ValueError('施工意图须为空或明确的32位身份')


def validate_config(value):
    _fields(value,{'version','gain_points_per_hour','material_points_per_packet','assumption'},'分时施工配置')
    if value['version']!=VERSION:
        raise ValueError('分时施工版本非法')
    for key in ('gain_points_per_hour','material_points_per_packet'):
        _integer(value[key],1,10000,key)
    if not isinstance(value['assumption'],str) or not value['assumption'].strip() or len(value['assumption'])>4000:
        raise ValueError('分时施工须明确估计依据')
    return True


def initial_state(*, root_id, root_committed, committed, base_ticks, materials):
    value = dict(version=STATE_VERSION,root_id=root_id,root_committed=root_committed,committed=committed,
                 base_ticks=base_ticks,point_remainder=0,work_remainder=0,
                 material_credit_work=0,materials=materials,intent_id=None,wait_remaining_ms=0)
    validate_state(value)
    return value


def validate_state(value):
    _fields(value,STATE_FIELDS,'施工工作账')
    if value['version']!=STATE_VERSION:
        raise ValueError('施工工作账版本非法')
    if not isinstance(value['root_id'],str) or re.fullmatch('[a-f0-9]{64}',value['root_id']) is None:
        raise ValueError('施工工作账须绑定明确的根编组身份')
    _integer(value['root_committed'],1,10_000_000,'根编组计量人数')
    _integer(value['committed'],1,value['root_committed'],'当前互斥分队计量人数')
    _integer(value['base_ticks'],0,CAP,'工事微分值')
    _integer(value['point_remainder'],0,value['committed']-1,'工事分值除法余量')
    _integer(value['work_remainder'],0,HOUR_MS-1,'施工时间余量')
    _integer(value['material_credit_work'],0,MAX_EXACT_INTEGER,'预付材料工作余额')
    _integer(value['materials'],0,10_000_000,'未拆包工程材料')
    _integer(value['wait_remaining_ms'],0,MAX_ELAPSED_MS,'施工剩余指挥等待')
    _intent(value['intent_id'])
    if value['intent_id'] is None and value['wait_remaining_ms']:
        raise ValueError('空闲施工意图不能保留指挥等待')
    if value['base_ticks']==CAP and (value['point_remainder'] or value['work_remainder']):
        raise ValueError('工事已达上限不能保留可重复兑现的工作进度')
    return True


def stock_work(value, configuration):
    validate_state(value);validate_config(configuration)
    total=(value['materials']*configuration['material_points_per_packet']*value['root_committed']
           +value['material_credit_work'])
    if total>MAX_EXACT_INTEGER:
        raise ValueError('材料工作总量超过Native整数可精确表示范围')
    return total


def validate_control(value):
    _fields(value,CONTROL_FIELDS,'施工原生输入')
    if not isinstance(value['entity_id'],str) or re.fullmatch('g[a-f0-9]{20}',value['entity_id']) is None:
        raise ValueError('施工实体须使用明确的编译身份')
    validate_config(value['configuration']);validate_state(value['state'])
    _integer(value['current'],0,value['state']['committed'],'当前可用计量人数')
    _integer(value['command_delay_ms'],0,MAX_ELAPSED_MS,'施工指挥延迟')
    if type(value['fortify']) is not bool:
        raise ValueError('是否施工须显式布尔值')
    _intent(value['intent_id'])
    if value['fortify']!=(value['intent_id'] is not None):
        raise ValueError('施工命令和意图身份须匹配')
    stock_work(value['state'],value['configuration'])
    return True


def check_transition(control, receipt):
    """Reject an inconsistent declared result without applying or repairing it."""
    validate_control(control);_fields(receipt,RECEIPT_FIELDS,'施工原生回执')
    if receipt['version']!=RECEIPT_VERSION or receipt['entity_id']!=control['entity_id']:
        raise ValueError('施工回执身份或版本不一致')
    elapsed=receipt['elapsed_ms'];_integer(elapsed,0,MAX_ELAPSED_MS,'施工跨度毫秒')
    for key in ('waited_ms','available_ms','work_added','packets_reserved',
                'discarded_numerator','cap_excess_micro_work'):
        _integer(receipt[key],0,MAX_EXACT_INTEGER,key)
    before=control['state'];after=receipt['after'];cfg=control['configuration']
    validate_state(after)
    if any(before[k]!=after[k] for k in ('root_id','root_committed','committed')):
        raise ValueError('施工期间不能改写编组身份或计量基数')
    waiting=(before['wait_remaining_ms'] if before['intent_id']==control['intent_id']
             else control['command_delay_ms']) if control['fortify'] else 0
    waited=min(elapsed,waiting)
    available=elapsed-waited if control['fortify'] else 0
    if (receipt['waited_ms']!=waited or receipt['available_ms']!=available
            or after['wait_remaining_ms']!=waiting-waited
            or after['intent_id']!=control['intent_id']):
        raise ValueError('施工指挥等待或实际时间账不一致')
    production=cfg['gain_points_per_hour']*control['current']*available
    if production+before['work_remainder']>MAX_EXACT_INTEGER:
        raise ValueError('施工时间乘积超过Native整数精度；须明确分段执行')
    raw=production+before['work_remainder']
    if before['base_ticks']==CAP or not control['fortify']:
        raw=before['work_remainder']
    capacity=((CAP-before['base_ticks'])*before['committed']-before['point_remainder']+SCALE-1)//SCALE
    added=min(raw//HOUR_MS,stock_work(before,cfg),capacity)
    numerator=before['base_ticks']*before['committed']+before['point_remainder']+added*SCALE
    capped=min(numerator,CAP*before['committed'])
    base,point_remainder=divmod(capped,before['committed'])
    remainder=raw%HOUR_MS if added==raw//HOUR_MS and base<CAP else 0
    discarded=raw-added*HOUR_MS-remainder
    packet=cfg['material_points_per_packet']*before['root_committed']
    reserved=max(0,(added-before['material_credit_work']+packet-1)//packet)
    credit=before['material_credit_work']+reserved*packet-added
    expected=dict(base_ticks=base,point_remainder=point_remainder,work_remainder=remainder,
                  materials=before['materials']-reserved,material_credit_work=credit)
    if (receipt['work_added']!=added or receipt['packets_reserved']!=reserved
            or receipt['discarded_numerator']!=discarded
            or receipt['cap_excess_micro_work']!=numerator-capped
            or any(after[k]!=v for k,v in expected.items())):
        raise ValueError('施工工作量、工事变化或材料预付守恒不一致')
    if stock_work(before,cfg)-added!=stock_work(after,cfg):
        raise ValueError('施工材料工作总账不守恒')
    return True
