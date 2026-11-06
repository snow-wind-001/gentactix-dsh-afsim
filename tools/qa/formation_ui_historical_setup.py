"""Import isolated historical-parent QA windows, never edit published sources."""
import copy
import argparse
import json
import uuid

from gentactix.state import DEFAULT_SESSION_STATE
from tools.qa import formation_ui_live as ui
from tools.qa.formation_ownership_fixture import historical_parent_world
from tools.upgrade_wanjialing import BATTLE


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',default='historical-cases.json');args=parser.parse_args()
    cases={}
    for engine in ('narrative','afsim'):
        world=historical_parent_world()
        session=copy.deepcopy(DEFAULT_SESSION_STATE)
        session.update(id=uuid.uuid4().hex[:12],scenario_input='历史番号分兵界面软件验收；私人粗粒度窗口，人数及部署均为QA估计，非历史复原',
            time_step=world['mission']['definition']['time_step'],battle_choice=BATTLE,use_adjudicator=False,use_rag=True,use_live_intel=False,
            product_mode='historical',simulation_mode='open',execution_backend=engine,war_state=world,role_epoch=0,
            historical_definition=copy.deepcopy(world['mission']['definition']),mission_id=world['mission']['definition']['id'])
        result=ui.api.call('POST','/sessions/import',dict(format='gentactix-session-v1',session=session))
        sid=result['session_id'];cases[engine]=dict(session_id=sid,parent_id='ww2.cn.army74',parent_name='第74军')
    ui.save(args.out,cases)
    print('Prepared historical parent UI QA copies; sources/force values not migrated')


if __name__=='__main__':main()
