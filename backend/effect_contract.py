"""Read-only domain shape checks shared with Native tool metadata.

Only the contract's structural keywords are checked here. Existing simulation
validators still own quantities, versions, resources, physics and provenance.
"""
import json
import math
from pathlib import Path

SCHEMA=json.loads((Path(__file__).resolve().parent.parent/'plugins/dsh-gentactix/effect-schema.json').read_text())


class ShapeError(ValueError):
    def __init__(self,issues):
        self.issues=issues
        summary='；'.join(i['path']+'：'+i['message'] for i in issues[:4])
        if len(issues)>4:summary+=f'；另有{len(issues)-4}项，见issues'
        super().__init__('候选结构错误；不得改写单位身份、兵种、来源或性能；'+summary)


def _token(value):
    return str(value).replace('~','~0').replace('/','~1')


def validate(value,*,schema=SCHEMA):
    """Reject typed shape errors; never coerce, drop or fill a field."""
    issues=[]
    def walk(item,schema,path):
        types=schema.get('type');types=[types] if isinstance(types,str) else types
        def matches(kind):
            if kind=='number':return type(item) is int or type(item) is float and math.isfinite(item)
            return (isinstance(item,dict) if kind=='object' else isinstance(item,list) if kind=='array'
                else isinstance(item,str) if kind=='string' else type(item) is bool if kind=='boolean'
                else item is None if kind=='null' else type(item) is int if kind=='integer'
                else False)
        if types and not any(matches(t) for t in types):
            names={'object':'对象','array':'数组','integer':'整数','number':'数值','string':'字符串','boolean':'布尔值','null':'空值'}
            issues.append(dict(path=path or '/',code='type',expected=types,message='须为'+'/'.join(names.get(t,t) for t in types)+'，不是'+type(item).__name__));return
        if isinstance(item,str) and len(item)<schema.get('minLength',0):
            issues.append(dict(path=path,code='empty',message='须为非空精确名称'))
        if isinstance(item,dict):
            props=schema.get('properties',{})
            for key in schema.get('required',[]):
                if key not in item:issues.append(dict(path=path+'/'+_token(key),code='missing',message='缺少必需字段'+key))
            for key,child in item.items():
                at=path+'/'+_token(key)
                if key in props:walk(child,props[key],at)
                elif schema.get('additionalProperties') is False:
                    label='顶层字段' if not path else '字段'
                    issues.append(dict(path=at,code='unknown',allowed=sorted(props),message='只读或未知'+label+str(key)+'；允许字段：'+','.join(sorted(props))))
        if isinstance(item,list) and 'items' in schema:
            for index,child in enumerate(item):walk(child,schema['items'],path+'/'+str(index))
    walk(value,schema,'')
    if issues:raise ShapeError(issues)


def validate_arguments(value):
    """Check only the outer Native arguments; retain malformed object references.

    Inner candidate checking follows reference creation so an explicit edit can
    repair an object's bad fields. A JSON string is never implicitly parsed.
    """
    validate(value,schema=dict(type='object',required=['candidate'],additionalProperties=False,
        properties=dict(candidate=dict(type='object'))))
