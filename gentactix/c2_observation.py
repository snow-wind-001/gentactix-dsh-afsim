"""Check existing intelligence metadata against elapsed time and action receipts.

This is a clock/receipt invariant, not a detector, target selector or command
transport. It never advances the world, resets an age or repairs a candidate.
"""
import math

from . import missions

VERSION='observation-age-1'
# Native decimal telemetry is written to twelve places; this is numerical
# representation tolerance in minutes, not a tactical or historical allowance.
MINUTE_TOLERANCE=1e-7


def _age(unit):
    value=unit['formation']['intel_age_min']
    if type(value) not in (int,float) or not math.isfinite(value) or value<0:
        raise ValueError(unit['name']+'：情报时效intel_age_min须为有限非负分钟数')
    return value


def validate_transition(before,after,orders,events,seconds,*,source,minimum_delays):
    if not before.get('combined_arms'):return None
    if type(seconds) not in (int,float) or not math.isfinite(seconds) or seconds<=0:
        raise ValueError('情报时效缺少实际正时长')
    old={u['name']:u for _,u in missions.units(before)}
    following={u['name']:u for _,u in missions.units(after)}
    checked={r['unit']:r for r in orders};refresh={};seen=set()
    for event in events:
        if event.get('action')!='recon':continue
        name=event.get('unit');at=event.get('seconds');status=event.get('status_code')
        if (name not in old or checked.get(name,{}).get('action')!='recon'
                or old[name]['personnel']['current']<=0 or type(status) is not int or not 0<=status<=7
                or type(at) not in (int,float) or not math.isfinite(at) or not 0<=at<=seconds
                or at+1e-6<minimum_delays[name] or name in seen):
            raise ValueError('侦察回执须唯一对应存活单位本轮recon、成功状态和有效发生秒数')
        seen.add(name)
        if status==0:refresh[name]=at
    for name,unit in old.items():
        prior=_age(unit);current=_age(following[name])
        expected=(seconds-refresh[name])/60 if name in refresh else prior+seconds/60
        if not math.isclose(current,expected,rel_tol=0,abs_tol=MINUTE_TOLERANCE):
            raise ValueError(name+f'：情报时效intel_age_min应为{expected:.12g}分钟，实际{current:.12g}；'
                '未有成功侦察回执时须加本轮实际秒数/60，recon命令或恢复通信本身不能重置；候选未修补')
        if (name not in refresh and following[name]['formation']['intel_confidence']>unit['formation']['intel_confidence']
                and not math.isclose(following[name]['formation']['intel_confidence'],unit['formation']['intel_confidence'],rel_tol=0,abs_tol=1e-7)):
            raise ValueError(name+'：无成功侦察回执不能提高情报可信度')
    return dict(version=VERSION,source=source,elapsed_seconds=seconds,validated_units=len(old),
        refreshed_units=len(refresh),scope='仅校验既有情报时间/刷新回执；不代表目标已探测或完整C2通信仿真')


def instruction(seconds):
    return ('\n情报时效使用formation.intel_age_min，单位是分钟，可以有小数，不是秒。'
        f'所有单位包括待命与暂未到场者，无成功侦察回执时，期末=轮初+{seconds}/60；必须提交变化后的值。'
        'recon如实际刷新，须在combined_arms.events提供{unit:精确名称,action:"recon",seconds:本轮实际发生秒数,status_code:0,model_estimate:true}；'
        f'期末时效=({seconds}-该发生秒数)/60，不能默认轮末永远为0。无刷新可以不提供侦察事件，时效正常递增。'
        '事件须对应本单位recon命令且每单位至多一次；restore_comms只恢复联络，不等于获得新情报。'
        '成功侦察发生时点不得早于本局既有通信延迟；阻塞回执不刷新，不能把命令已提交当成已收令。'
        'intel_confidence是0至100的连续分值，可以有小数；无成功刷新时不得提高。地图显示全局单位不等于部队已探测目标。')
