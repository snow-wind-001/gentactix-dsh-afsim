"""Model-authored JSON edits replayed from linked public Native tool events.

The invocation-local reference map is reconstructed every time, never retained.
No world execution, stock calculation or implicit proposal repair occurs here.
"""
import copy
import json
import re
from types import SimpleNamespace

from gentactix import missions
from .extensions import canonical_numbers,event_summary
from .effect_contract import SCHEMA

FULL_TOOL='preview_turn_effects'
AMEND_TOOL='amend_turn_effects'
REFERENCE_VERSION='turn-candidate-reference-1'
PREVIEW_VERSION='turn-effects-preview-1'


def digest(value):
    return isinstance(value,str) and re.fullmatch('[a-f0-9]{64}',value) is not None


def reference(ctx,tool,args,candidate):
    spec=ctx['turn_preview'];before=missions.digest(ctx['session']['war_state'])
    args=canonical_numbers(copy.deepcopy(args));candidate=canonical_numbers(copy.deepcopy(candidate))
    json.dumps(args,allow_nan=False);json.dumps(candidate,allow_nan=False)
    return dict(candidate_ref=missions.digest(dict(version=REFERENCE_VERSION,operation_id=spec['operation_id'],
        before_hash=before,tool=tool,arguments=args)),candidate_hash=missions.digest(candidate),
        before_hash=before,operation_id=spec['operation_id'])


def edit(candidate,args):
    if (not isinstance(args,dict) or set(args)!={'base_ref','edits'} or not digest(args['base_ref'])
            or not isinstance(args['edits'],list) or not 1<=len(args['edits'])<=128):
        raise ValueError('修订须提供本操作base_ref及1至128项显式edits，不提交世界或隐含计算')
    result=copy.deepcopy(candidate)
    for index,change in enumerate(args['edits']):
        if (not isinstance(change,dict) or change.get('op') not in ('add','replace','remove')
                or set(change)!=({'op','path'} if change.get('op')=='remove' else {'op','path','value'})):
            raise ValueError(f'edits[{index}]须为add/replace加value，或remove且不带value')
        path=change['path']
        if not isinstance(path,str) or not path.startswith('/') or len(path)>512 or re.search(r'~(?![01])',path):
            raise ValueError(f'edits[{index}].path须为有效有界JSON Pointer')
        parts=[v.replace('~1','/').replace('~0','~') for v in path[1:].split('/')]
        if parts[0] not in set(SCHEMA['properties'])-{'report','source_note'}:
            raise ValueError(f'edits[{index}].path只允许候选效果字段；战报使用submit_turn_report，不能编辑宿主或来源')
        parent=result
        def key(container,part,*,append=False):
            if isinstance(container,dict):return part
            if isinstance(container,list):
                if part=='-' and append:return len(container)
                if not re.fullmatch('0|[1-9][0-9]*',part):raise ValueError('数组路径须为非负标准整数')
                number=int(part)
                if not 0<=number<len(container)+(1 if append else 0):raise ValueError('数组路径越界')
                return number
            raise ValueError('修订路径的父级须为对象或数组')
        try:
            for part in parts[:-1]:parent=parent[key(parent,part)]
            selected=key(parent,parts[-1],append=change['op']=='add')
            if change['op']=='add':
                if isinstance(parent,list):parent.insert(selected,copy.deepcopy(change['value']))
                else:parent[selected]=copy.deepcopy(change['value'])
            else:
                if isinstance(parent,dict) and selected not in parent:raise ValueError('replace/remove路径不存在')
                if change['op']=='remove':del parent[selected]
                else:parent[selected]=copy.deepcopy(change['value'])
        except (KeyError,IndexError,TypeError,ValueError) as exc:
            raise ValueError(f'edits[{index}] {path}：{exc}') from exc
    return canonical_numbers(result)


def observer(payload,key):
    events=payload.get(key);sid=payload.get('session_id')
    if (not isinstance(events,list) or not events or len(events)%2 or not isinstance(sid,str) or not sid):
        raise ValueError('须由Native运行时提供完整的公开候选调用/结果链')
    previous=-1
    for index,event in enumerate(events):
        if not isinstance(event,dict) or event.get('type')!=('tool/call' if index%2==0 else 'tool/result'):
            raise ValueError('公开候选证据仅接受按序配对的领域工具事件')
        if type(event.get('seq')) is not int or event['seq']<=previous:raise ValueError('公开候选证据序号必须严格递增')
        previous=event['seq']
        if index%2==0 and event.get('data',{}).get('name') not in (FULL_TOOL,AMEND_TOOL):
            raise ValueError('公开候选证据不得包含聊天、推理或其他工具')
    return SimpleNamespace(runs=[dict(events=[event_summary(e,sid) for e in events])])


def candidates(observer,ctx):
    """Yield replayable raw proposals and paired replies, including failed shapes."""
    calls={};seen=set();catalog={}
    for run in observer.runs:
        for event in run.get('events',[]):
            sid=event.get('session_id');seq=event.get('seq');kind=event.get('type');stamp=(sid,seq,kind)
            if type(seq) is not int or not isinstance(sid,str) or not sid or stamp in seen:continue
            seen.add(stamp)
            if kind=='tool/call' and event.get('name') in (FULL_TOOL,AMEND_TOOL):
                args=event.get('arguments')
                try:args=json.loads(args) if isinstance(args,str) else args
                except ValueError:continue
                calls[(sid,event.get('callId'))]=(seq,event['name'],args)
            elif kind=='tool/result':
                message=event.get('message') or {};pair=calls.get((sid,message.get('toolCallId')))
                if not pair or seq<=pair[0] or event.get('isError') or message.get('isError'):continue
                try:reply=json.loads('\n'.join(b.get('text','') for b in message.get('content',[]) if b.get('type')=='text'))
                except ValueError:continue
                if not isinstance(reply,dict) or reply.get('version')!=PREVIEW_VERSION or reply.get('readonly') is not True:continue
                _,tool,args=pair
                if tool==FULL_TOOL:
                    if not isinstance(args,dict) or set(args)!={'candidate'} or not isinstance(args['candidate'],dict):continue
                    raw=canonical_numbers(copy.deepcopy(args['candidate']))
                else:
                    if 'candidate_ref' not in reply:continue  # Unresolved or malformed amendment.
                    if not isinstance(args,dict) or args.get('base_ref') not in catalog:
                        raise ValueError('修订链缺少本操作的原始候选证据')
                    raw=edit(catalog[args['base_ref']],args)
                if 'candidate_ref' in reply:
                    expected=reference(ctx,tool,args,raw)
                    if reply.get('operation_id')!=expected['operation_id'] or reply.get('before_hash')!=expected['before_hash']:
                        continue
                    if any(reply.get(k)!=v for k,v in expected.items()):raise ValueError('公开候选引用与完整参数、修订链或候选指纹不符')
                    catalog[reply['candidate_ref']]=raw
                yield raw,reply,sid,message['toolCallId']


def source(ctx,payload,base_ref):
    if not digest(base_ref):raise ValueError('base_ref须为本操作候选引用')
    found=None
    for raw,reply,_,_ in candidates(observer(payload,'candidate_events'),ctx):
        if reply.get('candidate_ref')==base_ref:found=raw
    if found is None:raise ValueError('没有匹配当前操作/轮初世界的公开候选引用；不使用旧轮次或其他会话候选')
    return found
