"""Canonical continuous-motion balances; readers and bookkeeping, not physics.

Whole fuel liters plus positive microliter credit represent usable fuel. This
is a conserved stock. Fatigue plus fractional ticks is intensive: splitting
copies it, while merging keeps the worst whole/fraction pair together.
"""
import math
import re

SCALE = 1_000_000
VERSION = 'fixed-motion-state-1'
FATIGUE_FIELD = 'fatigue_carry_ticks'
FUEL_FIELD = 'fuel_credit_microliters'
FIELDS = frozenset((FATIGUE_FIELD, FUEL_FIELD))
TASK_FIELD = 'motion_task'
TASK_VERSION = 'continuous-motion-task-1'
CADENCE_MS = 10000


def present(unit):
    f = unit.get('formation')
    return isinstance(f,dict) and bool(FIELDS.intersection(f) or TASK_FIELD in f)


def validate_unit(unit):
    f = unit.get('formation', {})
    if not isinstance(f,dict):
        raise ValueError('连续机动须有明确的编组状态对象')
    for field in FIELDS:
        if type(f.get(field)) is not int or not 0 <= f[field] < SCALE:
            raise ValueError('连续机动精度字段须完整，且余量为[0,1000000)的整数：'+field)
    if type(f.get('fatigue')) is not int or not 0 <= f['fatigue'] <= 100:
        raise ValueError('连续机动疲劳整数须在0至100之间')
    if f['fatigue'] == 100 and f[FATIGUE_FIELD]:
        raise ValueError('连续机动疲劳总量不能超过100')
    if type(f.get('fuel_liters')) is not int or not 0 <= f['fuel_liters'] <= 10_000_000:
        raise ValueError('连续机动整升燃油须为0至10000000的整数')
    if TASK_FIELD in f:validate_task(f[TASK_FIELD])
    return True


def validate_task(task):
    fields={'version','intent_id','target','status','wait_remaining_ms','speed_mps','feedback_remaining_ms'}
    if (not isinstance(task,dict) or set(task)!=fields or task['version']!=TASK_VERSION
            or task['status'] not in ('idle','waiting','moving','arrived','blocked')):
        raise ValueError('连续机动任务字段或状态非法')
    for k,maximum in [('wait_remaining_ms',31*86400000),('feedback_remaining_ms',CADENCE_MS)]:
        if type(task[k]) is not int or not 0<=task[k]<=maximum:
            raise ValueError('连续机动任务毫秒量非法：'+k)
    speed=task['speed_mps']
    if type(speed) not in (int,float) or not math.isfinite(speed) or not 0<=speed<=10000:
        raise ValueError('连续机动速度须为有界有限数')
    if task['status']=='idle':
        if task['intent_id'] is not None or task['target'] is not None or task['wait_remaining_ms'] or speed:
            raise ValueError('空闲连续机动任务不能保留活动意图')
    else:
        if not isinstance(task['intent_id'],str) or re.fullmatch('[a-f0-9]{32}',task['intent_id']) is None:
            raise ValueError('连续机动意图身份非法')
        p=task['target']
        if (not isinstance(p,dict) or set(p)!={'lat','lng'}
                or any(type(p[k]) not in (int,float) or not math.isfinite(p[k]) or abs(p[k])>bound
                    for k,bound in [('lat',90),('lng',180)])):
            raise ValueError('连续机动目标坐标非法')
    if task['status']=='waiting':
        if not task['wait_remaining_ms'] or speed:raise ValueError('通信等待须有剩余时间且速度为零')
    elif task['wait_remaining_ms']:raise ValueError('非等待状态不能保留通信等待')
    if task['status'] in ('arrived','blocked') and speed:raise ValueError('停止状态速度须为零')
    return True


def fatigue_load(unit):
    validate_unit(unit)
    f = unit['formation']
    return f['fatigue'] * SCALE + f[FATIGUE_FIELD]


def fuel_load(unit):
    validate_unit(unit)
    f = unit['formation']
    return f['fuel_liters'] * SCALE + f[FUEL_FIELD]


def fatigue_value(unit):
    return fatigue_load(unit) / SCALE


def fuel_value(unit):
    return fuel_load(unit) / SCALE


def validate_fuel_flow(before,after,*,received_microliters=0,spent_microliters=0):
    """Check explicit gross physical quantities; never fill or debit a stock."""
    for value in (received_microliters,spent_microliters):
        if type(value) is not int or value<0:
            raise ValueError('连续机动燃油到货与消耗须为非负整数微升')
    if fuel_load(before)+received_microliters-spent_microliters!=fuel_load(after):
        raise ValueError('连续机动燃油微升收支不守恒')


def validate_uniform(units):
    selected = [present(u) for u in units]
    if any(selected) and not all(selected):
        raise ValueError('连续机动精度不同，须显式完成版本迁移后才能合并')
    if any(selected):
        for u in units:
            validate_unit(u)
    return any(selected)


def summary(units):
    """Read-only stock total and intensive range, with explicit integer units."""
    if not validate_uniform(units):
        return None
    fuel=sum(fuel_load(u) for u in units)
    loads=[fatigue_load(u) for u in units]
    return {'version':VERSION,'units_per_point':SCALE,'microliters_per_liter':SCALE,
            'fuel_microliters':fuel,'fuel_credit_microliters':fuel%SCALE,
            'fatigue_min_ticks':min(loads),'fatigue_max_ticks':max(loads)}
