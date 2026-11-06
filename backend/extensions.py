"""Application plugin seam over DSH execution evidence and atomic battle commits.

Plugins get detached inputs. A required before-commit hook must finish before
the battle changes; plugin failures are visible and never silently lose traces.
Native tools/cancellation are implemented by the separate Cordis plugin.
"""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from gentactix import causal, missions
from gentactix.json_numbers import canonical_numbers

ROOT = Path(__file__).resolve().parent.parent
SECRET = re.compile(r'\bsk-[A-Za-z0-9_-]{16,}\b')


def safe(value):
    if isinstance(value, dict):
        return {k: safe(v) for k, v in value.items() if str(k).lower() not in
                {'reasoning', 'reasoning_content', 'api_key', 'apikey', 'authorization', 'token', 'control_token'}}
    if isinstance(value, (tuple, list)):
        return [safe(v) for v in value]
    return SECRET.sub('[REDACTED]', value) if isinstance(value, str) else value


class PluginRegistry:
    def __init__(self):
        self.plugins = {}

    def register(self, name, **hooks):
        if name in self.plugins:
            raise ValueError('重复插件：' + name)
        self.plugins[name] = hooks

    def emit(self, hook, context):
        outputs = {}
        for name, hooks in self.plugins.items():
            if hook in hooks:
                outputs[name] = hooks[hook](copy.deepcopy(context))
        return outputs

    def describe(self):
        return [{'name': name, 'hooks': list(hooks), 'enabled': True}
                for name, hooks in self.plugins.items()]


registry = PluginRegistry()


def _store(context):
    record = safe(context['record'])
    directory = Path(os.environ.get('GENTACTIX_TRACE_DIR', str(ROOT / '.cache' / 'trajectories')))
    directory = directory / context['session_id'] / f'epoch-{record["epoch"]}'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f'turn-{record["turn"]:06d}.json'
    if path.exists():
        if not context.get('recover_orphan') or record['id'] in context.get('committed_ids', []):
            raise ValueError('轨迹提交已存在，拒绝覆盖：' + record['id'])
        # A crash may leave a trace before its authoritative checkpoint. Preserve
        # that rejected attempt while allowing the unchanged turn to be retried.
        path.rename(path.with_name(path.stem + '.uncommitted-' + uuid.uuid4().hex + '.json'))
    fd, temp = tempfile.mkstemp(prefix='.commit-', suffix='.json', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)
    return {'stored': True, 'trace_id': record['id']}


_hooks = {
    'trajectory': {'before_commit': _store},
    'clock-audit': {'prepare_commit': lambda c: causal.clock_check(c['before'], c['after'], c['time_step'])},
    'causal-attribution': {'analyze': lambda c: causal.analyze(c['records'])},
}
manifest = json.loads((ROOT / 'plugins' / 'runtime.json').read_text())
for _name in manifest['plugins']:
    if _name not in _hooks:
        raise ValueError('未注册的应用插件：' + _name)
    registry.register(_name, **_hooks[_name])


def prepare_record(session, *, before, after, turn, epoch=None, params=None,
                   prompt='', result=None, observer=None, report='', guards=None, recover_orphan=False):
    epoch = session.get('role_epoch', 0) if epoch is None else epoch
    trace_id = f'{session["id"]}:e{epoch}:t{turn}'
    record = {'version': causal.VERSION, 'id': trace_id, 'turn': turn, 'epoch': epoch,
              'time': datetime.now(timezone.utc).isoformat(), 'time_step': session['time_step'],
              'before': copy.deepcopy(before), 'after': copy.deepcopy(after),
              'params': copy.deepcopy(params or {}), 'prompt': prompt,
              'report': report, 'geometry_enabled': session['use_adjudicator'],
              'guards': copy.deepcopy(guards or {}),
              'changes': causal.state_changes(before, after) if before else [],
              'decisions': causal.decisions_from(result or {}, before, after, trace_id),
              'runs': copy.deepcopy(observer.runs if observer is not None else []),
              'tool_executions': copy.deepcopy(observer.tool_executions if observer is not None else [])}
    if session.get('force_organization') is not None:
        from gentactix import force_organization
        organization=force_organization.state(session)
        record['force_organization']={k:copy.deepcopy(organization[k]) for k in ('version','revision','groups')}
        record['force_organization_hash']=missions.digest(record['force_organization'])
    if (result or {}).get('command_context') is not None:
        record['command_context'] = copy.deepcopy(result['command_context'])
    if (result or {}).get('force_task_execution') is not None:
        record['force_task_execution']=copy.deepcopy(result['force_task_execution'])
    command_state=session.get('command_state') or {}
    tasks={o.get('task_context',{}).get('task_id') for o in command_state.get('orders',[])}-{None}
    if tasks:
        record['force_task_plans']={k:copy.deepcopy(v) for k,v in command_state.get('task_plans',{}).items() if k in tasks}
    if (result or {}).get('external_execution') is not None:
        record['external_execution'] = copy.deepcopy(result['external_execution'])
    refs = [{'session_id': run['session_id'], 'seq': event.get('seq')}
            for run in record['runs'] for event in run.get('events', [])
            if event.get('type') == 'assistant/message' and isinstance(event.get('seq'), int)]
    for decision in record['decisions']:
        eligible = [run for run in record['runs'] if run['id'] in decision.get('run_ids', [])]
        local_refs = [{'session_id': run['session_id'], 'seq': e['seq']} for run in eligible
                      for e in run.get('events', []) if e.get('type') == 'assistant/message' and isinstance(e.get('seq'), int)]
        decision['dsh_event_ref'] = (local_refs[-1] if local_refs else None) if 'source' in decision else (refs[-1] if refs else None)
    context = {'before': before, 'after': after, 'time_step': session['time_step']}
    prepared = registry.emit('prepare_commit', context)
    record['clock'] = prepared.get('clock-audit') if before else {'status': 'initial'}
    record = safe(record)
    registry.emit('before_commit', {'record': record, 'session_id': session['id'],
        'recover_orphan': recover_orphan, 'committed_ids': [r['id'] for r in session.get('trajectory', [])]})
    return record


def discard_uncommitted(session, record):
    if any(r['id'] == record['id'] for r in session.get('trajectory', [])):
        return
    directory = Path(os.environ.get('GENTACTIX_TRACE_DIR', str(ROOT / '.cache' / 'trajectories')))
    path = directory / session['id'] / f'epoch-{record["epoch"]}' / f'turn-{record["turn"]:06d}.json'
    if path.exists():
        path.rename(path.with_name(path.stem + '.uncommitted-' + uuid.uuid4().hex + '.json'))


def persist_artifact(session, kind, value):
    directory = Path(os.environ.get('GENTACTIX_TRACE_DIR', str(ROOT / '.cache' / 'trajectories'))) / session['id'] / f'epoch-{session.get("role_epoch", 0)}' / kind
    directory.mkdir(parents=True, exist_ok=True)
    artifact = safe(value)
    # Each analysis/branch is immutable and linked back to its source trace.
    identifier = uuid.uuid4().hex
    path = directory / (identifier + '.json')
    with path.open('x', encoding='utf-8') as stream:
        json.dump(artifact, stream, ensure_ascii=False, indent=2, allow_nan=False)
    return identifier


def analyze(records):
    outputs = registry.emit('analyze', {'records': records})
    if 'causal-attribution' not in outputs:
        raise RuntimeError('因果分析插件未启用')
    return outputs['causal-attribution']


def record_failure(session, observer, phase, error):
    if observer is None:
        return
    clock=observer.clock_snapshot()
    value = {'phase': phase, 'turn': session.get('turn_count'), 'status': 'not_committed',
             'label':observer.label,**clock,
             'error': safe(str(error)[:700]), 'runs': observer.runs,
             'events': list(observer._events.values())}
    identifier = persist_artifact(session, 'failed-operations', value)
    session.setdefault('failed_operations', []).append({'id': identifier, 'phase': phase,
        'turn': session.get('turn_count'), 'status': 'not_committed', 'runs': observer.runs,
        'operation_id':observer.operation_id,'error':value['error'],
        'cancelled':bool(session.get('cancel_requested')),'label':observer.label,**clock})
    # Do not depend on graceful shutdown to preserve a rejected operation.
    from . import session_store
    try:
        session_store.save({**session,'cancel_requested':False})
    except (OSError,ValueError,TypeError):
        from .harness_engine import ENGINE_NOTICES
        ENGINE_NOTICES.append(dict(level='warning',message='失败记录检查点写入未成功；内存记录和原战局保留，请导出战局。'))


def event_summary(event, session_id):
    """Retain execution facts and native tool I/O, never hidden reasoning text."""
    out = {k: event[k] for k in ('seq', 'time', 'type') if k in event}
    out['session_id'] = session_id
    data = event.get('data') or {}
    for key in ('turn', 'step', 'callId', 'name', 'reason', 'usage'):
        if key in data:
            out[key] = safe(data[key])
    if event.get('type') == 'request/header':
        header = data.get('header') or {}
        out['tools'] = [t.get('name') for t in header.get('tools', []) if isinstance(t, dict)]
        config = header.get('config') or {}
        out['request_config'] = {k: config.get(k) for k in ('provider', 'model', 'reasoningEffort', 'maxTokens')}
    if event.get('type') in ('tool/call', 'tool/result'):
        for key in ('arguments', 'message', 'isError', 'error'):
            if key in data:
                out[key] = safe(data[key])
    return safe(out)


def public_tool_results(observer, name, *, start=0):
    """Read paired public tool I/O from this operation, excluding private text.

    Domain validators must still verify the current snapshot and candidate
    digest. A successful runtime/tool result is never a battle commit.
    """
    calls = {}; seen = set()
    for run in observer.runs[start:]:
        for event in run.get('events', []):
            sid = event.get('session_id'); seq = event.get('seq')
            if not isinstance(sid, str) or not sid or type(seq) is not int:
                continue
            stamp = (sid, seq, event.get('type'))
            if stamp in seen:
                continue
            seen.add(stamp)
            if event.get('type') == 'tool/call' and event.get('name') == name:
                call_id = event.get('callId'); args = event.get('arguments')
                if not isinstance(call_id, str) or not call_id:
                    continue
                try:
                    args = json.loads(args) if isinstance(args, str) else args
                except json.JSONDecodeError:
                    continue
                calls[(sid, call_id)] = (seq, args)
            elif event.get('type') == 'tool/result':
                message = event.get('message')
                if not isinstance(message, dict):
                    continue
                key = (sid, message.get('toolCallId'))
                if key not in calls or event.get('isError') or message.get('isError'):
                    continue
                call_seq, args = calls[key]
                if seq <= call_seq:
                    continue
                text = '\n'.join(b.get('text', '') for b in (message.get('content') or [])
                                 if isinstance(b, dict) and b.get('type') == 'text' and isinstance(b.get('text'), str))
                try:
                    reply = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(reply, dict) and reply.get('ok') is True and reply.get('readonly') is True:
                    yield args, reply, dict(session_id=sid, call_id=key[1])
