"""Actual DSH read-only tool use for committed model fire estimates."""
import argparse
import json
from pathlib import Path

from tools.qa.catalog_expansion_live import call


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true')
    if not parser.parse_args().live:parser.error('Use --live against owned isolated API18998')
    root=Path('.cache/qa/fire-process');home=Path('.cache/qa/ww2-phases/runtime/dsh-home/sessions')
    offsets={str(path):path.stat().st_size for path in home.glob('*/*/session.v4.jsonl')}
    sid='b9e368f0887c';base='/api/sessions/'+sid
    health=call('GET','/api/health');assert not health['build']['restart_required']
    assert Path(f"/proc/{health['build']['pid']}/cmdline").read_bytes().split(b'\0')[1]==b'.cache/qa/ww2-phases/launch.py'
    config=call('GET','/api/llm/config')
    (root/'review-config-shape.json').write_text(json.dumps({'keys':list(config)},ensure_ascii=False)+'\n')
    before=call('GET',base)['war_state'];commands=call('GET',base+'/commands')
    answer=call('POST',base+'/chat',{'message':'只读核对当前已提交战局。请实际调用get_afsim_observation，'
        '按单位列出本轮射击周期、首发/末发时点、有效火力时长、联络等待、轮末装填、弹药消耗与人员累计减员。'
        '说明这些数据是否属于AFSIM遥测，不能把发生时点称为耗时，也不能把本轮射击周期当作从开局累计值。'
        '不要下令、改主局、试算或用旧对话代替本轮观察；使用简短表格。'})
    assert answer['engine_meta']['finish_reason']=='completed'
    assert answer['war_state']==before and call('GET',base)['war_state']==before
    assert call('GET',base+'/commands')==commands
    public=next(row['content'] for row in reversed(answer['chat_messages']) if row['role']=='assistant')
    (root/'review-answer.txt').write_text(public+'\n')
    calls=[]
    for path in home.glob('*/*/session.v4.jsonl'):
        offset=offsets.get(str(path),0)
        if path.stat().st_size==offset:continue
        with path.open('rb') as stream:
            stream.seek(offset)
            for line in stream:
                if not line.endswith(b'\n'):continue
                row=json.loads(line)
                if row.get('type')=='tool/call':
                    data=row.get('data') or {};calls.append({'session_id':path.parent.name,'seq':row.get('seq'),
                        'name':data.get('name'),'arguments':data.get('arguments',data.get('args'))})
    (root/'review-tools.json').write_text(json.dumps(calls,ensure_ascii=False,indent=2)+'\n')
    assert any(row['name']=='get_afsim_observation' for row in calls),calls
    result={'passed':True,'world_and_commands_unchanged':True,'actual_native_tool_call':True,
        'scope':'DSH estimates through existing read-only tools; public text needs independent inspection',
        'session_id':sid,'pid':health['build']['pid'],'engine_meta':answer['engine_meta'],'tools':calls}
    (root/'review-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='tools'},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
