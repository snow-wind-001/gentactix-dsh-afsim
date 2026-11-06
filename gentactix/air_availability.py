"""Declared aviation availability; guards only, no flight or resource executor."""
import copy
import math
import re
from datetime import datetime, timedelta
from . import sim_clock

VERSION='air-availability-1'


def timestamp(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?',value):
        raise ValueError('航空可用时段须为明确当地日期时间，不接受仅日期或混合时区')
    try:return datetime.fromisoformat(value)
    except ValueError as exc:raise ValueError('航空可用时段日期时间非法') from exc


def validate(value):
    if (not isinstance(value,dict) or set(value)!={'version','start','end','assumption'}
            or value['version']!=VERSION or not isinstance(value['assumption'],str) or not value['assumption'].strip()):
        raise ValueError('航空可用时段须声明版本、起止与估计依据；end可为空表示持续可用')
    start=timestamp(value['start'])
    if value['end'] is not None and timestamp(value['end'])<=start:
        raise ValueError('航空可用时段结束须晚于开始')
    return True


def _interval(world,spec):
    value=spec.get('availability')
    if value is None:return None
    validate(value);now=sim_clock.instant(world)
    if now is None:raise ValueError('航空可用时段需要程序维护的明确公历时钟，不能猜测日期')
    return now,timestamp(value['start']),timestamp(value['end']) if value['end'] is not None else None


def status(world,spec):
    interval=_interval(world,spec)
    if interval is None:return 'active'
    now,start,end=interval
    return 'pending' if now<start else 'expired' if end is not None and now>=end else 'active'


def require(world,spec,through_s=0):
    if type(through_s) not in (int,float) or not math.isfinite(through_s) or through_s<0:
        raise ValueError('航空任务时段偏移须为有限非负秒数')
    interval=_interval(world,spec)
    if interval is None:return
    now,start,end=interval
    if now<start or end is not None and (now>=end or now+timedelta(seconds=through_s)>end):
        raise ValueError('航空任务超出该部队声明的可用时段；不能提前出动或越过退出时点返场')


def observation(world,spec):
    if 'availability' not in spec:return None
    return {**copy.deepcopy(spec['availability']),'status':status(world,spec)}


def view(world):
    from . import air_assets
    definition=air_assets.world_definition(world or {})
    return {identity:observation(world,spec) for identity,spec in (definition or {}).get('pools',{}).items()
            if 'availability' in spec}
