"""Read-only chronological microfuel checks; never allocate or move resources."""
import copy
import math
from decimal import Decimal

from . import motion_state

VERSION='timed-microfuel-1'
FIELDS=('opening_microliters','received_microliters','movement_spent_microliters',
        'support_spent_microliters','closing_microliters')


def validate_times(times,seconds=None):
    if not isinstance(times,(list,tuple)) or not 1<=len(times)<=97:
        raise ValueError('定时燃油须有完整且有界的事件时钟')
    previous=0;result=[]
    for index,item in enumerate(times):
        if not isinstance(item,(list,tuple)) or len(item)!=2:
            raise ValueError('定时燃油事件时钟格式非法')
        when,kind=item;last=index==len(times)-1
        if (type(when) not in (int,float) or not math.isfinite(when) or not 0<when<=31*86400
                or Decimal(str(when))*1000!=(Decimal(str(when))*1000).to_integral_value()
                or kind!=('settlement' if last else 'delivery')
                or when<previous or (when==previous and not last)):
            raise ValueError('定时燃油事件须依次到货并有唯一末态结算')
        result.append((when,kind));previous=when
    if seconds is not None and (type(seconds) not in (int,float) or previous!=seconds):
        raise ValueError('定时燃油事件未覆盖完整物理时长')
    return result


def _count(value):
    if type(value) is not int or value<0:
        raise ValueError('定时燃油数量须为非负整数微升')
    return value


def _stock(value):
    liters,credit=divmod(_count(value),motion_state.SCALE)
    unit={'formation':dict(fatigue=0,fatigue_carry_ticks=0,fuel_liters=liters,
                           fuel_credit_microliters=credit)}
    motion_state.validate_unit(unit)
    return unit


def validate(initial_microliters,ledger,expected_times,*,expected_received_microliters=None):
    """Arrivals occur AFTER the preceding interval's movement/support debits."""
    _stock(initial_microliters);times=validate_times(expected_times)
    if (not isinstance(ledger,dict) or set(ledger)!={'version','unit','events'}
            or ledger['version']!=VERSION or ledger['unit']!='microliter'
            or not isinstance(ledger['events'],list) or len(ledger['events'])!=len(times)):
        raise ValueError('定时燃油回执版本、单位或事件数量非法')
    if expected_received_microliters is not None:
        if not isinstance(expected_received_microliters,(list,tuple)) or len(expected_received_microliters)!=len(times):
            raise ValueError('定时燃油到货交叉回执不完整')
        for amount in expected_received_microliters:_count(amount)
    total=dict(opening_microliters=initial_microliters,received_microliters=0,
        movement_spent_microliters=0,support_spent_microliters=0,closing_microliters=initial_microliters)
    previous=initial_microliters
    for index,(row,expected) in enumerate(zip(ledger['events'],times)):
        if (not isinstance(row,dict) or set(row)!=set(FIELDS)|{'seconds','kind'}
                or type(row['seconds']) not in (int,float) or (row['seconds'],row['kind'])!=expected):
            raise ValueError('定时燃油事件缺失、重复或时刻非法')
        for key in FIELDS:_count(row[key])
        opening=row['opening_microliters'];closing=row['closing_microliters']
        got=row['received_microliters'];spent=row['movement_spent_microliters']+row['support_spent_microliters']
        if opening!=previous:raise ValueError('定时燃油跨事件库存不连续')
        if spent>opening:raise ValueError('定时燃油到货前消耗透支，不能用未来到货支付')
        if row['kind']=='settlement' and got:raise ValueError('定时燃油末态结算不得额外到货')
        if expected_received_microliters is not None and got!=expected_received_microliters[index]:
            raise ValueError('定时燃油到货与独立物资回执不一致')
        motion_state.validate_fuel_flow(_stock(opening),_stock(closing),
            received_microliters=got,spent_microliters=spent)
        for key in ('received_microliters','movement_spent_microliters','support_spent_microliters'):total[key]+=row[key]
        previous=closing
    total['closing_microliters']=previous
    return {**copy.deepcopy(ledger),**total}
