"""Version-pinned historical OOB facts, independent of purpose and executor.

This layer preserves source precision. It does not invent deployments, strengths
or combat effects. Process models and their estimates belong to a separate layer.
"""
import copy
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit

from . import adjudication_lib

DATA_ROOT = Path(__file__).resolve().parent.parent / 'data/historical_initial'
FORMAT = 'gentactix-historical-initial-v1'
ROLES = {'command', 'formation', 'support', 'naval', 'aviation'}
PRESENCE = {'reported_present', 'campaign_participant', 'later_participant', 'outside_scope', 'unverified'}
FILE_ID = r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}'


def digest(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _identity(value):
    return isinstance(value, str) and re.fullmatch(FILE_ID, value) is not None


def _fields(value, fields, message):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError(message)


def _evidence(value, sources):
    if not isinstance(value, list) or not value:
        raise ValueError('历史事实必须逐项保留来源与定位依据')
    for item in value:
        if (not isinstance(item, dict) or set(item) - {'source_id', 'locator', 'note'}
                or not isinstance(item.get('source_id'), str)
                or item['source_id'] not in sources or not _text(item.get('locator'))
                or ('note' in item and not isinstance(item['note'], str))):
            raise ValueError('历史事实来源或定位依据非法')


def _sources(sources):
    if not isinstance(sources, dict) or not sources:
        raise ValueError('历史初态缺少来源注册表')
    for key, source in sources.items():
        _fields(source, {'title', 'url', 'publisher', 'evidence_kind',
                         'original_archive_examined', 'limitations'}, '历史初态来源元数据非法')
        if not _identity(key) or any(not _text(source[k]) for k in ('title', 'url', 'publisher', 'limitations')):
            raise ValueError('历史初态来源元数据非法')
        try:
            url = urlsplit(source['url'])
        except ValueError as exc:
            raise ValueError('历史来源网址非法') from exc
        if url.scheme not in ('http', 'https') or not url.hostname:
            raise ValueError('历史来源必须是公开网页地址')
        if (type(source['original_archive_examined']) is not bool
                or source['evidence_kind'] not in ('archive_publication', 'published_memoir',
                                                   'published_secondary', 'official_history')):
            raise ValueError('历史来源类型或原件核验状态非法')


def _phases(phases, sources):
    if not isinstance(phases, list) or not phases:
        raise ValueError('历史初态缺少阶段')
    phase_ids = set()
    for phase in phases:
        _fields({k:v for k,v in phase.items() if k not in ('execution_window','geographic_scope','process_requirements','interaction','input_constraints','operations','relations','measurements')}, {'id', 'label', 'date', 'scope', 'evidence'}, '历史阶段字段非法')
        if 'interaction' in phase:
            interaction=phase['interaction']
            _fields(interaction,{'kind','active_teams','scope','evidence'},'阶段交互范围字段非法')
            if (interaction['kind']!='non_contact_transfer' or interaction['active_teams'] not in (['red'],['blue'])
                    or not _text(interaction['scope'])):
                raise ValueError('非接敌转移须声明单一在场方及有来源的范围，不是任意单方战斗开关')
            _evidence(interaction['evidence'],sources)
        if 'process_requirements' in phase:
            requirements=phase['process_requirements']
            if not isinstance(requirements,list) or not requirements or len(requirements)>4:raise ValueError('阶段过程需求必须为非空有界列表')
            for requirement in requirements:
                _fields(requirement,{'kind','scope','evidence'},'阶段过程需求字段非法')
                if requirement['kind'] not in ('formation_crossing','combined_operation') or not _text(requirement['scope']):raise ValueError('阶段过程需求尚未实现，不能宣称通用支持')
                _evidence(requirement['evidence'],sources)
        if 'geographic_scope' in phase:
            region=phase['geographic_scope']
            _fields(region, {'center','radius_km','kind','note','evidence'}, '阶段地域字段非法')
            _fields(region['center'], {'lat','lng'}, '阶段地域中心非法')
            if (any(type(region['center'][k]) not in (int,float) or not math.isfinite(region['center'][k]) for k in ('lat','lng'))
                    or not -90<=region['center']['lat']<=90 or not -180<=region['center']['lng']<=180
                    or type(region['radius_km']) not in (int,float) or not math.isfinite(region['radius_km'])
                    or not .1<=region['radius_km']<=2000 or region['kind']!='model_scope_limit' or not _text(region['note'])):
                raise ValueError('阶段地域必须保留有限的计算范围与参考说明')
            _evidence(region['evidence'],sources)
        if 'execution_window' in phase:
            window=phase['execution_window']
            if not isinstance(window,dict):raise ValueError('阶段计算窗口字段非法')
            _fields({k:v for k,v in window.items() if k!='start'}, {'end','kind','note','evidence'}, '阶段计算窗口字段非法')
            try:end=datetime.fromisoformat(window['end'])
            except (ValueError,TypeError) as exc:raise ValueError('阶段计算窗口结束时间非法') from exc
            if end.tzinfo is not None or window['kind']!='model_scope_limit' or not _text(window['note']):
                raise ValueError('阶段计算窗口须说明模型范围，不能冒充史实准确时刻')
            if 'start' in window:
                try:start=datetime.fromisoformat(window['start'])
                except (ValueError,TypeError) as exc:raise ValueError('阶段计算窗口开始时间非法') from exc
                if start.tzinfo is not None or start>=end:
                    raise ValueError('阶段计算窗口须按当地时间先开始后结束')
            _evidence(window['evidence'], sources)
        if (not isinstance(phase['id'], str) or not re.fullmatch(r'[a-z0-9_-]+', phase['id'])
                or phase['id'] in phase_ids or not _text(phase['label']) or not _text(phase['scope'])):
            raise ValueError('历史阶段身份非法')
        phase_ids.add(phase['id'])
        _evidence(phase['evidence'], sources)
        date = phase['date']
        _fields(date, {'label', 'precision', 'evidence'}, '历史日期字段非法')
        if (not _text(date['label']) or not isinstance(date['precision'], str)
                or date['precision'] not in ('day', 'month', 'year', 'period', 'range')):
            raise ValueError('历史阶段必须保留日期精度')
        _evidence(date['evidence'], sources)
    return phase_ids


def _facts(facts, sources, phase_ids):
    _fields(facts, {'personnel', 'equipment', 'position'}, '历史单位事实字段不完整')
    for kind, fact in facts.items():
        _fields(fact, {'value', 'evidence', 'scope'}, '历史事实字段非法')
        if not _text(fact['scope']) or not isinstance(fact['evidence'], list):
            raise ValueError('历史事实必须说明统计范围和来源精度')
        if fact['value'] is not None or fact['evidence']:
            _evidence(fact['evidence'], sources)
        number = fact['value']
        if kind == 'personnel' and number is not None and (type(number) is not int or number < 0):
            raise ValueError('历史人数非法')
        if kind == 'equipment' and number is not None and not isinstance(number, list):
            raise ValueError('历史装备必须分类记载')
        if kind == 'position' and number is not None:
            _fields(number, {'kind', 'lat', 'lng', 'uncertainty_km', 'phase_id'}, '历史位置字段非法')
            if (number['kind'] not in ('unit_position', 'deployment_area_reference')
                    or not isinstance(number['phase_id'], str) or number['phase_id'] not in phase_ids):
                raise ValueError('历史位置必须区分阵地与区域参考')
            if (any(type(number[k]) not in (int, float) or not math.isfinite(number[k])
                    for k in ('lat', 'lng', 'uncertainty_km'))
                    or not -90 <= number['lat'] <= 90 or not -180 <= number['lng'] <= 180
                    or number['uncertainty_km'] < 0):
                raise ValueError('历史位置坐标或不确定度非法')


def validate_definition(value):
    fields={'format', 'id', 'version', 'battle', 'coverage', 'sources', 'phases', 'units'}
    if isinstance(value,dict) and 'event_order' in value:fields.add('event_order')
    _fields(value, fields,
            '历史初态档案格式非法')
    if 'event_order' in value and value['event_order']!='dated-events-1':
        raise ValueError('史料事件排序版本非法；不得猜测缺载钟点')
    if value['format'] != FORMAT or not _identity(value['id']) or not _identity(value['version']):
        raise ValueError('历史初态格式、ID或版本非法')
    if not isinstance(value['battle'], str) or value['battle'] not in adjudication_lib.list_battles():
        raise ValueError('历史初态未关联有效战役')
    coverage = value['coverage']
    _fields(coverage, {'order_of_battle_complete', 'opening_deployment_complete',
                       'strength_complete', 'notes'}, '历史初态覆盖状态字段非法')
    if (any(type(coverage[k]) is not bool for k in coverage if k != 'notes')
            or not isinstance(coverage['notes'], list) or not coverage['notes']
            or any(not _text(x) for x in coverage['notes'])):
        raise ValueError('历史初态覆盖状态必须明确')
    sources = value['sources']
    _sources(sources)
    phase_ids = _phases(value['phases'], sources)
    rows = value['units']
    if not isinstance(rows, list) or not rows:
        raise ValueError('历史初态不允许空单位名单')
    units, names = {}, set()
    for unit in rows:
        _fields({k:v for k,v in unit.items() if k!='children_coverage'}, {'id', 'name', 'team', 'role', 'echelon', 'parent_id', 'evidence',
                       'presence', 'facts'}, '历史单位字段非法')
        if 'children_coverage' in unit:
            coverage=unit['children_coverage']
            _fields(coverage,{'status','scope','evidence'},'下级覆盖字段非法')
            if coverage['status'] not in ('complete','partial','unknown') or not _text(coverage['scope']):
                raise ValueError('下级覆盖必须声明完整/部分/未知及统计范围')
            _evidence(coverage['evidence'],sources)
        identity, name, team = unit['id'], unit['name'], unit['team']
        if (not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}', identity)
                or identity in units or not _text(name) or not isinstance(team, str)
                or team not in ('red', 'blue') or (team, name) in names):
            raise ValueError('历史单位身份重复或非法')
        if (not isinstance(unit['role'], str) or unit['role'] not in ROLES
                or not _text(unit['echelon'])
                or (unit['parent_id'] is not None and not isinstance(unit['parent_id'], str))):
            raise ValueError('历史单位角色、层级或上级身份非法')
        units[identity] = unit
        names.add((team, name))
        _evidence(unit['evidence'], sources)
        if not isinstance(unit['presence'], list) or not unit['presence']:
            raise ValueError('历史单位必须说明参战阶段与精度')
        seen = set()
        for row in unit['presence']:
            _fields(row, {'phase_id', 'status', 'evidence'}, '历史单位参战阶段字段非法')
            if (not isinstance(row['phase_id'], str) or row['phase_id'] not in phase_ids
                    or row['phase_id'] in seen or not isinstance(row['status'], str)
                    or row['status'] not in PRESENCE):
                raise ValueError('历史单位参战阶段非法')
            seen.add(row['phase_id'])
            _evidence(row['evidence'], sources)
        _facts(unit['facts'], sources, phase_ids)
    teams = {u['team'] for u in rows}
    if teams != {'red', 'blue'}:
        local = [p for p in value['phases'] if p['id'] != 'campaign_reference']
        if not local or any(set(p.get('interaction', {}).get('active_teams', [])) != teams for p in local):
            raise ValueError('接敌历史初态必须整理双方；单方仅限逐阶段有来源的非接敌转移')
    for identity, unit in units.items():
        parent = unit['parent_id']
        if parent is not None and (parent not in units or units[parent]['team'] != unit['team']):
            raise ValueError('历史单位父级缺失或跨阵营')
        chain = {identity}
        while parent is not None:
            if parent in chain:
                raise ValueError('历史单位隶属关系成环')
            chain.add(parent)
            parent = units[parent]['parent_id']
    from . import historical_constraints
    for phase in value['phases']:
        historical_constraints.validate_source(phase, units, sources)
    from . import historical_links
    historical_links.validate(value)
    json.dumps(value, ensure_ascii=False, allow_nan=False)
    return True


def catalog():
    path = DATA_ROOT / 'index.json'
    try:
        index = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'profiles': []}
    except (OSError, ValueError) as exc:
        raise ValueError('历史初态索引不可读') from exc
    _fields(index, {'profiles'}, '历史初态索引格式非法')
    if not isinstance(index['profiles'], list):
        raise ValueError('历史初态索引必须为列表')
    battles = adjudication_lib.list_battles()
    profiles, ids = {}, set()
    for row in index['profiles']:
        _fields(row, {'battle', 'id', 'default_version'}, '历史初态索引条目非法')
        if (not isinstance(row['battle'], str) or row['battle'] not in battles
                or row['battle'] in profiles or not _identity(row['id']) or row['id'] in ids
                or not _identity(row['default_version'])):
            raise ValueError('历史初态索引身份、版本重复或非法')
        profiles[row['battle']] = row
        ids.add(row['id'])
    return [{'battle': battle, 'profile_id': profiles.get(battle, {}).get('id'),
             'version': profiles.get(battle, {}).get('default_version'),
             'status': 'profiled' if battle in profiles else 'not_profiled'} for battle in battles]


def versions(battle):
    """Available fact snapshots; availability never certifies simulation fidelity."""
    row = next((x for x in catalog() if x['battle'] == battle), None)
    if not row or not row['profile_id']:
        return []
    result = []
    for path in sorted((DATA_ROOT / row['profile_id']).glob('*.json')):
        if not _identity(path.stem):
            continue
        try:
            record = definition(battle, path.stem)
        except ValueError:
            continue
        result.append({'version': record['version'], 'default': record['version'] == row['version'],
                       'coverage': copy.deepcopy(record['coverage'])})
    return result


def definition(battle, version=None):
    row = next((x for x in catalog() if x['battle'] == battle), None)
    if not row or not row['profile_id']:
        raise ValueError('本战役的历史单位初态尚未整理，不能用局部教学编组替代')
    version = version or row['version']
    if not _identity(version):
        raise ValueError('历史档案版本非法')
    path = DATA_ROOT / row['profile_id'] / (version + '.json')
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError('指定历史初态版本不存在或不可读') from exc
    validate_definition(value)
    if value['battle'] != battle or value['id'] != row['profile_id'] or value['version'] != version:
        raise ValueError('历史初态文件身份不一致')
    return value


def _materialize(record, phase_id):
    validate_definition(record)
    phase = next((p for p in record['phases'] if p['id'] == phase_id), None)
    if phase is None:
        raise ValueError('未知历史初始阶段')
    units = {'red_units': [], 'blue_units': []}
    for source in record['units']:
        facts = source['facts']
        present = next((r for r in source['presence'] if r['phase_id'] == phase_id), None)
        point = facts['position']['value']
        point = point if point and point['phase_id'] == phase_id else None
        actual = point if point and point['kind']=='unit_position' else None
        unit = {'historical_unit_id': source['id'], 'name': source['name'],
                'type': '指挥机构' if source['role'] == 'command' else '历史编制（兵种待核）',
                'historical_role': source['role'], 'echelon': source['echelon'],
                'parent_id': source['parent_id'],
                'historical_presence': present['status'] if present else 'unverified',
                'lat': actual['lat'] if actual else None, 'lng': actual['lng'] if actual else None,
                'deployment': copy.deepcopy(facts['position']),
                'personnel': {'current': facts['personnel']['value'], 'committed': None,
                              'casualties': None, 'noncombat_losses': None,
                              'source': '历史初态档案；未载字段为未知'},
                'historical_facts': copy.deepcopy(facts),
                'historical_evidence': copy.deepcopy(source['evidence'])}
        units[source['team'] + '_units'].append(unit)
    return {'current_time': phase['date']['label'], **units, 'engagements': [],
            'historical_initial': {'format': FORMAT, 'profile_id': record['id'],
                                   'version': record['version'], 'definition_hash': digest(record),
                                   'phase_id': phase_id, 'definition': copy.deepcopy(record)},
            'source_note': '历史单位档案；参战名单与阶段到场分别记录。人数、装备和精确位置未载时保持未知；档案覆盖程度见说明。'}


def initial(battle, phase_id=None, *, version=None, purpose='historical', engine='afsim'):
    if purpose not in ('analysis', 'historical', 'synthetic') or engine not in ('narrative', 'afsim'):
        raise ValueError('未知用途或执行引擎')
    record = definition(battle, version)
    return _materialize(record, phase_id or record['phases'][0]['id'])


def restore(snapshot):
    """Materialize a frozen fact snapshot without consulting the live index."""
    _fields(snapshot, {'format', 'profile_id', 'version', 'definition_hash', 'phase_id', 'definition'},
            '缺少完整的历史初态定义快照')
    value = snapshot['definition']
    validate_definition(value)
    if (snapshot['format'] != FORMAT or digest(value) != snapshot['definition_hash']
            or value['id'] != snapshot['profile_id'] or value['version'] != snapshot['version']):
        raise ValueError('历史初态定义或版本摘要被修改')
    return _materialize(value, snapshot['phase_id'])


def validate_initial(world):
    if not isinstance(world, dict):
        raise ValueError('历史初态必须为对象')
    record = world.get('historical_initial')
    _fields(record, {'format', 'profile_id', 'version', 'definition_hash', 'phase_id', 'definition'},
            '缺少完整的历史初态定义快照')
    if record['format'] != FORMAT:
        raise ValueError('历史初态快照格式非法')
    expected = restore(record)
    for key in ('current_time', 'red_units', 'blue_units', 'historical_initial'):
        if world.get(key) != expected[key]:
            raise ValueError('共同历史初态被改写：' + key)
    if any(k in world for k in ('mission', 'combined_arms', 'synthetic_configuration')):
        raise ValueError('历史初态不能混入局部教学编组')
    return True


def readiness(world):
    """Report factual coverage, without certifying an unbound process model."""
    validate_initial(world)
    units = world['red_units'] + world['blue_units']
    record = world['historical_initial']['definition']
    located = sum(u['lat'] is not None and u['lng'] is not None for u in units)
    missing = []
    if not record['coverage']['order_of_battle_complete']:
        missing.append('战斗序列尚未完整')
    if located < len(units) or not record['coverage']['opening_deployment_complete']:
        missing.append('缺少本阶段可核部署')
    if (any(u['personnel']['current'] is None for u in units)
            or not record['coverage']['strength_complete']):
        missing.append('缺少逐单位兵力／装备基数')
    if any(u['historical_presence'] != 'reported_present' for u in units):
        missing.append('参战名单尚未全部绑定阶段到场')
    # This module intentionally has no execution-model binding. A nonempty OOB
    # must not be advertised as a validated AFSIM/DSH combat model.
    missing.append('尚未绑定和验收历史部队过程计算模型')
    return {'roster_count': len(units), 'command_count': sum(u['historical_role'] == 'command' for u in units),
            'located_unit_count': located, 'unknown_position_count': len(units) - located,
            'ready_for_process_simulation': False, 'missing': missing,
            'coverage': copy.deepcopy(record['coverage'])}
