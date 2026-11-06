"""Matched source-payload measurement, real Native reads and isolated UI QA.

Only public SDK tools, typed product exports and ordinary application branches.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request

ROOT=Path('.cache/qa/native-source-details-2026-11-03')
SOURCE=Path('.cache/qa/operation-clock-2026-11-03/turn-browser')


def save(path,value):
    if path.exists():raise ValueError('Preserve original evidence: '+str(path))
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def measure():
    from backend import afsim_state,dsh_simulation
    from gentactix import commands,observation_codec as codec
    before=json.loads((SOURCE/'authoritative-before.json').read_text())
    after=json.loads((SOURCE/'authoritative-after.json').read_text())
    stable=copy.deepcopy((before,after));view=dsh_simulation.observation_view(before['war_state'])
    legacy=codec.encode(view)
    detail=codec.encode(view,source_queries=afsim_state.source_queries(before),world_version=commands.world_version(before))
    assert detail[codec.TABLE]['version']==codec.DETAIL_VERSION
    calls=[]
    def resolve(query):
        from backend.main import _native_tool_dispatch
        response=_native_tool_dispatch(afsim_state.operation_context(before),dict(tool='get_afsim_observation',args=query))
        calls.append(query);assert response['ok'];return response
    decoded=codec.decode(detail,resolve=resolve)
    assert json.dumps(decoded,sort_keys=True)==json.dumps(view,sort_keys=True)
    oldbody=json.dumps(legacy,ensure_ascii=False)
    body=json.dumps(detail,ensure_ascii=False,separators=(',',':'))
    original_prompt=after['trajectory'][-1]['prompt']
    assert original_prompt.count(oldbody)==1
    assert codec.instruction(legacy) in original_prompt
    projected=original_prompt.replace(oldbody,body,1).replace(codec.instruction(legacy),codec.instruction(detail),1)
    assert (before,after)==stable
    save(ROOT/'matched-measurement.json',dict(passed=True,actual_model=False,physical_turn=False,
        actors=22,legacy_observation_chars=len(oldbody),native_observation_chars=len(body),
        observation_reduction_pct=round(100*(1-len(body)/len(oldbody)),2),
        stored_actual_base_prompt_chars=len(original_prompt),matched_projected_base_chars=len(projected),
        matched_base_reduction_pct=round(100*(1-len(projected)/len(original_prompt)),2),
        source_entries=len(detail[codec.TABLE]['deferred']),source_detail_queries=len(calls),
        exact_types_values_and_sources_roundtrip=True,world_unchanged=True,
        actual_sdk_request_chars=None,
        scope='Matched replacement of the actual T5 stored base message only; not a new SDK request or latency measurement'))
    save(ROOT/'encoded-observation.json',detail)
    print('PASS matched source reduction',len(original_prompt),'to',len(projected),'base chars',flush=True)


def native():
    folder=ROOT/'native'
    if folder.exists():raise ValueError('Preserve previous Native result')
    folder.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str((folder/suffix).resolve())
    from backend import harness_engine as h,runtime_bridge,afsim_state
    from backend.main import _native_tool_dispatch
    from gentactix import commands,observation_codec as codec
    current=json.loads((SOURCE/'authoritative-before.json').read_text());original=copy.deepcopy(current)
    encoded=json.loads((ROOT/'encoded-observation.json').read_text())
    entries=encoded[codec.TABLE]['deferred'];pairs=commands.resolve_units(current)
    selected=[]
    for team in ('red','blue'):
        selected.append(next((key,row) for key,row in entries.items() if pairs[row['query']['ids'][0]][0]['team']==team))
    calls=[];observer=h.RunObserver('Native source detail references, readonly')
    def dispatch(context,payload):
        before=copy.deepcopy(context);reply=_native_tool_dispatch(context,payload)
        assert context==before
        calls.append(dict(tool=payload['tool'],args=copy.deepcopy(payload.get('args')),response=reply))
        (folder/'tool-calls.json').write_text(json.dumps(calls,ensure_ascii=False,indent=2)+'\n')
        print('PUBLIC_TOOL',payload['tool'],reply.get('ok'),flush=True)
        return reply
    runtime_bridge.register_dispatcher(dispatch)
    request=dict(world_version=encoded[codec.TABLE]['world_version'],sources=dict(selected))
    prompt=('这是只读来源核对，不推演、不下令、不提交候选。请对下列两个来源引用各实际调用一次get_afsim_observation，原样使用query。'
        '核对响应world_version与给定指纹相同，并读取units[0].parameter_sources.personnel.kind。'
        '仅输出JSON {"world_version":"响应指纹","units":[{"id":"响应单位id","name":"响应全名","personnel_basis":"personnel.kind原值"}]}。'
        '不自行计算哈希，不把估计说成历史实有数，不输出隐藏推理。\n'+json.dumps(request,ensure_ascii=False))
    (folder/'prompt.txt').write_text(prompt)
    started=time.monotonic();result=dict(passed=False,actual_model=True,physical_turn=False)
    try:
        reply=h._run_brain(prompt,None,role='chat',observer=observer,native_context=afsim_state.operation_context(current))
        answer=h.parse_json_object(reply.final_response)
        expected=[]
        for _,entry in selected:
            query=entry['query'];actual=[c['response'] for c in calls if c['tool']=='get_afsim_observation' and c['args']==query and c['response'].get('ok')]
            assert actual,'Model did not perform requested Native source lookup'
            row=actual[-1]['units'][0]
            assert actual[-1]['world_version']==request['world_version']
            text=[t for t in codec.source_texts(row) if hashlib.sha256(t.encode()).hexdigest()==entry['digest']]
            assert len(text)==1
            expected.append(dict(id=row['id'],name=row['name'],personnel_basis=row['parameter_sources']['personnel']['kind']))
        assert reply.finish_reason=='completed'
        assert answer==dict(world_version=request['world_version'],units=expected),(answer,expected)
        assert current==original
        result.update(passed=True,answer=answer,world_unchanged=True,source_digest_and_world_binding=True)
    except Exception as exc:
        result['error']=str(exc);raise
    finally:
        result.update(seconds=round(time.monotonic()-started,3),calls=len(calls),meta=observer.meta(),
            scope='Actual two-team source retrieval through existing Native observation; no physical turn or complete historical interpretation acceptance')
        save(folder/'result.json',result);save(folder/'public-runs.json',observer.runs);h.close_harness()


def seed():
    base='http://127.0.0.1:19247/api/sessions/'
    def call(path,body=None):
        request=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
        return json.load(urllib.request.urlopen(request,timeout=60))
    sid='b04f6b2e97a3';before=call(sid+'/export')['session'];assert not call(sid+'/progress')['active']
    view=call(sid+'/commands')
    branch=call(sid+'/commands/open-branch',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version']))
    new=call(branch['session_id']+'/export')['session'];assert new['turn_count']==5
    assert call(sid+'/export')['session']==before
    folder=ROOT/'live-api/sessions';folder.mkdir(parents=True,exist_ok=True)
    save(folder/(new['id']+'.json'),dict(format='gentactix-session-v1',session=new))
    save(ROOT/'turn-before-authoritative.json',new)
    save(ROOT/'turn-case.json',dict(session_id=new['id'],turn=6,api='http://127.0.0.1:19257',ui='http://127.0.0.1:19248'))
    print('Seeded normal new branch',new['id'],'T5; source unchanged',flush=True)


def serve():
    folder=(ROOT/'live-api').resolve()
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(folder/suffix)
    from backend import main,harness_engine as h,runtime_bridge
    import uvicorn
    def dispatch(context,payload):
        frozen=copy.deepcopy(context['session']['war_state']);reply=main._native_tool_dispatch(context,payload)
        assert context['session']['war_state']==frozen
        with (ROOT/'live-public-tools.jsonl').open('a') as stream:
            stream.write(json.dumps(dict(tool=payload['tool'],args=payload.get('args'),response=reply),ensure_ascii=False)+'\n')
        return reply
    runtime_bridge.register_dispatcher(dispatch)
    try:uvicorn.run(main.app,host='127.0.0.1',port=19257,log_level='warning')
    finally:h.close_harness()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=['measure','native','seed','serve'])
    parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if args.mode!='measure' and not args.live:parser.error('--live required')
    globals()[args.mode]()
