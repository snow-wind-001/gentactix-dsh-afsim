"""Explicit motion contract over unchanged WJL historical source and input priors."""
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from gentactix import campaign_windows as cw, historical_initial as hi, movement_feedback as mf


def build():
    value=copy.deepcopy(cw.load('WJL-oct6-10','1.4.0'))
    value.update(version='1.5.0',label='万家岭：10月6—10日地面会战 · 运动反馈约束')
    value['parameter_estimates']['global_priors']['movement_feedback']=dict(version=mf.VERSION,
        assumption='显式采用既有AFSIM聚合规则的通信、疲劳、压制、兵力和燃油机动约束；'
        '疲劳按实际陆地路程偶数舍入，乘艇水程不计陆地疲劳与燃油。'
        '这是两后端一致性的计算规则版本，不是1938年部队行军、生理或装备效能的历史标定。')
    value['limitations']+=' 本版仅新增movement-feedback-1运动反馈约束；沿用1.4.0史料、人数装备部署和库存先验，'
    value['limitations']+='不提高其历史可信度，不修改旧窗口或默认选择。'
    pin=value['historical_initial']
    snapshot=hi.initial(value['battle'],value['start_phase_id'],version=pin['version'])['historical_initial']
    cw.validate_definition(value,snapshot)
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    value=build();path=cw.DATA_ROOT/value['id']/(value['version']+'.json')
    if path.exists():
        if json.loads(path.read_text())!=value:raise SystemExit('Existing motion version differs; create another version')
        print('WJL1.5 motion contract matches; same1.4 historical source and numerical priors')
    elif args.check:raise SystemExit('WJL1.5 motion window missing')
    else:
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
        print('Created explicit WJL1.5 motion window; defaults and old versions unchanged')


if __name__=='__main__':main()
