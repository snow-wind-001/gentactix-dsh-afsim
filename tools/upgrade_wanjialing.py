"""Build an additive sourced Wanjialing snapshot; never advance the default."""
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from gentactix import historical_initial as hi

BATTLE='抗日战争-万家岭战役-1938.09下旬至1938.10'
PAPER='https://www.krzzjn.com/uploadfile/2018/0604/20180604092232868.pdf'


def evidence(locator,source='WJL_GUO'):
    return [{'source_id':source,'locator':locator}]


def build():
    d=hi.definition(BATTLE,'1.0.0');d['version']='1.1.0'
    d['sources']['WJL_GUO']={'title':'郭代习：万家岭战役述评，《抗日战争研究》1996年第2期，111—126页',
        'url':PAPER,'publisher':'《抗日战争研究》；抗日战争纪念网提供PDF',
        'evidence_kind':'published_secondary','original_archive_examined':False,
        'limitations':'2026-10-31视觉核读PDF第8、9页（印刷118、119页）。论文转引档案7878033、7878201及回忆；未辨读馆藏原件。其兵额与歼敌判断未作为精确事实采用。'}
    d['coverage']['notes']=[
        '1.1.0补充有页码的时段任务与已核下级；旧1.0.0及默认入口不变，不宣称完整会战序列。',
        '10月7日只配置已核第90、第159、第51、第58师、第161师本地投入部和106师团被围部；编制内缺载直属和余部须显式排除，不能宣称投入整军。',
        '161师一部在66军方向执行任务，不据此把全161师永久改隶66军；实际配属记在本阶段relations，历史树仍保持未知。',
        '10月6日与8日的任务片段用于有来源回溯；不足以建立这些日期完整可计算部署，相关phase故意不通过到场准入。',
        '军、师、投入部、炮兵营/连的累计身份不能同时重复计算；地名、命令、接敌与实际部署分开。',
        '现代磨溪乡点仅限定计算工作区域，张古山、石堡山、扁担山等精确坐标仍未知；不把县城纪念园放成阵位。',
        '实到兵额、分类装备、粮弹与逐日战损均未核，仍保持null；开放推演参数须独立估计，不能从武汉总数倒分。']
    ref,attack=copy.deepcopy(d['phases']);ref['scope']='累计身份参考；已列下级仍不完整，不能把全部部队视为同日在场。'
    def reference_phase(identity,label,date):
        ev=evidence('第118—119页：10月5—8日调整及作战经过；属于论文转引，不是原始作战日志')
        return dict(id=identity,label=label,date={'label':date,'precision':'day','evidence':ev},
            scope='资料回溯片段；尚未核齐当日完整投入、部署与到场，不开放为完整计算初态。',evidence=ev)
    orders=reference_phase('oct6_orders','10月6日调兵与反攻命令（资料片段）','1938-10-06')
    counter=reference_phase('oct8_counterattacks','10月8日反攻与阵地争夺（资料片段）','1938-10-08')
    attack['label']='10月7日分方向总攻：已核师级投入部'
    attack['scope']='第4军90师、第66军159师及作战配属161师投入部、第74军51/58师；未核余部明确不投入。日方仅106师团被围部，未完成逐联队序列。'
    attack['evidence']+=evidence('第118—119页：第4军90师、74军51/58师及66军159师和161师一部')
    attack['process_requirements']=[{'kind':'combined_operation','scope':'分别表达石堡山、长岭—张古山及第4军方向的合围任务；目标和地域参数仍为显式估计，不强制历史战果。','evidence':copy.deepcopy(attack['evidence'])}]
    d['phases']=[ref,orders,attack,counter]
    old={u['id']:u for u in d['units']}
    # Missing attendance outside Oct 7 is deliberately a reference, never an arrival.
    for u in d['units']:
        u['presence'] += [dict(phase_id=p['id'],status='campaign_participant',evidence=copy.deepcopy(u['evidence'])) for p in (orders,counter)]
    facts={k:{'value':None,'evidence':[], 'scope':scope} for k,scope in {
        'personnel':'缺本阶段实到兵额；不从全军、会战或战后减员倒分。',
        'equipment':'缺本阶段分类完好装备、库存与配属火力数。',
        'position':'只核历史地名与任务方向；无配准后的战术阵位坐标。'}.items()}
    def unit(identity,name,echelon,parent=None,role='formation',present=False,locator='第118页参战部队段'):
        ev=evidence(locator)
        row=dict(id=identity,name=name,team='red',role=role,echelon=echelon,parent_id=parent,evidence=ev,
            presence=[dict(phase_id=p['id'],status=('reported_present' if p['id']=='oct7_attack' and present else 'outside_scope' if p['id']=='oct7_attack' else 'campaign_participant'),evidence=copy.deepcopy(ev)) for p in d['phases']],facts=copy.deepcopy(facts))
        d['units'].append(row);return row
    for number in (18,64,72,78):unit(f'ww2.cn.army{number}',f'第{number}军','军')
    unit('ww2.cn.division90','第90师','师','ww2.cn.army4',present=True,locator='第118页：第4军90师从东面攻击')
    unit('ww2.cn.division159','第159师','师','ww2.cn.army66',present=True,locator='第118—119页：调入159师，7日向石堡山攻击')
    unit('ww2.cn.division160','第160师','师','ww2.cn.army66',locator='第118页：10月5日调159、160师；不能据此证明7日全160师到场')
    u=unit('ww2.cn.division161','第161师','师',locator='第119页：161师一部在66军方向投入，不据此确定全师行政上级')
    unit('ww2.cn.division161.wjl_part','第161师万家岭投入部','师之一部','ww2.cn.division161',present=True,locator='第119页：161师之一部；下级番号、规模缺载，不补造一个新团')
    unit('ww2.cn.division51','第51师','师','ww2.cn.army74',present=True,locator='第118页：74军率51师到白槎西北；第119页8日拂晓张古山争夺')
    unit('ww2.cn.division58','第58师','师','ww2.cn.army74',present=True,locator='第118页：58师归还74军建制，仍任长岭、张古山守备')
    for number,parent in ((60,18),(139,32),(141,32),(142,32),(187,64)):
        unit(f'ww2.cn.division{number}',f'第{number}师','师',f'ww2.cn.army{parent}')
    unit('ww2.cn.division_new15','新编第15师','师','ww2.cn.army72')
    unit('ww2.cn.division_new13','新编第13师','师','ww2.cn.army78')
    unit('ww2.cn.division91','第91师','师',locator='第118—119页：南田铺攻击后抽调阻援；全程行政隶属未由此核定')
    unit('ww2.cn.division_reserve6','预备第6师','师',locator='第118—119页：西面攻击与抽调阻援，不确定全程行政上级')
    unit('ww2.cn.artillery2.battalion3','炮兵第2团第3营','营',role='support',locator='第118页参战部队段：炮2团3营；无实有火炮数及逐日阵位')
    unit('ww2.cn.artillery4.company6','炮兵第4团第6连','连',role='support',locator='第118页参战部队段：炮4团6连；无实有火炮数及逐日阵位')
    parents={u['parent_id'] for u in d['units'] if u['parent_id']}
    for u in d['units']:
        if u['id'] in parents and u['role'] in ('formation','support'):
            u['children_coverage']={'status':'partial','scope':'仅列已核下级或本地投入部；全建制、直属与其余投入状态未核，不能称完整覆盖。','evidence':copy.deepcopy(u['evidence'])}
    def operation(phase,identity,kind,date,precision,ids,places,description,locator):
        ev=evidence(locator)
        phase.setdefault('operations',[]).append(dict(id=identity,kind=kind,date={'label':date,'precision':precision},
            unit_ids=ids,places=[{'name':name,'position':None,'evidence':copy.deepcopy(ev)} for name in places],
            description=description,evidence=ev,limitations='论文转引和公开叙述；未核原始命令正文、精确阵位及逐单位兵额。时间是来源记录精度，不是本局强制执行时刻。'))
    operation(orders,'WJL-Oct6-redeployment','concentration','1938-10-06，当日','day',
        ['ww2.cn.army66','ww2.cn.division159','ww2.cn.division160','ww2.cn.army74','ww2.cn.division51','ww2.cn.division58'],
        ['金娥殿','公母岭','白槎西北','长岭','张古山'],'66军接防后调向北侧攻击准备；51师随74军调动，58师回归74军并守备原方向。','第118页：10月5日调兵电、6日66军转用与74军调动段')
    operation(orders,'WJL-Oct6-orders','command','1938-10-06；13时下反攻令，15时指挥所命令（论文转引）','hour',
        ['ww2.cn.corps1','ww2.cn.army4','ww2.cn.army66','ww2.cn.army74','ww2.jp.division106'],
        ['白槎','石堡山','石头岭'],'命令分别安排66军突击、4军掩护侧翼与74军向北攻击；这是命令记录，不等于当时已经攻占。','第119页：6日13时薛岳下反攻令、15时吴奇伟白槎指挥所命令；引档案7878201及张秉均记述')
    operation(attack,'WJL-Oct7-shibao','attack','1938-10-07，当日','day',
        ['ww2.cn.army66','ww2.cn.division159','ww2.cn.division161.wjl_part','ww2.jp.division106'],
        ['金娥殿','公母岭','石堡山'],'159师与161师投入部向石堡山推进；不推定整个161师到场或全师改隶。','第119页：10月7日66军159师及161师之一部攻击段')
    operation(attack,'WJL-Oct7-eastern','combat','1938-10-07；7时（论文记述）','hour',
        ['ww2.cn.army4','ww2.jp.division106'],['刘家岭'],'4军游击部队发生接触；不能把该分队人数或位置推广到整个军。','第119页：4军游击部队7时刘家岭遭遇段')
    operation(attack,'WJL-Oct7-changling','attack','1938-10-07，当日','day',
        ['ww2.cn.army74','ww2.jp.division106'],['长岭','张古山'],'74军收复长岭并围住张古山；阵地控制仍会变化，不把包围写成日军已全歼。','第119页：74军长岭克复与张古山包围段')
    operation(counter,'WJL-Oct8-zhanggu','counterattack','1938-10-08，拂晓至天明后','period',
        ['ww2.cn.division51','ww2.jp.division106'],['张古山'],'51师一度夺取最高点，随后日军在航空支援下反攻夺回；两次控制权变化均保留。','第119页：8日拂晓51师攻克、天明后日军反攻段')
    operation(counter,'WJL-Oct8-hills','attack','1938-10-08，当日；部分动作记11时','period',
        ['ww2.cn.army66','ww2.cn.army4','ww2.cn.division142','ww2.jp.division106'],
        ['石堡山','老虎尖','狮子崖西北高地','城门山','桶汉傅','周家'],'66军与4军继续高地攻击；142师欠一团出击。具体余部、地名异写与阵位待补核。','第119页：8日66军进占、协同4军与142师11时出击段')
    for phase in (orders,attack,counter):
        phase['relations']=[]
    for child in ('ww2.cn.army4','ww2.cn.army66','ww2.cn.army74'):
        attack['relations'].append(dict(id='WJL-Oct7-command-'+child.split('.')[-1],kind='operational_command',
            parent_id='ww2.cn.corps1',child_id=child,scope='本阶段第一兵团协同任务参考；未重写永久行政隶属。',evidence=evidence('第118—119页：第一兵团部署与各军攻击任务')))
    attack['relations'].append(dict(id='WJL-Oct7-161-part',kind='operational_command',parent_id='ww2.cn.army66',
        child_id='ww2.cn.division161.wjl_part',scope='只关联文献所记161师一部的当前作战方向；不是全师永久改隶。',evidence=evidence('第119页：66军以159师及161师之一部展开')))
    hi.validate_definition(d)
    return d


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--check',action='store_true');args=p.parse_args()
    value=build();path=ROOT/'data/historical_initial/AJ07-wanjialing/1.1.0.json'
    if args.check:
        if not path.exists() or json.loads(path.read_text())!=value:raise SystemExit('Wanjialing 1.1.0 source snapshot differs')
        print('Wanjialing additive snapshot matches builder')
    elif path.exists():
        if json.loads(path.read_text())!=value:raise SystemExit('Refusing to overwrite an existing different version')
        print('Wanjialing 1.1.0 already matches; unchanged')
    else:
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');print('Created Wanjialing 1.1.0; default/1.0.0 unchanged')


if __name__=='__main__':main()
