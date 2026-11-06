"""Shared prepaid construction contracts; read-only, never a physics executor.

Materials remain in the caller's unique stock. Partial work consumes prepaid
credit immediately; state contains no second material count. Work units are
explicit normalized point-person equivalents, not historical material mass.
"""
import math
import re
from gentactix import fortification_work as legacy

VERSION='shared-fortification-work-1'
STATE_VERSION='shared-fortification-state-1'
RECEIPT_VERSION='shared-fortification-receipt-1'
SCALE=legacy.SCALE
CAP=legacy.CAP
HOUR_MS=legacy.HOUR_MS
MAX_ELAPSED_MS=legacy.MAX_ELAPSED_MS
STATE_FIELDS={'version','root_id','root_committed','committed','site_id','base_ticks',
    'point_remainder','work_remainder','material_credit_work','material_credit_fraction',
    'intent_id','wait_remaining_ms'}
CONTROL_FIELDS={'entity_id','configuration','state','materials','current','fortify','intent_id','command_delay_ms'}
RECEIPT_FIELDS={'version','entity_id','elapsed_ms','waited_ms','available_ms','productive_ms',
    'paid_work_numerator','work_added','packets_reserved','materials_after','cap_excess_micro_work','after'}


def _number(value,minimum,maximum,label):
    if type(value)not in(int,float)or not math.isfinite(value)or not minimum<=value<=maximum:
        raise ValueError(label+'须为范围内有限数值')


def validate_config(value):
    legacy._fields(value,{'version','gain_points_per_worker_hour','material_work_units_per_packet',
        'fatigue_per_work_hour','activity_food_factor','assumption'},'共享施工配置')
    if value['version']!=VERSION:raise ValueError('共享施工配置版本非法')
    legacy._integer(value['gain_points_per_worker_hour'],1,10000,'人当量小时工作率')
    legacy._integer(value['material_work_units_per_packet'],1,1000000000,'全局材料包工作容量')
    _number(value['fatigue_per_work_hour'],0,100,'施工小时疲劳')
    _number(value['activity_food_factor'],1,10,'施工劳动粮秣因子')
    if not isinstance(value['assumption'],str)or not value['assumption'].strip()or len(value['assumption'])>4000:
        raise ValueError('共享施工须说明估计依据')
    return True


def validate_state(value,configuration):
    validate_config(configuration);legacy._fields(value,STATE_FIELDS,'共享施工状态')
    if value['version']!=STATE_VERSION:raise ValueError('共享施工状态版本非法')
    for key in ('root_id','site_id'):
        if not isinstance(value[key],str)or re.fullmatch('[a-f0-9]{64}',value[key])is None:
            raise ValueError('共享施工须绑定明确的根与阵地身份')
    legacy._integer(value['root_committed'],1,10000000,'根投入人数')
    legacy._integer(value['committed'],1,value['root_committed'],'互斥投入人数')
    legacy._integer(value['base_ticks'],0,CAP,'工事微分值')
    legacy._integer(value['point_remainder'],0,value['committed']-1,'工事除法余量')
    for key in ('work_remainder','material_credit_fraction'):
        legacy._integer(value[key],0,HOUR_MS-1,key)
    legacy._integer(value['material_credit_work'],0,configuration['material_work_units_per_packet']-1,'整工作预付余额')
    legacy._integer(value['wait_remaining_ms'],0,MAX_ELAPSED_MS,'剩余指挥等待')
    legacy._intent(value['intent_id'])
    if value['intent_id']is None and value['wait_remaining_ms']:raise ValueError('空闲意图不能保留指挥等待')
    if value['base_ticks']==CAP and(value['point_remainder']or value['work_remainder']):
        raise ValueError('已封顶工事不能保留重复兑现余量')
    return True


def validate_control(control):
    legacy._fields(control,CONTROL_FIELDS,'共享施工输入')
    if not isinstance(control['entity_id'],str)or re.fullmatch('g[a-f0-9]{20}',control['entity_id'])is None:
        raise ValueError('共享施工须绑定编译实体')
    validate_state(control['state'],control['configuration'])
    legacy._integer(control['materials'],0,10000000,'唯一未拆包工程材料')
    legacy._integer(control['current'],0,control['state']['committed'],'实际可用计量人数')
    legacy._integer(control['command_delay_ms'],0,MAX_ELAPSED_MS,'指挥延迟')
    if type(control['fortify'])is not bool:raise ValueError('施工状态须为布尔值')
    legacy._intent(control['intent_id'])
    if control['fortify']!=(control['intent_id']is not None):raise ValueError('施工意图不匹配')
    return True


def material_balance(control):
    """Exact read-only total; the Native producer need not multiply a huge stock."""
    validate_control(control);state=control['state'];cfg=control['configuration']
    return (control['materials']*cfg['material_work_units_per_packet']+state['material_credit_work'])*HOUR_MS+state['material_credit_fraction']


def check_segment(control,receipt):
    """Validate a declared interval without returning, applying or repairing it."""
    validate_control(control);legacy._fields(receipt,RECEIPT_FIELDS,'共享施工回执')
    if receipt['version']!=RECEIPT_VERSION or receipt['entity_id']!=control['entity_id']:
        raise ValueError('共享施工回执身份或版本不匹配')
    elapsed=receipt['elapsed_ms'];legacy._integer(elapsed,0,MAX_ELAPSED_MS,'施工跨度')
    for key in ('waited_ms','available_ms','paid_work_numerator','work_added','packets_reserved','materials_after','cap_excess_micro_work'):
        legacy._integer(receipt[key],0,legacy.MAX_EXACT_INTEGER,key)
    _number(receipt['productive_ms'],0,elapsed,'实际工作时间')
    before=control['state'];after=receipt['after'];cfg=control['configuration'];validate_state(after,cfg)
    for key in ('root_id','root_committed','committed','site_id'):
        if before[key]!=after[key]:raise ValueError('施工区间不能改写根、人数或阵地身份')
    waiting=(before['wait_remaining_ms']if before['intent_id']==control['intent_id']else control['command_delay_ms'])if control['fortify']else 0
    waited=min(elapsed,waiting);available=elapsed-waited if control['fortify']else 0
    if(receipt['waited_ms']!=waited or receipt['available_ms']!=available
                or after['wait_remaining_ms']!=waiting-waited or after['intent_id']!=control['intent_id']):
        raise ValueError('施工等待或意图不匹配')
    remaining_micro=(CAP-before['base_ticks'])*before['committed']-before['point_remainder']
    capacity=(remaining_micro+SCALE-1)//SCALE*HOUR_MS-before['work_remainder']
    rate=cfg['gain_points_per_worker_hour']*control['current']
    demanded=min(rate*available,capacity)if control['fortify']and rate else 0
    paid=min(demanded,material_balance(control))
    added,remainder=divmod(before['work_remainder']+paid,HOUR_MS)
    numerator=before['base_ticks']*before['committed']+before['point_remainder']+added*SCALE
    capped=min(numerator,CAP*before['committed']);base,point_remainder=divmod(capped,before['committed'])
    if base==CAP:remainder=0
    prior_credit=before['material_credit_work']*HOUR_MS+before['material_credit_fraction']
    packet=cfg['material_work_units_per_packet']*HOUR_MS
    reserved=max(0,(paid-prior_credit+packet-1)//packet)
    credit=prior_credit+reserved*packet-paid;whole,fraction=divmod(credit,HOUR_MS)
    if(receipt['paid_work_numerator']!=paid or receipt['work_added']!=added
                or receipt['packets_reserved']!=reserved or receipt['materials_after']!=control['materials']-reserved
                or receipt['cap_excess_micro_work']!=numerator-capped
                or after['base_ticks']!=base or after['point_remainder']!=point_remainder
                or after['work_remainder']!=remainder or after['material_credit_work']!=whole
                or after['material_credit_fraction']!=fraction):
        raise ValueError('共享施工工作、工事或材料预付账不一致')
    productive=paid/rate if rate else 0
    if not math.isclose(receipt['productive_ms'],productive,rel_tol=0,abs_tol=.000001):
        raise ValueError('实际工作时间与已支付劳动量不一致')
    return True
