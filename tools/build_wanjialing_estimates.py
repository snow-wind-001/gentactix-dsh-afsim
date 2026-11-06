"""Create optional window1.1 with declared exploratory priors, not source facts."""
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from gentactix import historical_initial as hi,campaign_windows as cw,campaign_estimates as ce
from tools.build_wanjialing_window import build as window_source
from tools.upgrade_wanjialing import BATTLE

NOTE=('可编辑的探索性计算先验，非史料实有数、非历史标定。人数区间用于限制局部投入规模，'
      '不按全役总数平均分配；装备0表示本模型不投入，不证明历史没有。位置为相对现代磨溪地名的方向估计，'
      '不是1938年阵位。到场和库存须另填估计；粮弹按编组工作量，不是按人数或重量标定。')
CENTER={'lat':29.365246,'lng':115.581335}


def build():
    d=window_source();d['version']='1.1.0';d['label']='万家岭：10月6—10日地面会战 · 计算先验'
    s=hi.initial(BATTLE,'oct6_orders',version='1.3.0')['historical_initial']
    ids=[i for i,r in d['units'].items() if r['representation']=='actor']
    def rng(lo,high):return dict(minimum=lo,maximum=high)
    actors={}
    # Bounds are modelling assumptions for the admitted portions. The secondary
    # source does not provide unit strength returns, establishment or gun lists.
    bands={
        'division90':(1200,6000),'division159':(1000,6000),'division160':(1000,6000),
        'division161.wjl_part':(600,3600),'division51':(1200,6000),'division58':(1200,6000),
        'division60':(600,4000),'division139':(800,4800),'division141':(800,4800),
        'division187':(800,4800),'division_new15':(600,4000),'division_new13':(600,4000),
        'division91':(300,2400),'division_reserve6':(300,2400),'division142.wjl_part':(800,4000),
        'artillery2.battalion3':(120,600),'artillery1.company6':(40,200),
        'division106':(4000,12000),'regiment149':(400,2600),
        'uga_detachment':(1800,4000),'suzuki_detachment':(600,3000),'saeda_detachment':(400,2200)}
    for identity in ids:
        short=identity.split('.',2)[2];artillery=short.startswith('artillery')
        lat,lng=CENTER['lat'],CENTER['lng'];radius=8
        if short in ('division159','division160','division161.wjl_part'):lat+=.055
        elif short in ('division51','division58'):lat-=.05
        elif short in ('division90','division139','division141','division187'):lng+=.055
        elif short in ('division142.wjl_part',):lng-=.09
        elif short in ('division60','division_new13','division_new15','division91','division_reserve6'):lat-=.10;lng-=.10;radius=12
        elif short in ('uga_detachment','suzuki_detachment','saeda_detachment'):lat-=.12;lng-=.22;radius=12
        elif artillery:lat-=.07
        guns=(3,12) if short=='artillery2.battalion3' else (1,4) if artillery else (0,24)
        actors[identity]=dict(personnel=rng(*bands[short]),
            equipment=dict(armor=rng(0,0),artillery=rng(*guns),air_defense=rng(0,4),engineer=rng(0,16),transport=rng(0,100)),
            position=dict(center={'lat':lat,'lng':lng},radius_km=radius,assumption=NOTE+'仅约束开局估计工作区，不限制随后合法机动。'),
            role='support' if artillery else 'infantry',direct_range_m=rng(100,600 if artillery else 1500),
            assumption=NOTE+' '+d['units'][identity]['extent'])
    red=[i for i in ids if i.startswith('ww2.cn.')]
    outer=['ww2.cn.'+i for i in ('division60','division_new13','division_new15','division91','division_reserve6')]
    assault=[i for i in red if i not in outer and 'artillery' not in i]
    def node(identity,label,team,members,condition,after=(),operations=()):
        return dict(id=identity,label=label,team=team,unit_ids=members,after=dict(mode='all',node_ids=list(after)),
            not_before_seconds=0,condition=condition,hold_seconds=None,latch=False,operation_ids=list(operations),assumption=NOTE)
    def region(kind):return dict(kind=kind,region={'center':{'lat':None,'lng':None},'radius_km':None},minimum_personnel=None)
    graph=dict(version='campaign-objectives-1',nodes=[
        node('red_inner','控制内圈估计作战地域','red',assault,region('control'),operations=['WJL-Oct6-orders','WJL-Oct10-residual']),
        node('red_block','维持外线估计阻援地域','red',outer,region('control'),operations=['WJL-Oct6-relief-blocking']),
        node('red_preserve','在两方向达成时保存投入兵力','red',red,dict(kind='preserve',minimum_fraction=None),after=['red_inner','red_block']),
        node('blue_core','保存被围投入部','blue',['ww2.jp.division106'],dict(kind='preserve',minimum_fraction=None)),
        node('blue_exit','被围投入部到达估计突围地域','blue',['ww2.jp.division106'],region('reach'),after=['blue_core'],operations=['WJL-Oct6-orders']),
        node('blue_relief','援军推进至内圈估计地域','blue',['ww2.jp.uga_detachment','ww2.jp.suzuki_detachment','ww2.jp.saeda_detachment'],region('reach'),after=['blue_core'],operations=['WJL-Oct6-relief-blocking'])],
        outcomes={'red':{'mode':'all','node_ids':['red_preserve']},'blue':{'mode':'any','node_ids':['blue_exit','blue_relief']}},
        elimination_ends=True,assumption=NOTE+'双边目标为模型胜负代理，不是原始作战命令；到达参照区不证明已完成真实解围或通信接通。')
    d['parameter_estimates']=dict(version=ce.VERSION,historically_calibrated=False,assumption=NOTE,
        area=dict(center=copy.deepcopy(CENTER),radius_km=60,assumption=NOTE+'60公里是包含外线的宽工作范围假设，未核道路通行与各地精确坐标。',
            evidence=[{'source_id':'GEO','locator':'现代磨溪乡地名参考；外线范围为独立模型假设，不来自OSM单位阵位'}]),actors=actors,goal_template=graph)
    d['limitations']+=' 本版补可计算先验和双边目标模板，未新增单位实有事实；数值、位置与阈值未经历史标定，航空及真正场外过程未因此补齐。'
    cw.validate_definition(d,s)
    return d


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--check',action='store_true');args=p.parse_args()
    d=build();path=cw.DATA_ROOT/'WJL-oct6-10/1.1.0.json'
    if path.exists():
        if json.loads(path.read_text())!=d:raise SystemExit('Existing window differs; create a new version')
        print('Wanjialing1.1 estimates match; source facts and1.0 window unchanged')
    elif args.check:raise SystemExit('Wanjialing1.1 estimates missing')
    else:path.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n');print('Created opt-in1.1 estimates; not historical strengths or positions')


if __name__=='__main__':main()
