"""Reversible source-text references for model observations, not battle state.

Only repeated long provenance strings are encoded. Numeric data and identities
keep their original paths/types. V1 embeds source text; the Native-only V2 may
bind retrievable text to existing unit-detail queries and the current world.
"""
from collections import Counter
import copy
import hashlib
import json
import re

VERSION='observation-provenance-1'
DETAIL_VERSION='observation-provenance-2'
TABLE='_provenance'
PREFIX='~source:'
MIN_CHARS=160
SOURCE_FIELDS={'source','calculation_source','assumption','assumptions','parameter_sources','source_note'}


def _json(value):
    try:return json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False)
    except (TypeError,ValueError,RecursionError) as exc:
        raise ValueError('观察须为有限、可序列化的JSON树') from exc


def _validate(value):
    _json(value)  # Also rejects cycles before walking.
    def visit(item):
        if isinstance(item,dict):
            if any(type(k) is not str for k in item):raise ValueError('观察对象键须为字符串')
            for v in item.values():visit(v)
        elif isinstance(item,list):
            for v in item:visit(v)
        elif item is not None and type(item) not in (str,int,float,bool):
            raise ValueError('观察只接受JSON对象、数组及标量')
    visit(value)
    if not isinstance(value,dict):raise ValueError('观察根须为JSON对象')


def _digest(value):return hashlib.sha256(_json(value).encode()).hexdigest()


def _source_id(text):return 's'+hashlib.sha256(text.encode()).hexdigest()[:16]


def _walk(value,transform,metadata=False):
    if isinstance(value,dict):
        return {k:_walk(v,transform,metadata or k in SOURCE_FIELDS) for k,v in value.items()}
    if isinstance(value,list):return [_walk(v,transform,metadata) for v in value]
    return transform(value) if metadata and isinstance(value,str) else value


def source_texts(value):
    """Long metadata text only; identities and physical values are not sources."""
    found=set()
    def collect(text):
        if len(text)>=MIN_CHARS:found.add(text)
        return text
    _walk(value,collect)
    return found


def _detail_query(query):
    if (not isinstance(query,dict) or set(query)!={'ids','limit','detail'}
            or not isinstance(query['ids'],list) or len(query['ids'])!=1
            or not isinstance(query['ids'][0],str) or not query['ids'][0]
            or type(query['limit']) is not int or query['limit']!=1 or query['detail'] is not True):
        raise ValueError('来源详情须按一个完整单位ID读取现有detail=true观察')
    return copy.deepcopy(query)


def _world_version(value):
    if not isinstance(value,str) or re.fullmatch('[a-f0-9]{64}',value) is None:
        raise ValueError('来源详情须绑定当前世界指纹')
    return value


def encode(value,*,source_queries=None,world_version=None):
    """Return an independent observation; retain the old shape if no space is saved."""
    _validate(value)
    if source_queries is not None:
        if not isinstance(source_queries,dict):raise ValueError('来源查询须为已知正文到单位详情的映射')
        _world_version(world_version)
    if TABLE in value:raise ValueError('只读来源表字段已存在，不能叠加编码')
    counts=Counter()
    def collect(text):
        if len(text)>=MIN_CHARS:counts[text]+=1
        return text
    _walk(value,collect)
    selected={text for text,count in counts.items() if count>1}
    if not selected:return copy.deepcopy(value)
    sources={}
    for text in sorted(selected):
        identity=_source_id(text)
        if identity in sources and sources[identity]!=text:raise ValueError('来源引用标识冲突')
        sources[identity]=text
    def replace(text):
        if text in selected:return PREFIX+_source_id(text)
        return '~~'+text if text.startswith('~') else text
    result=_walk(value,replace)
    result[TABLE]=dict(version=VERSION,sources=sources,original_digest=_digest(value))
    if source_queries:
        deferred={i:dict(query=_detail_query(source_queries[t]),digest=hashlib.sha256(t.encode()).hexdigest())
                  for i,t in sources.items() if t in source_queries}
        if deferred:
            detailed=copy.deepcopy(result)
            detailed[TABLE]=dict(version=DETAIL_VERSION,sources={i:t for i,t in sources.items() if i not in deferred},
                deferred=deferred,world_version=world_version,original_digest=_digest(value))
            if len(_json(detailed))<len(_json(result)):result=detailed
    return result if len(_json(result))<len(_json(value)) else copy.deepcopy(value)


def decode(value,*,resolve=None):
    """Validate/decode an observation for inspection; never apply it as authority."""
    _validate(value)
    if TABLE not in value:return copy.deepcopy(value)
    meta=value[TABLE]
    if not isinstance(meta,dict):raise ValueError('来源观察编码版本或字段非法')
    deferred=meta.get('deferred',{})
    fields={'version','sources','original_digest'}
    if meta.get('version')==DETAIL_VERSION:fields|={'deferred','world_version'}
    if (set(meta)!=fields or meta['version'] not in (VERSION,DETAIL_VERSION)
            or not isinstance(meta['sources'],dict) or not isinstance(deferred,dict)):
        raise ValueError('来源观察编码版本或字段非法')
    sources=copy.deepcopy(meta['sources']);seen=set()
    if meta['version']==DETAIL_VERSION:
        _world_version(meta['world_version'])
        if not deferred or set(deferred)&set(sources) or not callable(resolve):
            raise ValueError('原生来源详情缺少只读解析器或引用集合非法')
        replies={}
        for identity,entry in deferred.items():
            if not isinstance(entry,dict) or set(entry)!={'query','digest'}:
                raise ValueError('原生来源详情字段非法')
            query=_detail_query(entry['query']);key=query['ids'][0]
            if key not in replies:replies[key]=resolve(query)
            reply=replies[key]
            _validate(reply)
            if (not isinstance(reply,dict) or reply.get('world_version')!=meta['world_version']
                    or not isinstance(reply.get('units'),list) or len(reply['units'])!=1
                    or not isinstance(reply['units'][0],dict) or reply['units'][0].get('id')!=key):
                raise ValueError('原生来源详情不属于绑定世界或单位')
            texts=[t for t in source_texts(reply['units'][0]) if _source_id(t)==identity
                   and hashlib.sha256(t.encode()).hexdigest()==entry['digest']]
            if len(texts)!=1:raise ValueError('原生来源正文缺失或指纹不一致')
            sources[identity]=texts[0]
    if not sources or any(not isinstance(t,str) or i!=_source_id(t) for i,t in sources.items()):
        raise ValueError('来源引用正文或标识非法')
    def restore(text):
        if text.startswith('~~'):return text[2:]
        if text.startswith(PREFIX):
            identity=text[len(PREFIX):]
            if identity not in sources:raise ValueError('来源引用缺失')
            seen.add(identity);return sources[identity]
        return text
    result=_walk({k:v for k,v in value.items() if k!=TABLE},restore)
    if seen!=set(sources) or _digest(result)!=meta['original_digest']:
        raise ValueError('来源表与完整观察不一致')
    return result


def instruction(value):
    if TABLE not in value:return ''
    if value[TABLE]['version']==DETAIL_VERSION:
        return ('\n只读来源编码：~source:标识优先指向_provenance.sources内嵌正文；'
            '其余指向_provenance.deferred中的query，使用现有get_afsim_observation原样读取detail=true单位详情，'
            'response.world_version须等于_provenance.world_version；该单位详情中的来源正文由digest绑定。'
            '所有单位、身份、到场、数值、位置、装备和库存仍完整提供，只有重复来源长文改为按需取回；'
            'parameter_sources.kind等估计标记仍保留，引用不等于史实已证实。解释具体历史依据前须读取相应详情，不能从旧会话补写来源。'
            '来源字段的~~前缀为字面转义，移除前两个~还原。引用和_provenance不属于可写战局，宿主保留原来源；'
            '不要将引用、来源表或查询写入候选。会话上下文压缩仍由DSH处理。')
    return ('\n只读来源编码：当前态势中~source:标识指向同一观察_provenance.sources的完整正文，'
        '仅压缩重复来源说明，所有单位、数值、位置与库存仍完整提供；来源字段的~~前缀为字面转义，移除前两个~还原。'
        '来源表与引用不属于可写战局，unit_updates可省略只读来源，宿主保留原来源；'
        '不要将引用标签、_provenance或来源表写入候选。会话上下文压缩仍由DSH处理。')


def has_reference(text):
    return isinstance(text,str) and re.search(r'~source:s[0-9a-f]{16}(?![0-9a-f])',text) is not None
