"""Real Native source reading and isolated normal API; no user games or config edits."""
import argparse
import copy
import json
import os
from pathlib import Path
import time

ROOT = Path('.cache/qa/campaign-continuity-2026-11-01')
PORT = 19119


def isolate(folder):
    folder.mkdir(parents=True,exist_ok=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                       ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(folder.resolve()/suffix)


def serve():
    isolate(ROOT/'http')
    from backend import main,harness_engine
    import uvicorn
    try:uvicorn.run(main.app,host='127.0.0.1',port=PORT,log_level='warning')
    finally:harness_engine.close_harness()


def model():
    folder=ROOT/'model'/str(time.time_ns());isolate(folder)
    from gentactix import history_replay
    from tools.upgrade_wanjialing import BATTLE
    from backend import harness_engine as h,runtime_bridge,afsim_state
    from backend.main import _native_tool_dispatch
    pinned=history_replay.pin(BATTLE,version='1.3.0')
    cursor=next(i for i,e in enumerate(pinned['pack']['events']) if e.get('event_key')=='WJL-Sep28-149-attachment')
    session=dict(id='wjl-campaign-sources-qa',war_state=history_replay.frame_pinned(pinned,cursor),
        turn_count=cursor,battle_choice=BATTLE,execution_backend='narrative',product_mode='analysis',
        simulation_mode='replay',use_rag=False,history=[])
    saved=copy.deepcopy(session);calls=[];result=dict(passed=False,cases=[],actual_model=True)
    observer=h.RunObserver('会战身份配属与后续过程来源核验')
    def dispatch(context,payload):
        reply=_native_tool_dispatch(context,payload)
        calls.append(dict(tool=payload.get('tool'),args=payload.get('args'),response=reply))
        return reply
    runtime_bridge.register_dispatcher(dispatch)
    def ask(phase,question,expected):
        start=len(calls);began=time.monotonic()
        prompt=('实际调用retrieve_history(kind="operations",phase_id="'+phase+'",limit=2)，沿next_args读完。'
            '完全省略query，不用关键词或*；需要关系时可再读kind="relations"。只依据固定版本来源，不调用变更工具。'+question)
        reply=h._run_brain(prompt,None,role='chat',observer=observer,native_context=afsim_state.operation_context(session))
        answer=h.parse_json_object(reply.final_response)
        result['cases'].append(dict(phase=phase,answer=answer,seconds=round(time.monotonic()-began,3),tool_calls=len(calls)-start))
        (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        assert answer==expected,answer
        assert any(c['tool']=='retrieve_history' and c['response'].get('phase_id')==phase for c in calls[start:])
        assert session==saved
        print('PASS source query',phase,'seconds',result['cases'][-1]['seconds'],flush=True)
    try:
        ask('sep28_isolation','149联队行政上级与临时作战指挥分别是谁？是否已核两师团全部下级和原始档案？'
            '只返回JSON {"administrative_parent":"101或106","operational_parent":"101或106",'
            '"complete_divisional_rosters":布尔值,"original_archive_examined":布尔值}。',
            dict(administrative_parent='101',operational_parent='106',complete_divisional_rosters=False,original_archive_examined=False))
        ask('oct2_encirclement','两方向记录属于命令还是证明同时到场？是否提供逐师实到兵额或精确坐标？'
            '只返回JSON {"east_and_west_orders":布尔值,"simultaneous_arrival_proven":布尔值,'
            '"unit_strength_known":布尔值,"precise_positions_known":布尔值}。',
            dict(east_and_west_orders=True,simultaneous_arrival_proven=False,unit_strength_known=False,precise_positions_known=False))
        ask('oct17_withdrawal','16日论文后退记为60师还是61师？17日是什么日期精度？是否可在开放推演强制终止或补满残部？'
            '只返回JSON {"division_in_retreat_record":"60或61","withdrawal_precision":"day或hour",'
            '"force_open_campaign_end":布尔值,"restore_full_strength":布尔值}。',
            dict(division_in_retreat_record='61',withdrawal_precision='day',force_open_campaign_end=False,restore_full_strength=False))
        result.update(passed=True,world_unchanged=True,meta=observer.meta())
    finally:
        result.update(world_unchanged=session==saved,calls=calls)
        (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        (folder/'runs.json').write_text(json.dumps(observer.runs,ensure_ascii=False,indent=2))
        h.close_harness();print('Evidence:',folder,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['serve','model']);p.add_argument('--live',action='store_true');a=p.parse_args()
    if a.mode=='model' and not a.live:p.error('Use --live for configured real model calls')
    serve() if a.mode=='serve' else model()
