"""Lossless, self-contained checkpoint factoring; never a battle-state format.

Only exactly repeated large definitions/source values are factored. Each
restored occurrence is a detached ordinary JSON value, not a shared mutable
definition. Public expanded exports and world hashes remain unchanged.
"""
import copy
import hashlib
import json
import re
from collections import Counter

from gentactix.observation_codec import SOURCE_FIELDS

V1='gentactix-session-v1'
V2='gentactix-session-v2'
FIELDS=SOURCE_FIELDS|{'definition','historical_definition','historical_initial','source_replay_snapshot'}
MIN_BYTES=2048
MAX_BYTES=1024*1024*1024


def _wire(value):
    try:return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
    except (ValueError,TypeError,RecursionError) as exc:raise ValueError('存档须为有限、可序列化的JSON树') from exc


def _sha(wire):return hashlib.sha256(wire).hexdigest()


def _plain(value):
    if isinstance(value,dict):return all(type(k) is str and _plain(v) for k,v in value.items())
    if isinstance(value,(list,tuple)):return all(_plain(v) for v in value)
    return value is None or type(value) in (str,int,float,bool)


def encode(session,*,_original=None):
    if not isinstance(session,dict):raise ValueError('存档会话须为对象')
    original=_wire(session) if _original is None else _original
    if not isinstance(original,bytes):raise ValueError('存档序列化结果须为字节')
    legacy=lambda:dict(format=V1,session=copy.deepcopy(session))
    # Preserve the old serializer's behavior for non-string mapping keys.
    if not _plain(session):return legacy()
    candidates={};values={};wires={};counts=Counter()
    def collect(value,path=()):
        if isinstance(value,dict):
            for key,row in value.items():
                here=path+(key,)
                if key in FIELDS and isinstance(row,(dict,list,str)):
                    raw=_wire(row)
                    if len(raw)>=MIN_BYTES:
                        identity=_sha(raw)
                        if identity in wires and wires[identity]!=raw:
                            raise ValueError('冻结定义指纹冲突')
                        values.setdefault(identity,row);wires.setdefault(identity,raw)
                        candidates[here]=identity;counts[identity]+=1
                        continue
                collect(row,here)
        elif isinstance(value,(list,tuple)):
            for index,row in enumerate(value):collect(row,path+(index,))
    collect(session)
    selected={identity for identity,count in counts.items() if count>1}
    if not selected:return legacy()
    references=[]
    def body(value,path=()):
        identity=candidates.get(path)
        if identity in selected:
            references.append(dict(path=list(path),digest=identity));return None
        if path in candidates:return copy.deepcopy(value)
        if isinstance(value,dict):return {k:body(v,path+(k,)) for k,v in value.items()}
        if isinstance(value,(list,tuple)):return [body(v,path+(i,)) for i,v in enumerate(value)]
        return copy.deepcopy(value)
    packed=dict(format=V2,session=body(session),definitions={key:copy.deepcopy(values[key]) for key in sorted(selected)},
                definition_refs=references,session_digest=_sha(original),expanded_bytes=len(original))
    return packed if len(_wire(packed))+1024<len(original) else legacy()


def _slot(value,path):
    if not isinstance(path,list) or not path or type(path[-1]) is not str or path[-1] not in FIELDS:
        raise ValueError('冻结定义路径非法')
    current=value
    for index,part in enumerate(path):
        if isinstance(current,dict) and type(part) is str and part in current:pass
        elif isinstance(current,list) and type(part) is int and 0<=part<len(current):pass
        else:raise ValueError('冻结定义路径不存在')
        if index==len(path)-1:return current,part
        current=current[part]


def decode(document,*,max_bytes=MAX_BYTES):
    if not isinstance(document,dict) or not isinstance(document.get('session'),dict):
        raise ValueError('存档缺少会话对象')
    if document.get('format')==V1:
        _wire(document['session']);return copy.deepcopy(document['session'])
    if (document.get('format')!=V2 or set(document)!={'format','session','definitions','definition_refs','session_digest','expanded_bytes'}
            or not isinstance(document['definitions'],dict) or not document['definitions']
            or not isinstance(document['definition_refs'],list) or not document['definition_refs']):
        raise ValueError('存档版本或冻结定义字段非法')
    if type(max_bytes) is not int or max_bytes<=0:raise ValueError('恢复大小上限须为正整数')
    if type(document['expanded_bytes']) is not int or document['expanded_bytes']<=0:
        raise ValueError('展开大小非法')
    table=document['definitions'];lengths={}
    for identity,value in table.items():
        if (not isinstance(identity,str) or re.fullmatch('[a-f0-9]{64}',identity) is None
                or not isinstance(value,(dict,list,str))):raise ValueError('冻结定义条目非法')
        raw=_wire(value)
        if _sha(raw)!=identity:raise ValueError('冻结定义内容与指纹不一致')
        lengths[identity]=len(raw)
    size=len(_wire(document['session']));seen=set();used=set()
    for row in document['definition_refs']:
        if (not isinstance(row,dict) or set(row)!={'path','digest'}
                or not isinstance(row['digest'],str) or row['digest'] not in table):
            raise ValueError('冻结定义引用缺失')
        parent,key=_slot(document['session'],row['path']);path=tuple(row['path'])
        if parent[key] is not None or path in seen:raise ValueError('冻结定义位置非空或重复')
        seen.add(path);used.add(row['digest']);size+=lengths[row['digest']]-4
        if size>max_bytes:raise ValueError('存档展开后大小超过恢复上限')
    if used!=set(table) or size!=document['expanded_bytes']:raise ValueError('冻结定义集合或展开大小不一致')
    result=copy.deepcopy(document['session'])
    for row in document['definition_refs']:
        parent,key=_slot(result,row['path']);parent[key]=copy.deepcopy(table[row['digest']])
    if _sha(_wire(result))!=document['session_digest']:raise ValueError('完整存档指纹不一致')
    return result
