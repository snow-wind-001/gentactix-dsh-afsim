"""Read-only personnel indicators; legacy HP is never an inferred headcount."""
import math


def strength_pct(unit):
    counts=unit.get('personnel')
    if not isinstance(counts,dict):return None
    current,committed=counts.get('current'),counts.get('committed')
    if (type(current) not in (int,float) or type(committed) not in (int,float)
            or not 0<=current<=committed or not 0<committed<=2**53-1 or current*10000>2**53-1):
        return None
    if current!=int(current) or committed!=int(committed):return None
    current,committed=int(current),int(committed)
    # Integer ratio with native ties to even; round(percent,2) has different
    # binary-decimal ties (e.g. 107/4000). Neither counts nor raw HP are changed.
    whole,remainder=divmod(current*10000,committed)
    if remainder*2>committed or remainder*2==committed and whole%2:
        whole+=1
    return whole/100


def inactive(unit):
    counts=unit.get('personnel')
    current=counts.get('current') if isinstance(counts,dict) else None
    if type(current) in (int,float) and 0<=current<=2**53-1 and current==int(current):return current==0
    hp=unit.get('hp',unit.get('HP',unit.get('health',unit.get('兵力'))))
    if isinstance(hp,bool) or hp is None:return False
    try:value=float(hp)
    except (TypeError,ValueError,OverflowError):return False
    return math.isfinite(value) and value<=0


INSTRUCTION=('人员保有率personnel_strength_pct为宿主只读投影：现有/累计投入×100，保留两位且恰好一半取偶数；'
    '不是核定编制满员率。人员数未知时不提供该值；不得从HP反推人数。HP保留旧兼容含义，'
    '不能用旧HP声称人员满额。该只读字段不得提交到unit_updates。')
