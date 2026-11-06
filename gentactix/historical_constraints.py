"""Source-associated input envelopes, never battle transitions or outcome quotas.

Reported quantities, analyst bounds and estimated geographic regions remain
separate from frozen unit facts. Only profiles opting in carry these checks.
"""
from datetime import datetime
import math

VERSION = 'historical-input-2'
LEGACY_VERSION = 'historical-input-1'
EVENT_KINDS = ('departure', 'battlefield_entry')


def _fields(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError(label + '字段非法')


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + '不可为空')


def _number(value, low, high, label, *, integer=False):
    if (type(value) not in ((int,) if integer else (int, float))
            or not math.isfinite(value) or not low <= value <= high):
        raise ValueError(label + '必须为有界有限数值')


def _time(value):
    try:
        result = datetime.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise ValueError('输入参考时间非法') from exc
    if result.tzinfo is not None:
        raise ValueError('输入参考时间须采用当地时间')
    return result


def validate_source(phase, units, sources):
    value = phase.get('input_constraints')
    if value is None:
        return
    from .historical_initial import _evidence
    from .missions import distance
    _fields(value, {'version', 'personnel', 'entries'}, '历史输入约束')
    if value['version'] not in (LEGACY_VERSION, VERSION):
        raise ValueError('历史输入约束版本不支持')
    for key in ('personnel', 'entries'):
        if not isinstance(value[key], list) or len(value[key]) > 200:
            raise ValueError('历史输入参考须为有界列表')
    seen = set()
    for row in value['personnel']:
        _fields(row, {'unit_id', 'minimum', 'maximum', 'reported', 'assumption', 'evidence'}, '兵力参考')
        _text(row['unit_id'], '兵力参考单位')
        _number(row['minimum'], 1, 1000000, '兵力建模下界', integer=True)
        _number(row['maximum'], row['minimum'], 1000000, '兵力建模上界', integer=True)
        _text(row['reported'], '原文规模口径')
        _text(row['assumption'], '建模范围依据')
        _evidence(row['evidence'], sources)
        if row['unit_id'] in seen:
            raise ValueError('同一阶段的兵力参考重复；分歧须在依据中保留')
        seen.add(row['unit_id'])
    seen = set()
    if value['entries'] and not any(x['kind'] == 'combined_operation' for x in phase.get('process_requirements', [])):
        raise ValueError('入场参考需要已声明的战役过程')
    for row in value['entries']:
        fields = {'id', 'unit_id', 'label', 'earliest', 'latest', 'region', 'assumption', 'evidence'}
        if value['version'] == VERSION:
            fields.add('reference_kind')
        _fields(row, fields, '行动时点参考')
        kind = row.get('reference_kind', 'contact')
        if kind not in ('contact', 'departure'):
            raise ValueError('参考类型须为contact（接敌）或departure（启程）')
        for key in ('id', 'unit_id', 'label', 'assumption'):
            _text(row[key], '接敌参考' + key)
        if row['id'] in seen:
            raise ValueError('接敌参考ID重复')
        seen.add(row['id'])
        start, end = _time(row['earliest']), _time(row['latest'])
        window = phase.get('execution_window', {})
        if start > end or not window.get('start') or not _time(window['start']) <= start <= end <= _time(window['end']):
            raise ValueError('接敌参考时间超出阶段窗口')
        region = row['region']
        if kind == 'departure':
            if region is not None:
                raise ValueError('启程参考region须为空；不得由出动时段编造接敌区域')
            _evidence(row['evidence'], sources)
            continue
        _fields(region, {'center', 'radius_km'}, '接敌参考区域')
        _fields(region['center'], {'lat', 'lng'}, '接敌参考区域中心')
        _number(region['center']['lat'], -90, 90, '纬度')
        _number(region['center']['lng'], -180, 180, '经度')
        _number(region['radius_km'], .01, 20, '参考区域半径')
        area = phase.get('geographic_scope')
        if area and distance(region['center'], area['center']) + region['radius_km'] > area['radius_km']:
            raise ValueError('接敌参考区域超出阶段地域')
        _evidence(row['evidence'], sources)
    for row in value['personnel'] + value['entries']:
        unit = units.get(row['unit_id'])
        if not unit or unit['role'] not in ('formation', 'support') or not any(
                p['phase_id'] == phase['id'] and p['status'] == 'reported_present' for p in unit['presence']):
            raise ValueError('输入参考必须绑定本阶段已核定的作战单位')


def enforce(snapshot, parameters, actor_ids=None):
    phase = next(p for p in snapshot['definition']['phases'] if p['id'] == snapshot['phase_id'])
    value = phase.get('input_constraints')
    if value is None:
        for row in (parameters.get('campaign') or {}).get('arrivals', {}).values():
            if any('reference_id' in item for item in [row, *row.get('parts', {}).values()]):
                raise ValueError('本阶段没有接敌参考，不能声明未绑定的reference_id')
        return
    from .missions import distance
    selected = set(parameters['actors']) if actor_ids is None else set(actor_ids)
    for row in value['personnel']:
        if row['unit_id'] not in selected:
            continue
        count = parameters['actors'][row['unit_id']]['personnel']
        if not row['minimum'] <= count <= row['maximum']:
            raise ValueError(f"{row['unit_id']}兵力{count}超出本阶段建模范围{row['minimum']}—{row['maximum']}；"
                             f"来源口径：{row['reported']}。{row['assumption']}")
    groups = (parameters.get('partitions') or {}).get('groups', {})
    references = {r['id']: r for r in value['entries']}
    # Also inspect optional parent metadata; an unrelated actor must not claim
    # a source binding merely because only constrained actors are looped below.
    for identity, parent in (parameters.get('campaign') or {}).get('arrivals', {}).items():
        for entry in [parent, *parent.get('parts', {}).values()]:
            if 'reference_id' in entry:
                ref = references.get(entry['reference_id'])
                if ref is None or ref['unit_id'] != identity:
                    raise ValueError('时点参考必须绑定本单位的已声明reference_id：' + identity)
    for identity in {r['unit_id'] for r in value['entries']}:
        refs = {r['id']: r for r in value['entries'] if r['unit_id'] == identity}
        actor = parameters['actors'][identity]
        parent = parameters['campaign']['arrivals'][identity]
        parts = groups.get(identity, {}).get('parts')
        leaves = [(p, parent.get('parts', {}).get(p['id'], parent)) for p in parts] if parts else [(actor, parent)]
        used = set()
        for leaf, entry in leaves:
            ref_id, kind = entry.get('reference_id'), entry.get('event_kind')
            if ref_id not in refs or ref_id in used or kind not in EVENT_KINDS:
                raise ValueError(identity + '每个入场批次须绑定不同的本单位接敌参考reference_id，并声明event_kind为departure或battlefield_entry')
            used.add(ref_id)
            ref = refs[ref_id]
            earliest, latest, release = _time(ref['earliest']), _time(ref['latest']), _time(entry['not_before'])
            if ref.get('reference_kind', 'contact') == 'departure':
                if kind != 'departure':
                    raise ValueError(ref_id + '启程参考只允许event_kind=departure，不能代替前沿接敌')
                if not earliest <= release <= latest:
                    raise ValueError(ref_id + '可启程时间不在所选启程参考时间窗')
                # Availability is constrained, not a movement command: native
                # execution and the operator still determine actual departure.
                continue
            if kind == 'battlefield_entry' and not earliest <= release <= latest:
                raise ValueError(ref_id + '前沿入场时间不在所选参考时间窗；不能把接敌记载改为驻地启程')
            if kind == 'departure' and release >= latest:
                raise ValueError(ref_id + '启程时间须早于接敌参考时间，并留足行军时间')
            # Global assembly knows partition positions but not yet parent speeds.
            if parts or identity in selected:
                remaining = max(0, distance(leaf['position'], ref['region']['center']) - ref['region']['radius_km'])
                if kind == 'battlefield_entry' and remaining > .001:
                    raise ValueError(ref_id + '前沿入场位置不在参考区域；远处驻地不能到接敌时刻才开始行动')
                if kind == 'departure' and identity in selected:
                    possible = actor['speed'] / parameters['area']['terrain_factor'] * (latest - release).total_seconds() / 3600
                    if remaining > possible + .001:
                        raise ValueError(ref_id + '启程时间不足以覆盖最短行军距离；通信与疲劳还会进一步延迟，不保证必然接敌')
        if used != set(refs):
            raise ValueError(identity + '接敌参考批次未全部绑定，不能合并或遗漏援军批次')
