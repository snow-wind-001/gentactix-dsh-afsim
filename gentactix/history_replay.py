"""Immutable sourced event frames. Missing tactical state is never synthesized."""
import copy
from datetime import date
import hashlib
import json
import math
import re
from pathlib import Path

from . import anchors

ROOT = Path(__file__).resolve().parent.parent
VERSION = 'strict-history-1'
PINNED_VERSION = 'strict-history-2'
SCOPE = '史料事件级重现；地名点不是部队部署；不补全缺载钟点、轨迹或逐回合伤亡。'
PINNED_SCOPE = '来源事件与部队身份已固定版本；参战参考不表示本帧到场。缺载的本帧位置、人数与损失保持未知。'
ORDER_VERSION = 'dated-events-1'
ORDER_SCOPE = '未载明确日日期的概览在前；明确日期事件按所记日期分组，同日保留来源顺序。范围可能重叠，排序不补造钟点，也不代表各阶段串行发生。'


def _sort_dated_events(events):
    def key(event):
        found=re.match(r'(\d{4}-\d{2}-\d{2})(?=$|[^\d])',event['date_label'])
        if found:
            try:day=date.fromisoformat(found.group(1))
            except ValueError as exc:raise ValueError('史料事件包含非法日日期')from exc
            return 1,day.toordinal()
        return 0,0
    return sorted(events,key=key)


def _apply_event_order(pack,source):
    if source.get('event_order')!=ORDER_VERSION:return
    pack['events']=_sort_dated_events(pack['events'])
    pack['ordering']={'version':ORDER_VERSION,'scope':ORDER_SCOPE}
    if ORDER_SCOPE not in pack.setdefault('uncertainties',[]):pack['uncertainties'].append(ORDER_SCOPE)


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def dataset(battle):
    for family in ('long_march', 'anti_japanese_war'):
        folder = ROOT / 'data' / family
        records = json.loads((folder / 'scenarios.json').read_text())['scenarios']
        for record in records:
            if record['name'] != battle:
                continue
            registry = json.loads((folder / 'sources.json').read_text())['sources']
            def resolve(row):
                return {**copy.deepcopy(row), 'sources': [
                    {'id': key, **copy.deepcopy(registry[key])} for key in row.get('sources', [])]}
            events = []
            for row in record['events']:
                event = resolve(row)
                event['date_label'] = row['date'] + ' · ' + row.get('time_label', '未载钟点')
                events.append(event)
            value = {'battle': battle, 'events': events, 'forces': [resolve(r) for r in record['forces']],
                     'figures': [resolve(r) for r in record['figures']], 'outcome': record['outcome'],
                     'uncertainties': copy.deepcopy(record.get('uncertainties', [])),
                     'evidence': '公开资料审订档案；未核原始命令簿，不将记载升级为唯一确证'}
            break
        else:
            continue
        break
    else:
        records = json.loads((ROOT / 'data/history_replay/curated_events.json').read_text())['battles']
        found = next((r for r in records if r['battle'] == battle), None)
        if found is None:
            raise ValueError('本战役缺少已整理的史料事件，不能使用模型替代严格回放')
        value = {**copy.deepcopy(found), 'forces': [], 'figures': [],
                 'outcome': '以所列史料事件及原卡为准，不从战役总数反推逐帧伤亡。',
                 'evidence': '现有史料卡的事件摘编；具体指令与逐帧部署未载'}
    if not value['events'] or any(not e.get('sources') for e in value['events']):
        raise ValueError('史实事件必须逐项保留来源')
    points = []
    for name, coords in anchors.collect_available_nodes(battle, battle=battle).items():
        meta = anchors.node_metadata(name)
        if not meta.get('source_url'):
            continue
        points.append({'name': name, 'lat': coords[0], 'lng': coords[1],
                       'kind': '地名参考点，非本帧部队位置', 'metadata': copy.deepcopy(meta)})
    value.update(version=VERSION, scope=SCOPE, geo_references=points)
    value['dataset_hash'] = _digest(value)
    return value


def frame(battle, cursor):
    pack = dataset(battle)
    if type(cursor) is not int or not 0 <= cursor < len(pack['events']):
        raise ValueError('史料事件索引超出范围，回放已经结束或序号无效')
    event = copy.deepcopy(pack['events'][cursor])
    record = {k: copy.deepcopy(v) for k, v in pack.items() if k != 'events'}
    record.update(cursor=cursor, total=len(pack['events']), event=event,
                  status='completed' if cursor == len(pack['events']) - 1 else 'active')
    citations = '；'.join(s.get('title', s.get('id', '来源')) for s in event['sources'])
    return {'current_time': event['date_label'], 'red_units': [], 'blue_units': [], 'engagements': [],
            'history_replay': record, 'current_terrain': '地名仅供定位，不代表已核部队部署',
            'situation_report': f"【史料重现 {cursor + 1}/{record['total']}】{event['date_label']}\n\n{event['event']}\n\n时间精度：{event['precision']}。\n\n来源：{citations}\n\n{SCOPE}",
            'source_note': pack['evidence']}


def validate(world):
    record = world.get('history_replay') or {}
    if record.get('version') == PINNED_VERSION:
        expected = frame_pinned({'pack': record.get('source_snapshot'),
                                 'initial': world.get('historical_initial')}, record.get('cursor'))
        if set(world) - (set(expected) | {'afsim'}):
            raise ValueError('史料帧不得附加无来源战局字段')
        for key, value in expected.items():
            if world.get(key) != value:
                raise ValueError('固定史料帧被改写：' + key)
        return True
    expected = frame(record.get('battle'), record.get('cursor'))
    if set(world) - (set(expected) | {'afsim'}):
        raise ValueError('史料帧不得附加无来源战局字段')
    for key in ('history_replay', 'current_time', 'red_units', 'blue_units', 'engagements', 'situation_report', 'source_note', 'current_terrain'):
        if world.get(key) != expected[key]:
            raise ValueError('史料帧与审订数据不一致，拒绝改写：' + key)
    if any(key in world for key in ('mission', 'combined_arms', 'simulation_clock', 'air_operations')):
        raise ValueError('严格回放不得混入合成教学规则或固定回合时钟')
    return True


def _validate_pack(pack):
    fields = {'battle', 'dataset_hash', 'events', 'evidence', 'figures', 'forces',
              'geo_references', 'outcome', 'scope', 'version'}
    if (not isinstance(pack, dict) or not fields <= set(pack)
            or set(pack) - fields - {'corpus', 'uncertainties', 'ordering'} or pack['version'] != PINNED_VERSION):
        raise ValueError('固定来源包格式非法')
    if pack['dataset_hash'] != _digest({k: v for k, v in pack.items() if k != 'dataset_hash'}):
        raise ValueError('固定来源包摘要不一致')
    for key in ('battle', 'evidence', 'outcome', 'scope'):
        if not isinstance(pack[key], str) or not pack[key].strip():
            raise ValueError('固定来源包缺少说明：' + key)
    for key in ('events', 'forces', 'figures', 'geo_references'):
        if not isinstance(pack[key], list):
            raise ValueError('固定来源包列表非法：' + key)
    if not pack['events']:
        raise ValueError('固定来源包不能没有事件')
    for event in pack['events']:
        if (not isinstance(event, dict) or any(not isinstance(event.get(k), str) or not event[k].strip()
                for k in ('date_label', 'event', 'precision')) or not isinstance(event.get('sources'), list)
                or not event['sources'] or any(not isinstance(s, dict) or not s.get('title') for s in event['sources'])):
            raise ValueError('固定来源事件缺少日期、精度或出处')
    if 'ordering' in pack:
        if pack['ordering']!={'version':ORDER_VERSION,'scope':ORDER_SCOPE} or pack['events']!=_sort_dated_events(pack['events']):
            raise ValueError('固定来源日期分组被改写，或排序版本非法')
    for point in pack['geo_references']:
        if (not isinstance(point, dict) or any(type(point.get(k)) not in (int, float)
                or not math.isfinite(point[k]) for k in ('lat', 'lng'))
                or not -90 <= point['lat'] <= 90 or not -180 <= point['lng'] <= 180):
            raise ValueError('固定地名参考坐标非法')
    json.dumps(pack, ensure_ascii=False, allow_nan=False)


def pin(battle, *, version=None):
    """Freeze sources and a partial OOB, if available, at session creation."""
    from . import historical_initial
    pack = copy.deepcopy(dataset(battle))
    pack.pop('dataset_hash')
    pack.update(version=PINNED_VERSION, scope=PINNED_SCOPE)
    row = next((r for r in historical_initial.catalog() if r['battle'] == battle), None)
    initial = (historical_initial.initial(battle,version=version)['historical_initial']
               if row and row['status'] == 'profiled' else None)
    _merge_missing_operations(pack, initial)
    from . import historical_links
    historical_links.bind_events(pack,initial)
    pack['dataset_hash'] = _digest(pack)
    _validate_pack(pack)
    return {'pack': pack, 'initial': initial}


def _merge_missing_operations(pack, initial):
    """Include the selected version's sourced events, never live effects.

    Legacy versions retain the original phase/operation ordering. Explicit
    dated-events-1 source versions group known dates across overlapping axes;
    unknown dates and same-day order never acquire inferred clock values.
    """
    if initial is None:
        return
    source = initial['definition']
    operations = [op for phase in source['phases'] for op in phase.get('operations', [])]
    identities = {op['id'] for op in operations}
    linked = [e['event_key'] for e in pack['events'] if e.get('event_key') in identities]
    if len(linked) != len(set(linked)):
        raise ValueError('同一史料事件不能绑定多个回放帧；扩展版本不得静默消除重复来源')
    existing = {e.get('event_key'):e for e in pack['events'] if e.get('event_key')}
    if not any(op['id'] not in existing for op in operations):
        _apply_event_order(pack,source)
        return
    events = [copy.deepcopy(e) for e in pack['events'] if e.get('event_key') not in identities]
    for op in operations:
        if op['id'] in existing:
            events.append(copy.deepcopy(existing[op['id']]))
        else:
            sources = [{**copy.deepcopy(source['sources'][ev['source_id']]),
                        'id':ev['source_id'],'locator':ev['locator']} for ev in op['evidence']]
            events.append(dict(event_key=op['id'],date_label=op['date']['label'],precision=op['date']['precision'],
                event=op['description']+'\n\n核验限制：'+op['limitations'],sources=sources))
    pack['events'] = events
    if source.get('event_order')==ORDER_VERSION:
        _apply_event_order(pack,source)
    else:
        pack.setdefault('uncertainties', []).append(
            '扩展版本保留既有概览在前，具名事件按固定版本阶段顺序展示；命令不等于到场，日级记录不补造钟点或单位状态。')


def frame_pinned(snapshot, cursor):
    """Render immutable references; do not pretend a roster is live deployment."""
    from . import historical_initial
    if not isinstance(snapshot, dict) or set(snapshot) != {'pack', 'initial'}:
        raise ValueError('缺少完整来源及初态快照')
    pack, initial = snapshot['pack'], snapshot['initial']
    _validate_pack(pack)
    if type(cursor) is not int or not 0 <= cursor < len(pack['events']):
        raise ValueError('史料事件索引超出范围，回放已经结束或序号无效')
    baseline = historical_initial.restore(initial) if initial is not None else None
    expected_order=(initial or {}).get('definition',{}).get('event_order')
    if (pack.get('ordering')or{}).get('version')!=expected_order:
        raise ValueError('来源事件排序与固定档案版本不一致')
    if baseline and initial['definition']['battle'] != pack['battle']:
        raise ValueError('历史单位档案与固定来源战役不一致')
    event = copy.deepcopy(pack['events'][cursor])
    from . import historical_links
    linked=historical_links.frame_binding(initial,event)
    record = {k: copy.deepcopy(v) for k, v in pack.items() if k != 'events'}
    record.update(cursor=cursor, total=len(pack['events']), event=event,
                  status='completed' if cursor == len(pack['events']) - 1 else 'active',
                  source_snapshot=copy.deepcopy(pack),
                  dataset_hash=_digest({'source_hash': pack['dataset_hash'], 'historical_initial': initial}),
                  roster_status='partial_reference' if baseline else 'not_profiled',
                  unit_state_scope='有出处的参战参考；未建立逐事件的部队部署与损耗，不能作为当前到场或交战证据')
    units = {team: copy.deepcopy(baseline[team]) if baseline else [] for team in ('red_units', 'blue_units')}
    for unit in units['red_units'] + units['blue_units']:
        unit.update(lat=None, lng=None, frame_evidence_status='参战参考；本帧部署、实到与损失未载')
        unit['personnel'] = {'current': None, 'committed': None, 'casualties': None,
                             'noncombat_losses': None, 'source': '本帧未载，不能从参战名单反推'}
        if linked:
            related=unit['historical_unit_id'] in linked['unit_ids']
            unit['frame_operation_ids']=[linked['id']] if related else []
            unit['frame_evidence_status']=('本事件记载任务/行动；精确阵位与兵额未核' if related else '未绑定本事件；不证明当前在场')
    if linked:
        record['source_operation']=linked
        record['unit_state_scope']='本事件具名单位与地名已关联；任务记载不证明精确阵位、当时兵额或已计算战损。'
    citations = '；'.join(s.get('title', s.get('id', '来源')) for s in event['sources'])
    return {'current_time': event['date_label'], **units, 'engagements': [],
            **({'historical_initial': copy.deepcopy(initial)} if baseline else {}),
            'history_replay': record, 'current_terrain': '地名仅供定位，不代表已核部队部署',
            'situation_report': f"【史料重现 {cursor + 1}/{record['total']}】{event['date_label']}\n\n{event['event']}\n\n时间精度：{event['precision']}。\n\n来源：{citations}\n\n{PINNED_SCOPE}",
            'source_note': pack['evidence']}


def frame_for_session(session, cursor):
    if session.get('source_replay_snapshot') is not None:
        return frame_pinned(session['source_replay_snapshot'], cursor)
    return frame(session['battle_choice'], cursor)


def observation(world, *, limit=8, offset=0):
    """Bounded source facts for DSH; full definitions stay outside messages."""
    if type(limit) is not int or not 1 <= limit <= 16 or type(offset) is not int or offset < 0:
        raise ValueError('历史编制观察每页1—16条，分页须为非负整数')
    validate(world)
    record = world['history_replay']
    units = [(team, unit) for team in ('red', 'blue') for unit in world.get(team + '_units', [])]
    initial = world.get('historical_initial')
    return {'readonly': True, 'battle': record['battle'], 'cursor': record['cursor'],
            **({'source_operation':copy.deepcopy(record['source_operation'])} if record.get('source_operation') else {}),
            'total_events': record['total'], 'dataset_hash': record['dataset_hash'],
            'current_time': world['current_time'], 'event': copy.deepcopy(record['event']),
            'recent_events': [{k: copy.deepcopy(e.get(k)) for k in ('date_label', 'event', 'precision')}
                              for e in record.get('source_snapshot', {}).get('events', [])[
                                  max(0, record['cursor'] - 3):record['cursor'] + 1]],
            'scope': record['scope'], 'unit_state_scope': record.get('unit_state_scope', SCOPE),
            'profile_id': initial['profile_id'] if initial else None,
            'profile_version': initial['version'] if initial else None,
            'coverage': copy.deepcopy(initial['definition']['coverage']) if initial else None,
            'roster_total': len(units), 'offset': offset,
            'next_offset': offset + limit if offset + limit < len(units) else None,
            'units': [{'team': team, **{k: copy.deepcopy(unit.get(k)) for k in (
                'historical_unit_id', 'name', 'echelon', 'parent_id', 'historical_role',
                'historical_presence', 'frame_evidence_status')}} for team, unit in units[offset:offset + limit]]}


def analysis_prompt(world, question, recent_dialogue=(), *, tools_available=False):
    tools = ('本轮已提供只读工具。先调用get_afsim_observation(limit=1)，不传ids，核对当前帧；'
             '需要指定参考单位时可用historical_unit_id，返回id为该参考的注册ID；两者不会重复计数。'
             '若有source_operation，再用retrieve_history(kind="operations",query=当前事件ID)核对绑定来源。'
             '只检索回答所需资料；当前事件已命中且next_args为空时，不重复扫完其他阶段或继续增加offset。'
             '需要其他部队、事件或数值时沿next_args分页；数值用kind="measurements"并保留统计对象、日期与口径。'
             'query是文字子串，不是语义检索；未命中用返回的unfiltered_args核对，仍未知就说明未载。'
             'get_afsim_observation是既有工具名，不表示启用了AFSIM或发生物理交战。'
             '工具读取不下令、不推进、不执行；不能仅依靠旧会话记忆或谎称已检索。\n'
             if tools_available else '')
    return ('你是只读历史回溯分析员。依据固定来源事件和参考编制回答问题；'
            '参战名单不证明当前到场，地名点不代表阵地，未知人数不等于零。'
            '本次不是模型计算的交战过程，不得宣称AFSIM产生了部队运动、毁伤或资源消耗。'
            '区分来源记载与分析假说，保持时间精度；不下令、不改节点、不补造部署。'
            '具体方位、行军方向、部队到场、指挥动作和伤亡数字须有当前事件或实际检索结果的来源定位；'
            '地名、现代参考点与军事常识不能补成这些史实，资料未载就写未载。'
            '说明来源明确记载什么；额外因果解释标为“分析推断（非史料记载）”并说明条件，不能改写成当时确定发生。'
            '对话和旧模型讲解不是新的史料；来源未支持的说法不能因为重复而获得证实。'
            '只给出公开分析与来源依据，不输出内部思维过程。\n' + tools
            + json.dumps({'observation': observation(world), 'question': question,
                'recent_dialogue': [{'role': str(m.get('role')), 'content': str(m.get('content') or '')[:700]}
                                    for m in list(recent_dialogue)[-4:]]}, ensure_ascii=False))
