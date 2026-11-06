"""Military plotting skill and overlay API over the existing native DSH runtime."""
import copy
import json
from pathlib import Path
import uuid
from fastapi import APIRouter,HTTPException,Response
from pydantic import BaseModel,ConfigDict,Field
from gentactix import military_symbols as m
from . import harness_engine as h,extensions,session_store
SKILL=Path(__file__).resolve().parents[1]/'plugins/dsh-military-plotting/skills/military-plotting/SKILL.md'
TOOLS={'read_military_plotting_skill','search_military_symbols','validate_military_plotting'}


def execute_tool(context,payload):
    scoped=context['military_plotting'];tool=payload.get('tool');args=payload.get('args') or {}
    if tool=='read_military_plotting_skill':return {'ok':True,'skill':'military-plotting','content':SKILL.read_text()}
    if tool=='search_military_symbols':return {'ok':True,**m.catalog(args.get('query',''),args.get('limit',12))}
    if tool=='validate_military_plotting':
        try:
            result=m.bind_candidate(args.get('candidate'),scoped['session'],scoped['points'])
            return {'ok':True,'valid':True,'items':len(result['items']),'scope':'overlay_only; no_world_write'}
        except (ValueError,TypeError,KeyError) as exc:return {'ok':True,'valid':False,'error':str(exc),'fields':['symbol_id','label','team','status','points','source','visible','unit_id']}
    raise ValueError('本次标图操作不支持该工具')


class Context(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    revision:int=Field(ge=0)
    turn:int=Field(ge=0)
    world_version:str=Field(min_length=1,max_length=128)


class Save(Context):
    items:list[dict]=Field(default_factory=list,max_length=m.MAX_ITEMS)
    unit_symbols:dict[str,str]=Field(default_factory=dict,max_length=1000)


class Propose(Context):
    text:str=Field(min_length=1,max_length=3000)
    points:list[dict]=Field(default_factory=list,max_length=32)


def build_router(get_session,serialized):
    router=APIRouter()

    @router.get('/api/plotting/catalog')
    def catalog():return m.catalog()

    @router.get('/api/plotting/reference')
    def reference(query:str='',offset:int=0,limit:int=24):
        if not 0<=offset or not 1<=limit<=40:raise HTTPException(422,'分页范围非法')
        rows=[r for r in m.REFERENCE if not query or query.casefold() in (r['id']+' '+r['name_zh']).casefold()]
        return {'total':len(rows),'items':rows[offset:offset+limit],'scope':'原书独立示例参考；不证明年代适用、语义认证或地理定位点。'}

    @router.get('/api/plotting/reference/{identity}.svg')
    def reference_svg(identity:str):
        try:
            return Response(m.reference_svg(identity),media_type='image/svg+xml',headers={
                'Content-Security-Policy':"default-src 'none'; sandbox",'X-Content-Type-Options':'nosniff','Cache-Control':'private, max-age=3600'})
        except FileNotFoundError as exc:raise HTTPException(404,str(exc)) from exc
        except (ValueError,OSError) as exc:raise HTTPException(422,str(exc)) from exc

    def session(sid):
        value=get_session(sid)
        if not value.get('war_state'):raise HTTPException(409,'请先初始化战局，再进行标图')
        return value

    @router.get('/api/sessions/{sid}/plotting')
    def get(sid:str):return m.view(session(sid))

    @router.put('/api/sessions/{sid}/plotting')
    @serialized
    def save(sid:str,req:Save):
        value=session(sid)
        try:state=m.replace(value,req.model_dump())
        except m.Conflict as exc:raise HTTPException(409,str(exc)) from exc
        except (ValueError,TypeError,KeyError) as exc:raise HTTPException(422,str(exc)) from exc
        candidate=session_store.serializable(value);candidate['plotting_state']=state
        try:
            session_store.validate(candidate);session_store.save(candidate)
        except (OSError,ValueError) as exc:raise HTTPException(503,'标图检查点未保存，原标注保留') from exc
        value['plotting_state']=state
        return m.view(value)

    @router.post('/api/sessions/{sid}/plotting/propose')
    @serialized
    def propose(sid:str,req:Propose):
        value=session(sid)
        try:
            m.check_context(value,req.model_dump());points=[m.point(p) for p in req.points]
        except m.Conflict as exc:raise HTTPException(409,str(exc)) from exc
        except (ValueError,TypeError) as exc:raise HTTPException(422,str(exc)) from exc
        observer=h.RunObserver('DSH军事标图草稿');value.update(progress=observer.progress,active_observer=observer)
        try:
            context={'military_plotting':{'session':value,'points':points}}
            prompt=('读取read_military_plotting_skill，使用search_military_symbols检索图例，调用validate_military_plotting校验后返回标注草稿。'
                    '只允许使用下列已知位置及用户选点；不输出作战命令或完整战局。若点不够，返回明确说明，不编坐标。\n'
                    +json.dumps({'request':req.text,'selected_points':points,'known_locations':m.known_locations(value),'units':m.view(value)['units']},ensure_ascii=False))
            result=h._run_brain(prompt,None,role='map-annotator',observer=observer,native_context=context)
            answer=h.parse_json_object(result.final_response)
            calls={e.get('name') for run in observer.runs for e in run.get('events',[]) if e.get('type')=='tool/call'}
            if not TOOLS<=calls:raise ValueError('缺少实际skill、目录检索与校验工具事件，草稿未采纳')
            draft=m.bind_candidate(answer,value,points)
            if value.get('cancel_requested') or observer.cancel_requested:raise RuntimeError('已取消军事标图，未保存标注')
            record={**draft,'id':uuid.uuid4().hex,'revision':req.revision,'turn':req.turn,'world_version':req.world_version,
                    'construction':{'source':'dsh_native_skill','skill':'military-plotting','runs':extensions.safe(observer.runs),'meta':observer.meta()}}
            value.setdefault('plotting_proposals',[]).append(copy.deepcopy(record));value['plotting_proposals']=value['plotting_proposals'][-10:]
            return record
        except Exception as exc:
            cancelled=value.get('cancel_requested') or observer.cancel_requested
            raise HTTPException(409 if cancelled else 502,'标图草稿未保存：'+str(exc)) from exc
        finally:value.update(progress=None,active_observer=None,cancel_requested=False)

    return router
