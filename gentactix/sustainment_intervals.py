"""Read-only interval receipts, using existing ration rules; no state executor."""
import copy
import math
from decimal import Decimal

from . import formation_parts, motion_state, support_dynamics as sd, timed_fuel

VERSION='sustainment-intervals-1'
FIELDS=('start_ms','end_ms','moving_ms','people','demand','consumed','shortage_hours',
        'noncombat_remainder','fatigue_floor','noncombat_delta','fatigue_floor_gain_ticks')
INTEGERS={'start_ms','end_ms','moving_ms','people','noncombat_delta','fatigue_floor_gain_ticks'}


def validate(cfg,unit,seconds,segments,*,events=None,max_segment_ms=motion_state.CADENCE_MS,load_probe=False,work_activity=None):
    sd.validate_config(cfg)
    if type(load_probe) is not bool or load_probe and seconds!=.001:
        raise ValueError('仅一毫秒初始化检查可以声明加载探针')
    if (type(seconds) not in (int,float) or not 0<seconds<=31*86400
            or type(max_segment_ms) is not int or max_segment_ms<=0 or not isinstance(segments,list)):
        raise ValueError('营养回执时长或时段列表非法')
    stop=int(Decimal(str(seconds))*1000)
    if Decimal(str(seconds))*1000!=stop:raise ValueError('营养回执须精确到毫秒')
    deliveries=[]
    if events is not None:
        if not isinstance(events,list):raise ValueError('营养到货时钟须为列表')
        for e in events:
            if not isinstance(e,dict) or set(e)!={'seconds','kind','food_received'}:raise ValueError('营养到货事件字段非法')
            sd.number(e['food_received'])
            if e['kind']=='settlement' and e['food_received']:raise ValueError('营养末态结算不得额外到货')
        timed_fuel.validate_times([(e['seconds'],e['kind']) for e in events],seconds)
        deliveries=[(int(Decimal(str(e['seconds']))*1000),e) for e in events]
    if work_activity is not None:
        from . import shared_fortification
        if not isinstance(work_activity,dict)or set(work_activity)!={'configuration','intervals'}:
            raise ValueError('劳动营养必须同时绑定配置和实际工作区间')
        shared_fortification.validate_config(work_activity['configuration'])
        if not isinstance(work_activity['intervals'],list)or len(work_activity['intervals'])!=len(segments):
            raise ValueError('劳动营养区间数量不完整')
    u=copy.deepcopy(unit);scale=formation_parts.scale(unit);available=unit['personnel']['current']
    total={k:0 for k in sd.RECEIPT_FIELDS};last=0;nc=0;gain=0;moving=0;index=0;snapshots=[]

    def arrivals():
        nonlocal index
        while index<len(deliveries) and deliveries[index][0]==last:
            _,event=deliveries[index];before=u['logistics']['food']*scale;got=event['food_received']
            if before+got>sd.food_capacity(cfg,unit)*scale+1e-6:
                raise ValueError('营养到货超过当时携行容量')
            u['logistics']['food']+=got/scale
            snapshots.append(dict(seconds=event['seconds'],kind=event['kind'],food_before=before,
                food_after=u['logistics']['food']*scale,people=available,nutrition=copy.deepcopy(total)))
            index+=1

    for segment_number,r in enumerate(segments):
        if not isinstance(r,dict) or set(r)!=set(FIELDS):raise ValueError('营养分时回执字段非法')
        for k,v in r.items():
            sd.number(v)
            if k in INTEGERS and v!=int(v):raise ValueError('营养整数时段或人数非法')
        dt=r['end_ms']-last
        if r['start_ms']!=last or not 0<dt<=max_segment_ms or not 0<=r['moving_ms']<=dt:
            raise ValueError('营养时段不连续或超过允许周期')
        if index<len(deliveries) and deliveries[index][0]<r['end_ms']:
            raise ValueError('营养到货必须具有独立时段边界，不能跨越后再结算')
        if r['people']>available or r['people']>unit['personnel']['current']-nc:
            raise ValueError('营养可用人数增加或超出已知人数')
        if r['fatigue_floor_gain_ticks']>math.floor(r['fatigue_floor']*motion_state.SCALE+.5):
            raise ValueError('营养疲劳增量超过缺粮下限')
        u['personnel']['current']=int(r['people'])
        if load_probe and r['moving_ms']:
            raise ValueError('初始化加载探针不能声明真实机动时段')
        work_arguments={}
        if work_activity is not None:
            activity=work_activity['intervals'][segment_number];paid=activity['receipt']
            if (activity['start_ms']!=r['start_ms']or activity['end_ms']!=r['end_ms']
                    or activity['current']!=r['people']or paid['elapsed_ms']!=dt):
                raise ValueError('劳动与营养必须使用同一时间段和可用人数')
            work_arguments=dict(working_seconds=paid['productive_ms']/1000,
                work_factor=work_activity['configuration']['activity_food_factor'])
            if load_probe and paid['productive_ms']:raise ValueError('初始化探针不能声明实际劳动')
        if load_probe and sd.deferred_support(u):
            wanted=sd.expected(cfg,u,'hold',dt/1000)
        else:
            wanted=sd.expected(cfg,u,'move',dt/1000,moving_seconds=r['moving_ms']/1000,**work_arguments)
        for k in ('demand','consumed','shortage_hours','noncombat_remainder','fatigue_floor','noncombat_delta'):
            if not math.isclose(r[k],wanted[k],rel_tol=0,abs_tol=1e-6):raise ValueError('营养分时回执不一致：'+k)
        # Reference arithmetic avoids accumulating printed-decimal noise. No
        # candidate stock is filled, rounded or committed from this reference.
        u['logistics']['food']-=wanted['consumed']/scale
        u['sustainment'].update({k:r[k] for k in ('shortage_hours','noncombat_remainder')})
        for k in ('demand','consumed','noncombat_delta'):total[k]+=r[k]
        total['unmet']+=r['demand']-r['consumed']
        for k in ('shortage_hours','noncombat_remainder','fatigue_floor'):total[k]=r[k]
        last=r['end_ms'];nc+=r['noncombat_delta'];available=r['people']-r['noncombat_delta']
        gain+=r['fatigue_floor_gain_ticks'];moving+=r['moving_ms'];arrivals()
    if last!=stop or index!=len(deliveries):raise ValueError('营养回执未覆盖完整时长或到货')
    summary={**total,'fatigue_floor_gain_ticks':int(gain),'moving_ms':int(moving),
             'elapsed_ms':int(last),'interval_count':len(segments)}
    return dict(summary=summary,events=snapshots,food_after=u['logistics']['food']*scale)
