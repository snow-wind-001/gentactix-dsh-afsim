"""Atomic battle checkpoints, independent of SDK session memory."""
import copy
import json
import os
from pathlib import Path
import re
import threading

from . import checkpoint_codec

_WRITE_LOCK = threading.RLock()
# Persistence metadata only: no world, candidate, or old trajectory is cached.
_WRITTEN = {}

ROOT = Path(__file__).resolve().parent.parent


def directory():
    return Path(os.environ.get('GENTACTIX_SESSION_DIR', str(ROOT / '.cache' / 'sessions')))


def serializable(session):
    return copy.deepcopy({k: v for k, v in session.items() if k not in ('adj_spec', 'active_observer', 'progress')})


def _stamp(path):
    stat=path.stat()
    return (stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)


def _signature(session,wire=None):
    value={k:v for k,v in session.items() if k not in ('adj_spec','active_observer','progress')}
    if 'cancel_requested' not in value:
        value['cancel_requested']=False;wire=None
    return checkpoint_codec._sha(wire if wire is not None else checkpoint_codec._wire(value))


def save(session):
    # Creation and checkpoints may overlap; a shared .tmp must have one writer.
    with _WRITE_LOCK:
        _save(session)


def _save(session):
    path = directory() / (session['id'] + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    current={k:v for k,v in session.items() if k not in ('adj_spec','active_observer','progress')}
    wire=checkpoint_codec._wire(current);detached=False
    # Legacy flag normalization must inspect the same captured content. A later
    # input change must not make the cache describe a different saved snapshot.
    if 'cancel_requested' not in current:
        if checkpoint_codec._plain(current):current=json.loads(wire)
        else:
            current=serializable(session);wire=checkpoint_codec._wire(current)
        detached=True
    signature=_signature(current,wire)
    cache_key=str(path.resolve())
    saved=_WRITTEN.get(cache_key)
    stamp=_stamp(path) if path.exists() else None
    if saved and saved[0]==stamp and saved[1]==signature:return
    if stamp is not None and (not saved or saved[0]!=stamp):
        try:
            previous=checkpoint_codec.decode(json.loads(path.read_text(encoding='utf-8')))
        except (ValueError,TypeError,KeyError) as exc:
            raise ValueError('已有检查点无法读取，原文件保留') from exc
        if previous.get('id')!=session['id']:raise ValueError('已有检查点身份不一致，原文件保留')
        # Startup clears cancellation; an idle shutdown must not migrate or
        # reformat an otherwise untouched legacy checkpoint.
        previous['cancel_requested']=False
        if _signature(previous)==signature:
            _WRITTEN[cache_key]=(stamp,signature);return
    # Own the exact JSON wire snapshot before encoding. The transaction already
    # cloned its working state; a repeated save need not clone old history again.
    # Non-string mapping keys retain the legacy codec's type/format behavior.
    if not detached:
        if checkpoint_codec._plain(current):
            current=json.loads(wire)
        else:
            current=serializable(session)
            wire=checkpoint_codec._wire(current);signature=_signature(current,wire)
    value = checkpoint_codec.encode(current,_original=wire)
    temporary = path.with_suffix('.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _WRITTEN[cache_key]=(_stamp(path),signature)
    except BaseException:
        try:temporary.unlink(missing_ok=True)
        except OSError:pass
        raise


def validate(session):
    """Validate durable state before import/restore can make it visible to the UI."""
    from gentactix import sim_clock
    if not isinstance(session, dict) or not re.fullmatch(r'[a-f0-9]{12}', str(session.get('id', ''))):
        raise ValueError('会话ID不合法')
    if session.get('execution_backend', 'narrative') not in ('narrative', 'afsim'):
        raise ValueError('会话执行后端未知，不能静默改用其他引擎')
    if session.get('product_mode') is not None:
        if session['product_mode'] not in ('analysis','historical','synthetic'):
            raise ValueError('未知使用类型')
        if (session['product_mode']=='analysis')!=(session.get('simulation_mode')=='replay'):
            raise ValueError('使用类型与史料/开放模式不一致')
    source_snapshot = session.get('source_replay_snapshot')
    if source_snapshot is not None:
        from gentactix import history_replay
        if session.get('product_mode') != 'analysis' or session.get('simulation_mode') != 'replay':
            raise ValueError('固定来源包只能绑定历史回溯会话')
        source_frame = history_replay.frame_pinned(source_snapshot, 0)
        if source_frame['history_replay']['battle'] != session.get('battle_choice'):
            raise ValueError('固定来源包与会话战役不一致')
    historical_definition = session.get('historical_definition')
    construction=session.get('scenario_construction')
    if construction is not None and (not isinstance(construction,dict)
            or not isinstance(construction.get('id'),str) or not construction['id'].strip()):
        raise ValueError('想定构建记录缺少有效id，不能恢复会导致页面读取失败的存档')
    if historical_definition is not None:
        from gentactix import historical_operations, synthetic_history, phase_continuity
        synthetic=bool(historical_definition.get('historical_synthetic'))
        expected = (phase_continuity.definition(historical_definition['phase_continuation']) if historical_definition.get('phase_continuation') else
                    synthetic_history.from_binding(historical_definition['historical_synthetic']) if synthetic else
                    historical_operations.from_binding(historical_definition.get('historical_calculation')))
        if (expected != historical_definition or expected['id'] != session.get('mission_id')
                or expected['battle'] != session.get('battle_choice') or session.get('product_mode') != ('synthetic' if synthetic else 'historical')
                or session.get('simulation_mode') != 'open'):
            raise ValueError('历史参数化定义与会话身份不一致')
    from gentactix import formation_runtime
    formation_runtime.validate_session(session)
    origin=session.get('branch_origin') or {}
    if not isinstance(origin,dict):raise ValueError('分支来源须为对象')
    if session.get('command_identity_origin') is not None or origin.get('identity_policy'):
        from gentactix import commands
        commands.validate_identity_origin(session)
    if session.get('command_state') is not None:
        from gentactix import commands
        commands.validate_saved(session)
    if session.get('force_organization') is not None:
        from gentactix import force_organization
        force_organization.validate(session)
    from gentactix.state import DEFAULT_SESSION_STATE
    required = set(DEFAULT_SESSION_STATE) | {'time_step', 'use_adjudicator', 'battle_choice', 'use_rag', 'use_live_intel'}
    if required - session.keys():
        raise ValueError('检查点缺少完整会话字段')
    if not isinstance(session.get('scenario_input'), str):
        raise ValueError('缺少有效想定正文')
    sim_clock.duration_seconds(session.get('time_step'))
    for field in ('turn_count', 'role_epoch'):
        value = session.get(field, 0)
        if type(value) is not int or value < 0:
            raise ValueError(f'{field}必须是非负整数')
    for field in ('history', 'chat_messages', 'trajectory', 'counterfactuals', 'decision_log'):
        if not isinstance(session.get(field, []), list):
            raise ValueError(f'{field}必须是列表')
    if any(not isinstance(item, str) for item in session.get('history', [])):
        raise ValueError('战报必须是文本')
    for field in ('chat_messages', 'trajectory', 'counterfactuals', 'decision_log'):
        if any(not isinstance(item, dict) for item in session.get(field, [])):
            raise ValueError(f'{field}条目必须是对象')
    for field in ('war_state', 'last_war_state'):
        world = session.get(field)
        if world is None:
            continue
        if not isinstance(world, dict) or not isinstance(world.get('current_time'), str):
            raise ValueError('战局必须包含有效时间')
        if world.get('history_replay'):
            from gentactix import history_replay
            history_replay.validate(world)
            if source_snapshot is not None:
                if (world['history_replay'].get('version') != history_replay.PINNED_VERSION
                        or world['history_replay'].get('source_snapshot') != source_snapshot['pack']
                        or world.get('historical_initial') != source_snapshot['initial']):
                    raise ValueError('来源帧与本局固定来源／部队档案不一致')
            elif world['history_replay'].get('version') == history_replay.PINNED_VERSION:
                raise ValueError('版本化来源帧缺少本局固定来源包')
            if session.get('simulation_mode') != 'replay' or (session.get('execution_backend') != 'afsim' and session.get('product_mode')!='analysis') or session.get('mission_id'):
                raise ValueError('史料帧只能存在于AFSIM严格回放会话')
            if world['history_replay']['battle'] != session.get('battle_choice'):
                raise ValueError('史料帧与会话战役不一致')
            if field == 'war_state' and world['history_replay']['cursor'] != session['turn_count']:
                raise ValueError('史料事件序号与会话不一致')
        if world.get('air_operations'):
            from . import afsim_air
            afsim_air.state(world)
        if world.get('mission'):
            from gentactix import missions
            missions.validate(world)
            if (world['mission']['definition'].get('historical_calculation') or world['mission']['definition'].get('historical_synthetic')) and world['mission']['definition'] != historical_definition:
                raise ValueError('历史参数化战局缺少本局固定计算定义')
            if session.get('mission_id') != world['mission']['id'] or session.get('simulation_mode', 'open') != 'open':
                raise ValueError('会话模式或想定身份不一致')
            if session.get('synthetic_configuration') != world['mission']['definition'].get('synthetic_configuration'):
                raise ValueError('会话自定义编制与战局定义不一致')
            if (session.get('synthetic_configuration') or {}).get('historical_basis'):
                origin=session.get('scenario_construction') or {}
                if origin.get('definition_hash')!=world['mission']['definition_hash'] or origin.get('construction',{}).get('source')!='dsh_native_skill':
                    raise ValueError('派生演习缺少一致的DSH skill构建证据')
        for team in ('red_units', 'blue_units'):
            if not isinstance(world.get(team), list) or any(not isinstance(u, dict) for u in world[team]):
                raise ValueError(f'{team}必须是单位对象列表')
    if session.get('plotting_state') is not None:
        from gentactix import military_symbols
        military_symbols.validate_state(session['plotting_state'], session)
    # JSON NaN/Infinity is accepted by Python but breaks browser JSON parsing.
    json.dumps(session, allow_nan=False)


def load_all():
    sessions, errors = {}, []
    for path in directory().glob('*.json'):
        try:
            stamp=_stamp(path)
            value = json.loads(path.read_text(encoding='utf-8'))
            session = checkpoint_codec.decode(value)
            if not re.fullmatch(r'[a-f0-9]{12}', session['id']) or path.stem != session['id']:
                raise ValueError('invalid checkpoint identity')
            validate(session)
            session.update(adj_spec=None, active_observer=None, progress=None, cancel_requested=False)
            sessions[session['id']] = session
            if _stamp(path)==stamp:_WRITTEN[str(path.resolve())]=(stamp,_signature(session))
        except (ValueError, KeyError, TypeError, OSError):
            errors.append(path.name)
    return sessions, errors


def remove(session_id):
    with _WRITE_LOCK:
        path=directory()/(session_id+'.json')
        path.unlink(missing_ok=True)
        _WRITTEN.pop(str(path.resolve()),None)
