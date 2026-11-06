"""Read-only workforce chronology; never allocate losses or update a world.

Combat availability is sampled after actual Native events. Noncombat losses in
an interval apply at its end, so neither can be charged to an earlier period.
"""
from decimal import Decimal, InvalidOperation

VERSION = 'combat-strength-clock-1'


def _integer(value, maximum, label):
    if type(value) not in (int, float) or not 0 <= value <= maximum or value != int(value):
        raise ValueError(label+'须为有限范围内整数')
    return int(value)


def validate(unit, seconds, segments, events, *, final_current):
    """Check actual people per interval, returning evidence rather than effects."""
    if type(seconds) not in (int, float) or isinstance(seconds, bool):
        raise ValueError('兵力时钟须有明确时长')
    try:
        ms = Decimal(str(seconds))*1000
        if not ms.is_finite() or not 0 < ms <= 31*86400000 or ms != int(ms):
            raise ValueError('兵力时钟须为有界毫秒时长')
    except (InvalidOperation, OverflowError) as exc:
        raise ValueError('兵力时钟时长非法') from exc
    stop = int(ms)
    initial = _integer(unit.get('personnel', {}).get('current'), 10000000, '期初人数')
    final_current = _integer(final_current, initial, '期末人数')
    if not isinstance(events, list) or not events or not isinstance(segments, list) or not segments:
        raise ValueError('兵力时钟及实际时段不可缺失')
    previous_time = -1
    previous_people = initial
    for event in events:
        if not isinstance(event, dict) or set(event) != {'at_ms', 'combat_current'}:
            raise ValueError('兵力时钟事件字段非法')
        when = _integer(event['at_ms'], stop, '兵力事件时刻')
        people = _integer(event['combat_current'], initial, '战斗后可用人数')
        if when <= previous_time or people > previous_people:
            raise ValueError('兵力时钟不能倒序、重复或补造人员')
        previous_time, previous_people = when, people
    if events[0] != {'at_ms': 0, 'combat_current': initial}:
        raise ValueError('兵力时钟必须从明确的期初人数开始')
    index = 0
    noncombat = 0
    last = 0
    person_ms = 0
    for segment in segments:
        if not isinstance(segment, dict) or not {'start_ms', 'end_ms', 'people', 'noncombat_delta'} <= set(segment):
            raise ValueError('兵力时段缺少人数或时间')
        start = _integer(segment['start_ms'], stop, '时段开始')
        end = _integer(segment['end_ms'], stop, '时段结束')
        people = _integer(segment['people'], initial, '时段人数')
        lost = _integer(segment['noncombat_delta'], people, '时段非战斗减员')
        if start != last or end <= start:
            raise ValueError('兵力时段必须连续且完整')
        while index+1 < len(events) and events[index+1]['at_ms'] <= start:
            index += 1
        if index+1 < len(events) and events[index+1]['at_ms'] < end:
            raise ValueError('兵力时段跨越伤亡事件，须先结算旧人数时段')
        if people != max(0, events[index]['combat_current']-noncombat):
            raise ValueError('实际时段人数与战斗及非战斗减员时钟不一致')
        person_ms += people*(end-start)
        noncombat += lost
        last = end
    if last != stop:
        raise ValueError('兵力时钟没有覆盖完整时长')
    if final_current != max(0, events[-1]['combat_current']-noncombat):
        raise ValueError('兵力时钟与期末人员总账不一致')
    return dict(version=VERSION, initial_current=initial, final_current=final_current,
                final_combat_current=events[-1]['combat_current'],
                noncombat_delta=noncombat, event_count=len(events),
                interval_count=len(segments), elapsed_ms=stop,
                person_milliseconds=str(person_ms))
