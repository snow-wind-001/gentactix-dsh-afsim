"""Closed scenario templates and observed motion over DSH's native AFSIM MCP.

AFSIM owns the observed positions. Existing application checkpoints own roster,
resources, historical provenance and teaching-rule effects. No LLM-written state
or arbitrary scenario source is accepted at this boundary.
"""
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import time
import uuid

from gentactix import adjudicator, commands, sim_clock
from gentactix.config import is_naval
from gentactix.unit_types import classify_unit


SCOPE = 'AFSIM地理运动；未作DEM道路、弹道、武器效能或历史伤亡标定'
NATIVE_MOTION_REVISION = 3


def motion_revision(world):
    from gentactix import movement_feedback
    if movement_feedback.continuous(world):return 12
    if movement_feedback.configuration(world):return 11
    from gentactix import crossing_network
    if crossing_network.enabled(world):return 10
    from gentactix import ferries
    if ferries.config(world):return 9
    from gentactix import formation_parts
    if formation_parts.has_groups(world):return 8
    from gentactix import crossings
    return 7 if crossings.get_model(world) else NATIVE_MOTION_REVISION


def _coordinate(unit):
    result = commands.known_position(unit)
    if result is None:
        return None
    if not -90 <= result['lat'] <= 90 or not -180 <= result['lng'] <= 180:
        raise ValueError('AFSIM坐标超出地理范围')
    return result


def _location(point):
    lat, lng = point['lat'], point['lng']
    return f'{abs(lat):.10f}{"n" if lat >= 0 else "s"} {abs(lng):.10f}{"e" if lng >= 0 else "w"}'


def _mover(unit):
    profile = classify_unit(unit.get('type', '')) or {}
    if is_naval(unit.get('type', '')) or profile.get('id') == 'naval':
        return 'WSF_SURFACE_MOVER'
    return 'WSF_AIR_MOVER' if profile.get('id') == 'aviation' else 'WSF_GROUND_MOVER'


def compile_scene(before, orders, seconds, *, native_rules=False):
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 31 * 86400:
        raise ValueError('AFSIM回合秒数非法')
    from gentactix import movement_feedback
    movement_feedback.require_executor(before,backend='afsim' if native_rules else None)
    continuous=movement_feedback.continuous(before)
    units = list(commands.iter_units(before))
    if not isinstance(orders, list) or any(not isinstance(order, dict) for order in orders):
        raise ValueError('AFSIM命令必须为对象数组')
    names = [commands.name_of(unit) for _, unit in units]
    selected = {}
    for order in orders:
        name = order.get('unit')
        if name not in names or names.count(name) != 1 or name in selected:
            raise ValueError('AFSIM命令单位不存在、重复或有歧义')
        from gentactix import missions
        if order.get('action') not in missions.ACTIONS:
            raise ValueError('AFSIM命令行动未登记')
        if order['action'] == 'move' and _coordinate(order) is None:
            raise ValueError('AFSIM移动坐标未知或非有限数')
        selected[name] = order
        if native_rules:
            from gentactix import terrain_process
            terrain_process.check_order(before,order)
    controls=None
    if continuous:
        from . import afsim_continuous_motion
        bound={
            'g'+hashlib.sha256((team+':'+commands.name_of(unit)).encode()).hexdigest()[:20]:
                {'team':team,'name':commands.name_of(unit)} for team,unit in units if _coordinate(unit) is not None}
        controls=afsim_continuous_motion.inputs(before,orders,bound)
    script = [f'end_time {seconds + .001:.6f} sec', 'log_file mission.log',
              'event_output', ' file events.evt', ' enable all', 'end_event_output']
    entities, excluded = {}, []
    from . import afsim_ferries
    ferry=bool(native_rules and afsim_ferries.enabled(before))
    for team, unit in units:
        name = commands.name_of(unit)
        origin = _coordinate(unit)
        if origin is None:
            excluded.append({'team': team, 'name': name, 'reason': '坐标未知，保留于应用态势但不虚构AFSIM位置'})
            continue
        identity = 'g' + hashlib.sha256((team + ':' + name).encode()).hexdigest()[:20]
        if identity in entities:
            raise ValueError('AFSIM实体身份重复')
        order = selected.get(name, {})
        target = _coordinate(order) if order.get('action') == 'move' else origin
        moving = adjudicator.distance_km((origin['lat'], origin['lng']), (target['lat'], target['lng'])) > 1e-6
        mover = _mover(unit)
        crossing_plan=None
        if moving and native_rules and before.get('combined_arms'):
            from gentactix import crossing_network
            crossing_plan=crossing_network.plan(before,unit,order)
        entities[identity] = {'team': team, 'name': name, 'origin': origin, 'target': target,
                              'mover': mover if moving else 'static', 'moving': moving,
                              'constrained':bool(native_rules and before.get('combined_arms'))}
        if crossing_plan:
            entities[identity].update(crossing_plan=crossing_plan,waypoints=crossing_plan['waypoints'])
        if ferry:
            from gentactix import ferries
            if crossing_plan or ferries.carrier(before,name):
                entities[identity]['ferry_transport']=True
                if not crossing_plan:
                    entities[identity].update(waypoints=[before['combined_arms']['bridge']['crossing_model']['banks'][k] for k in ('a','b')],move_budget_km=1000000)
            if crossing_plan:
                banks=before['combined_arms']['bridge']['crossing_model']['banks']
                entities[identity]['boat_distance_km']=adjudicator.distance_km((banks['a']['lat'],banks['a']['lng']),(banks['b']['lat'],banks['b']['lng']))
        if order.get('cancel_crossing') and not crossing_plan:
            entities[identity]['cancel_crossing']=order['cancel_crossing']
        if moving:
            script += [f'platform_type {identity}_type WSF_PLATFORM',
                       f' mover {mover}', f'  update_interval {1 if continuous else min(10, max(.01, seconds / 100)):.6f} sec',
                       '  at_end_of_path stop', ' end_mover']
            if crossing_plan:
                from . import afsim_crossing
                script+=afsim_ferries.actor_callbacks() if ferry else afsim_crossing.callbacks()
                phase='Enter' if crossing_plan['enter_required'] else 'Exit'
                bank=crossing_plan['entry'] if crossing_plan['enter_required'] else crossing_plan['exit']
                if adjudicator.distance_km((origin['lat'],origin['lng']),(bank['lat'],bank['lng']))<.001:
                    script+=[' execute at_time 0.002 sec relative',f'  GtxCross{phase}();',' end_execute']
            script.append('end_platform_type')
        script += [f'platform {identity} {identity + "_type" if moving else "WSF_PLATFORM"}', f' side {team}']
        if moving:
            if native_rules and before.get('combined_arms'):
                from gentactix import missions
                window = sim_clock.duration_seconds(before['mission']['definition']['time_step'])
                speed = missions.move_budget(before, unit, target) * 1000 / window
                if crossing_plan:entities[identity]['move_budget_km']=speed*seconds/1000+entities[identity].get('boat_distance_km',0)
                initial_speed=(f'{controls[identity]["task"]["speed_mps"]:.12f}' if continuous else f'{speed:.9f}')
                script += [' route', f'  position {_location(origin)}', f'  speed {initial_speed} m/s']
                if crossing_plan:
                    previous_point=origin
                    for point in crossing_plan['waypoints']:
                        callback=''
                        if point==crossing_plan['entry'] and crossing_plan['enter_required']:callback=' execute GtxCrossEnter'
                        elif point==crossing_plan['exit']:callback=' execute GtxCrossExit'
                        if callback and adjudicator.distance_km((origin['lat'],origin['lng']),(point['lat'],point['lng']))<.001:continue
                        if point==previous_point:continue
                        script.append(f'  position {_location(point)}'+callback)
                        previous_point=point
                else:script.append(f'  position {_location(target)}')
                script.append(' end_route')
            else:
                script += [' route', f'  position {_location(origin)}', '  speed 1 m/s',
                           f'  position {_location(target)}', f'  time_to_point {seconds:.6f} sec', ' end_route']
        else:
            script += [f' position {_location(origin)}']
        # Split integer degrees and fractional degrees: default ostream precision
        # loses metres at three-digit longitudes. Fractions fit AFSIM int32.
        script += [f' execute at_time {seconds:.6f} sec absolute',
            *([afsim_ferries.sync_expression('PLATFORM')] if ferry else []),
            '  int la = (int)PLATFORM.Latitude();', '  int lo = (int)PLATFORM.Longitude();',
            '  int lf = (int)((PLATFORM.Latitude() - la) * 100000000);',
            '  int of = (int)((PLATFORM.Longitude() - lo) * 100000000);',
            f'  writeln("GTXPOS|{identity}|", la, "|", lf, "|", lo, "|", of);',
            ' end_execute']
        if continuous:script+=afsim_continuous_motion.callbacks()
        script.append('end_platform')
    script += [f'execute at_time {seconds:.6f} sec absolute', ' writeln("GTXCLOCK|", TIME_NOW);', 'end_execute']
    scene = {'script': '\n'.join(script) + '\n', 'entities': entities, 'excluded': excluded,
             'seconds': seconds, 'scope': SCOPE,
             'motion_revision': motion_revision(before) if native_rules and before.get('combined_arms') else 1}
    if continuous:scene['experimental_continuous']=True
    if ferry:scene['script']+=afsim_ferries.compile_boats(scene,before)
    if native_rules and before.get('mission'):
        from . import afsim_rules
        model = afsim_rules.compile_model(scene,before,orders)
        scene.update(native_model=model, scope='AFSIM地理运动及原生教学规则计算；非历史武器、DEM或弹道标定')
        if continuous:scene['scope']='连续机动隔离验证模式；AFSIM实际计算，DSH规划；未通过完整历史会战或跨后端验收'
        scene['script'] += model['script']
    return scene


def parse_observations(text, scene):
    clocks, positions = [], {}
    for line in text.splitlines():
        if line.startswith('GTXCLOCK|'):
            clocks.append(float(line.split('|')[1]))
        elif line.startswith('GTXPOS|'):
            values = line.strip().split('|')
            if len(values) != 6 or values[1] not in scene['entities'] or values[1] in positions:
                raise ValueError('AFSIM实体回传缺项、重复或引用未知身份')
            positions[values[1]] = {'lat': int(values[2]) + int(values[3]) / 1e8,
                                    'lng': int(values[4]) + int(values[5]) / 1e8}
    if len(clocks) != 1 or not math.isfinite(clocks[0]) or abs(clocks[0] - scene['seconds']) > .0001:
        raise ValueError('AFSIM回传时间不等于本轮权威时长')
    if set(positions) != set(scene['entities']):
        raise ValueError('AFSIM实体回传不完整；原战局保持不变')
    for identity, point in positions.items():
        expected = scene['entities'][identity]['target']
        if scene['entities'][identity].get('constrained'):
            origin=scene['entities'][identity]['origin']
            if scene['entities'][identity].get('ferry_transport') and not scene['entities'][identity].get('crossing_plan'):
                from gentactix import crossings
                if crossings.path_position(scene['entities'][identity]['waypoints'][0],scene['entities'][identity]['waypoints'][1:],point,.002) is None:
                    raise ValueError('乘客位置不在登记舟艇通道')
                continue
            if scene['entities'][identity].get('waypoints'):
                from gentactix import crossings
                waypoints=scene['entities'][identity]['waypoints']
                actual=crossings.path_position(origin,waypoints,point)
                planned=sum(adjudicator.distance_km((a['lat'],a['lng']),(b['lat'],b['lng'])) for a,b in zip([origin]+waypoints,waypoints))
                if _coordinate(point) is None or actual is None or actual>min(planned,scene['entities'][identity]['move_budget_km'])+.009:
                    raise ValueError('AFSIM渡运运动不在登记两岸通道内')
                continue
            planned=adjudicator.distance_km((origin['lat'],origin['lng']),(expected['lat'],expected['lng']))
            actual=adjudicator.distance_km((origin['lat'],origin['lng']),(point['lat'],point['lng']))
            if _coordinate(point) is None or actual>planned+.009:raise ValueError('AFSIM受约束运动超过明确目的地预算')
            remaining=adjudicator.distance_km((point['lat'],point['lng']),(expected['lat'],expected['lng']))
            if actual+remaining>planned+.018:raise ValueError('AFSIM运动偏离明确的直达航路')
            continue
        if _coordinate(point) is None or adjudicator.distance_km((point['lat'], point['lng']), (expected['lat'], expected['lng'])) > .009:
            raise ValueError('AFSIM未实际到达命令位置；不拉回坐标，拒绝本轮提交')
    return positions


def apply_observations(before, positions, scene):
    if set(positions) != set(scene['entities']):
        raise ValueError('AFSIM结果名单不完整')
    after = copy.deepcopy(before)
    index = {(team, commands.name_of(unit)): unit for team, unit in commands.iter_units(after)}
    for identity, point in positions.items():
        entry = scene['entities'][identity]
        # A stationary coordinate is retained exactly when the external output
        # agrees at its declared precision. No personnel/equipment field is merged.
        if entry['moving'] or entry.get('ferry_transport'):
            index[(entry['team'], entry['name'])].update(point)
    return after


def run_scene(session, scene, cancel_check=None, progress=None):
    from tools.afsim.launch import layout
    from . import harness_engine as h
    project = Path(__file__).resolve().parent.parent
    import os
    paths = layout(Path(os.environ.get('GENTACTIX_PROJECT_ROOT', project)))
    job = paths['workspace'] / 'jobs' / uuid.uuid4().hex
    job.mkdir(parents=True)
    source = job / 'scene.afsim'
    source.write_text(scene['script'], encoding='ascii')
    (job / 'entities.json').write_text(json.dumps({k: v for k, v in scene.items() if k != 'script'}, ensure_ascii=False))
    started = time.monotonic(); process_id = None; dispatches = []
    try:
        if cancel_check and cancel_check():
            raise RuntimeError('已取消，AFSIM未执行')
        run = h.afsim_call('run_mission', {'scenario': str(source), 'background': True})
        dispatches.append(run['dispatch_id']); process_id = run['payload']['process_id']
        if not re.fullmatch(r'[A-Za-z0-9-]{1,80}', process_id):
            raise RuntimeError('AFSIM进程身份非法')
        polls = 0
        while True:
            if (cancel_check and cancel_check()) or time.monotonic() - started > 120:
                raise RuntimeError('AFSIM已取消或超时，候选未提交')
            result = h.afsim_call('run_mission', {'action': 'status', 'process_id': process_id})
            polls += 1; record = result['payload']
            if progress is not None:
                progress.update(phase='afsim_execution', external_elapsed_ms=int((time.monotonic() - started) * 1000))
            if record.get('status') != 'running':
                dispatches.append(result['dispatch_id'])
                break
            time.sleep(.15)
        if record.get('returncode') != 0 or record.get('status') != 'completed':
            diagnostic = ''
            stdout_path = Path(record.get('stdout_path') or paths['state'] / 'unavailable').resolve()
            if stdout_path.is_relative_to(paths['state'].resolve()) and stdout_path.is_file():
                output = stdout_path.read_text(encoding='utf-8', errors='replace')[:16000]
                diagnostic = next((line.strip()[:700] for line in output.splitlines()
                                   if 'ERROR:' in line or 'FATAL:' in line), '')
            (job / 'failure.json').write_text(json.dumps({'process_id': process_id,
                'status': record.get('status'), 'returncode': record.get('returncode'),
                'diagnostic': diagnostic, 'scope': scene['scope']}, ensure_ascii=False, indent=2))
            raise RuntimeError('AFSIM运行失败' + ('：' + diagnostic if diagnostic else '') +
                               '；原战局保持不变，运行证据：' + str(job))
        log = Path(record['stdout_path']).resolve()
        if not log.is_relative_to(paths['state'].resolve()):
            raise RuntimeError('AFSIM日志不在本项目运行目录内')
        text = log.read_text(encoding='utf-8', errors='replace')
        diagnostic = next((line.strip()[:700] for line in text.splitlines()
                           if re.match(r'^\s*(?:\*{3,}\s*(?:ERROR|FATAL):|GTXERROR\|)',line)), '')
        if diagnostic:
            (job / 'failure.json').write_text(json.dumps({'process_id':process_id,
                'status':record.get('status'),'returncode':record.get('returncode'),
                'reason':'native_output_error','diagnostic':diagnostic,
                'stdout_path':str(log),'scope':scene['scope']},ensure_ascii=False,indent=2))
            raise RuntimeError('AFSIM脚本报告运行时错误，结果已拒收：'+diagnostic+
                               '；原战局保持不变，运行证据：'+str(job))
        if 'Simulation complete' not in text or not re.search(r'WSF Version:\s*2\.9\.', text):
            raise RuntimeError('AFSIM未提供已验证版本的完整结束记录')
        positions = parse_observations(text, scene)
        if scene.get('history_token') and text.splitlines().count('GTXHISTORY|' + scene['history_token']) != 1:
            raise ValueError('AFSIM史料帧回执缺失、重复或身份不符')
        evidence = {'source': 'dsh_native_mcp_controller', 'transport': 'dsh-native-mcp',
            'process_id': process_id, 'dispatch_ids': dispatches, 'status': 'completed', 'returncode': 0,
            'seconds': scene['seconds'], 'wall_ms': round((time.monotonic() - started) * 1000),
            'entity_count': len(positions), 'excluded': scene['excluded'], 'poll_count': polls,
            'scope': scene['scope'], 'artifact': str(job),
            'motion_revision': scene.get('motion_revision', 1),
            'version': re.search(r'WSF Version:\s*([^\r\n]+)', text).group(1)}
        if scene.get('experimental_continuous'):evidence['experimental_continuous']=True
        if scene.get('history_token'):
            evidence['history_token'] = scene['history_token']
        if scene.get('native_model'):
            from . import afsim_rules
            if scene['native_model'].get('settlement_layout'):
                evidence['settlement_layout']=copy.deepcopy(scene['native_model']['settlement_layout'])
            if scene['native_model'].get('combat_revision'):
                evidence.update(combat_revision=scene['native_model']['combat_revision'],
                                combat_profile=copy.deepcopy(scene['native_model']['combat_profile']))
            for revision in ('supply_control_revision','command_control_revision','intelligence_revision','formation_fire_control_revision','legacy_support_revision'):
                if revision in scene['native_model']:
                    evidence[revision]=scene['native_model'][revision]
            if scene['native_model'].get('support_dynamics'):
                evidence['support_dynamics']=copy.deepcopy(scene['native_model']['support_dynamics'])
            if scene['native_model'].get('supply_distribution'):
                evidence['supply_distribution']=copy.deepcopy(scene['native_model']['supply_distribution'])
            if scene['native_model'].get('supply_schedule'):
                evidence['supply_schedule']=copy.deepcopy(scene['native_model']['supply_schedule'])
            evidence['native_effects'] = afsim_rules.parse(text,scene['native_model'],scene)
        (job / 'result.json').write_text(json.dumps({'positions': positions, 'evidence': evidence}, ensure_ascii=False, indent=2))
        return positions, evidence
    except BaseException:
        if process_id:
            try:
                h.afsim_call('run_mission', {'action': 'stop', 'process_id': process_id})
            except Exception:
                pass
        raise
