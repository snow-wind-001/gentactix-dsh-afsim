"""Add independently sourced LM15 reunion windows; preserve all published pins."""
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from gentactix import historical_initial as hi,campaign_windows as cw

BATTLE='红军长征-甘孜会师至三大主力会师-1936.07.01至1936.10.22'
WINDOWS={
 'LM15-ganzi-jul1-2':('ganzi_assembly','甘孜：7月1—2日两军团集结',('re.red.corps2','re.red.corps6')),
 'LM15-huining-oct9-10':('huining_assembly','会宁：10月9—10日分路会合',('re.red.division1','re.red.division2','re.red.division73','re.red.army4','re.red.army31')),
 'LM15-jiangtaibao-oct22':('jiangtaibao_meeting','将台堡：10月22日本地会合',('re.red.corps2','re.red.division2')),
}


def ev(source,locator):return [dict(source_id=source,locator=locator)]


def source(title,url,publisher,limitations,kind='published_secondary'):
    return dict(title=title,url=url,publisher=publisher,evidence_kind=kind,original_archive_examined=False,limitations=limitations)


def operation(identity,kind,date,units,places,description,evidence,limitations,precision='day'):
    return dict(id=identity,kind=kind,date=dict(label=date,precision=precision),unit_ids=units,
        places=[dict(name=name,position=None,evidence=copy.deepcopy(evidence))for name in places],
        description=description,evidence=copy.deepcopy(evidence),limitations=limitations)


def phase(identity,label,date,start,end,center,radius,evidence,geo,scope):
    value=dict(id=identity,label=label,date=dict(label=date,precision='range',evidence=copy.deepcopy(evidence)),scope=scope,evidence=copy.deepcopy(evidence),
        interaction=dict(kind='non_contact_transfer',active_teams=['red'],scope='只计算所列红军本地集结、接应和供给；不代表整个会师战区无敌军，不隐藏其他方向的后卫战斗或生成虚构蓝军。',evidence=copy.deepcopy(evidence)))
    if center is not None:
        value['geographic_scope']=dict(center=dict(lat=center[0],lng=center[1]),radius_km=radius,kind='model_scope_limit',
            note='现代地名粗定位与模型工作范围，不是1936年实测阵地、逐单位部署或误差置信区间。',evidence=copy.deepcopy(geo))
    if start is not None and end is not None:
        value['execution_window']=dict(start=start,end=end,kind='model_scope_limit',note='日期取自所列来源；零时及末日边界为离散化约定，不是已核钟点。开放推演按会合目标判定，不强制历史结果。',evidence=copy.deepcopy(evidence))
    return value


def build():
    value=hi.definition(BATTLE,'1.0.0');value['version']='1.1.0'
    value['sources']['REUNION']['url']='https://www.mod.gov.cn/gfbw/gfjy_index/js_214151/16418521.html'
    value['sources'].update(
        XINHUA_REUNION=source('三军大会师——红军长征三大主力会师全纪录','https://www.cac.gov.cn/2016-08/22/c_1119432029.htm','新华社／中央网信办转载，2016-08-22','公开报道及采访，未亲核原始电报；会合日期与庆祝、后续兴隆镇事件分开，文中其他阶段总数不作为本地兵额。'),
        PLA_LIUPAN=source('红旗漫卷六盘山','https://cpc.people.com.cn/n1/2026/1101/c443712-40825293.html','解放军报／人民网转载，2026-11-01','报道转述博物馆电报及接应史事，未亲核电报原件；22日将台堡与23日兴隆镇不同，慰问物资不等于逐单位开局库存。'),
        GUANGMANG=source('三军会宁大会师，《光芒》2020年第1期第22—23页','https://www.gscn.com.cn/doc/003/006/910/00300691032_348ae422.pdf','甘肃省延安精神研究会／中国甘肃网','已核PDF第23页图像与文字，非原始档案；7—8日先头会合地点与静宁县志办叙述存在异文，不合并为精确部署。仅采用逐项定位内容。'),
        JINGNING=source('红军长征过静宁','https://www.gsjn.gov.cn/zjjn/jnfz/art/2022/art_f50ab4aff934446c8967070a69859278.html','静宁县县志办，网页标注2017-12-26','地方史志公开叙述，7—8日会合地点及接应对象与其他记述有异文；保留，不据此强定钟点或用会战总数补人数。','official_history'),
        GEO_huining=source('会宁县城现代地名参考','https://www.geonames.org/1806807/','GeoNames／项目原地名资料','只作现代聚落定位；不是会师阵位、部队初态或行军路线。'),
        GEO_jiangtai=source('将台堡镇现代地名参考','https://zh.wikipedia.org/wiki/%E5%B0%86%E5%8F%B0%E5%A0%A1%E9%95%87','维基百科地名页，2026-11-03核读','仅采用现代镇位置35.81754,105.83963作粗定位，不混用高德坐标、不作为1936年部队实测或纪念碑精确位置。'))
    value['coverage']['notes'] += [
        '1.1.0补甘孜、会宁、将台堡独立本地窗口及来源关联；不是三个月全程连续战役，也不自动把已发表1.0.0或默认版本迁移。',
        '会宁9—10日仅列已核本地接应和到达单位；第2师、第4军、第31军的计算投入须明确本地范围，不把全军都放在城内。第10师仅作第4军内8日活动参考，不证明9—10日部署，不能双计或推定其覆盖完整。',
        '红二方面军7月5日形成；此前的红2、6军团不倒挂到尚未成立的方面军。阶段编制关系另列，指挥机关不成为战斗实体。',
        '10月22日将台堡本地只核红2军团及红一军团第2师；红6军团与第1师翌日在兴隆镇会合。红32军领导到场不能证明全军同时在同点。',
        '7—8日青江驿／界石铺先头会合的细节存在来源异文；采用分路、先头与后续的共同层次，不伪造统一逐时轨迹。逐单位实到兵额、完好装备、粮弹、路程和时点仍未知。']
    ganzi=next(p for p in value['phases']if p['id']=='ganzi_assembly')
    ganzi['operations']=[
        operation('LM15-Jul1-assembly','concentration','1936-07-01',['re.red.corps2','re.red.corps6'],['甘孜地区'],'红2、红6军团在甘孜地区完成集结；不是各部同时占据城镇中心。',ev('REUNION','甘孜会师：7月1日全部集结段'),'只有日级集体过程；前期甲洼、绒坝岔接触不是本地开局。'),
        operation('LM15-Jul2-celebration','command','1936-07-02',['re.red.corps2','re.red.corps6'],['甘孜地区'],'举行会师庆祝活动；庆祝不生成兵力、库存或新的作战单位。',ev('REUNION','甘孜会师：2日庆祝、5日整编段'),'日级记录；不将庆祝和7月5日整编合并成一个事件。')]
    huining=phase('huining_assembly','会宁分路到达与会合','1936年10月9日至10日','1936-10-09T00:00','1936-10-11T00:00',(35.69196,105.04858),70,
        ev('GUANGMANG','第23页左栏：9日总部、第4军及第31军到达，接应的第1师、第2师一部、第73师；10日庆祝'),ev('GEO_huining','会宁县城现代聚落参考'),
        '会宁及相邻接应方向的非接敌集结片段；不重演此前夺城或整个会师战区后卫作战；所有单位部署须独立估计。')
    huining['operations']=[
        operation('LM15-Oct9-huining-arrival','concentration','1936-10-09',['re.red.front4','re.red.army4','re.red.army31','re.red.division1','re.red.division2','re.red.division73'],['会宁及周边接应地域'],'总部与所列红四方面军部队陆续到达，由所列红一方面军接应部队迎接；第2师记录为一部，不外推全师同地。',ev('GUANGMANG','第23页左栏首段：9日到达及接应单位'),'只有日级到达范围；师军的本地投入份额、坐标、人数均未核，不能从迎接活动推成全军已展开。'),
        operation('LM15-Oct10-huining-celebration','command','1936-10-10黄昏',['re.red.front4'],['会宁文庙'],'举行会师庆祝活动并传达中央贺电；参会代表不等于各军全体列队，更不代表红二方面军全体已经到场。',ev('XINHUA_REUNION','会宁节：9日指挥部进入、10日傍晚庆祝'), '只支持活动及所列指挥参考，不合成人员或恢复满编。',precision='period')]
    jiangtai=phase('jiangtaibao_meeting','将台堡本地会合','1936年10月22日','1936-10-22T00:00','1936-10-23T00:00',(35.81754,105.83963),20,
        ev('PLA_LIUPAN','第三节：22日红二方面军总指挥部率红2军团与红一军团第2师会合'),ev('GEO_jiangtai','现代镇位置，非纪念碑或历史部队阵位'),
        '仅将台堡本地接应与会合，不将红6军团翌日兴隆镇过程或未核红32军全部位置搬入本地。')
    jiangtai['operations']=[
        operation('LM15-Oct22-jiangtai-meeting','concentration','1936-10-22',['re.red.front2','re.red.corps2','re.red.division2'],['将台堡'],'红二方面军总部及红2军团到达，将台堡的接应部队为红一军团第2师；建立联络与会合条件。',ev('PLA_LIUPAN','第三节末：22日将台堡第2师会合与23日兴隆镇第1师会合分述'),'日级记录不证明每个下级同时到场，不补红32军全军部署或历史伤亡。'),
        operation('LM15-Oct22-arrival-report','command','1936-10-22原文24时发电',['re.red.front2','re.red.corps1'],['将台堡','硝河城'],'报道转述当夜电报，报告领导及部分部队已经抵达，其他部队尚在随后到达的过程中。',ev('PLA_LIUPAN','第三节博物馆电报转述，署22日24时'),'转述而非亲核电报原件；发电时刻不是全体到达时刻，不能把两个地名合并成一个坐标。',precision='hour')]
    followup=phase('xinglong_followup','兴隆镇后续会合参考','1936年10月23日',None,None,None,None,
        ev('PLA_LIUPAN','第三节：23日红6军团与第1师在兴隆镇会合'),[],
        '窗口外的次日来源参考；本地坐标尚未独立核定，未登记可计算会战窗口，不从14或15公里概述反算精确位置。')
    followup['operations']=[operation('LM15-Oct23-xinglong-meeting','concentration','1936-10-23',['re.red.corps6','re.red.division1'],['兴隆镇'],'红6军团与红一军团第1师在兴隆镇会合，保留与前一日将台堡不同的日期和地域。',ev('PLA_LIUPAN','第三节末：23日兴隆镇，约在将台堡14公里外'),'与新华社回顾的约15公里为概述精度，不能据距离反算精确坐标或逐时路线。')]
    value['phases'] += [huining,jiangtai,followup]
    definitions=[('re.red.front1','红一方面军指挥参考','command','方面军',None),('re.red.front2','红二方面军指挥参考（7月5日起）','command','方面军',None),
        ('re.red.front4','红四方面军指挥参考','command','方面军',None),('re.red.corps1','红一军团指挥参考','command','军团','re.red.front1'),('re.red.corps15','红15军团指挥参考','command','军团','re.red.front1'),
        ('re.red.division1','红一军团第1师','formation','师','re.red.corps1'),('re.red.division2','红一军团第2师','formation','师','re.red.corps1'),
        ('re.red.division73','红15军团第73师','formation','师','re.red.corps15'),('re.red.army4','红四方面军第4军','formation','军','re.red.front4'),
        ('re.red.army31','红四方面军第31军','formation','军','re.red.front4'),('re.red.army4.division10','红四方面军第4军第10师','formation','师','re.red.army4')]
    for identity,name,role,echelon,parent in definitions:
        refs=ev('GUANGMANG','第23页：会宁到达与接应序列，第4军第10师；只列已核身份，不代表下级完整')
        if identity in ('re.red.front2','re.red.corps1'):refs=ev('PLA_LIUPAN','第三节：将台堡总部及红一军团第2师会合')
        value['units'].append(dict(id=identity,name=name,team='red',role=role,echelon=echelon,parent_id=parent,evidence=refs,presence=[],
            facts={k:dict(value=None,evidence=[],scope='未核此身份在本地阶段的实到数、完好装备或部署；事件及现代地名不能代填单位初态。')for k in ('personnel','equipment','position')},
            children_coverage=dict(status='partial',scope='仅登记所列可核下级，未载余部必须保留；不能将参考名单当完整战斗序列。',evidence=copy.deepcopy(refs))))
    known={phase_id:set(actors)for phase_id,_,actors in WINDOWS.values()}
    known['second_front_formation']={'re.red.corps2','re.red.corps6','re.red.army32','re.red.front2'}
    known['huining_assembly'].update(('re.red.front4','re.red.corps1','re.red.corps15'))
    known['jiangtaibao_meeting'].update(('re.red.front2','re.red.corps1'))
    known['xinglong_followup']={'re.red.corps6','re.red.division1'}
    for unit in value['units']:
        existing={p['phase_id']for p in unit['presence']}
        for p in value['phases']:
            if p['id'] in existing:continue
            status='campaign_participant'if p['id']=='campaign_reference'else'reported_present'if unit['id'] in known.get(p['id'],set())else'outside_scope'
            if unit['id']=='re.red.army4.division10'and p['id']=='huining_assembly':status='campaign_participant'
            unit['presence'].append(dict(phase_id=p['id'],status=status,evidence=copy.deepcopy(p['evidence'])))
    for p in value['phases']:
        if p['id'] in ('second_front_formation','jiangtaibao_meeting'):
            members=['re.red.corps2','re.red.corps6','re.red.army32']if p['id']=='second_front_formation'else['re.red.corps2']
            p['relations']=[dict(id='LM15-'+p['id']+'-admin-'+str(i),kind='administrative',parent_id='re.red.front2',child_id=identity,
                scope='7月5日以后的编制来源参考，不倒推7月1日方面军已成立，也不自动创建本局命令。',evidence=ev('REUNION','甘孜会师：7月5日合编红二方面军'))for i,identity in enumerate(members)]
    hi.validate_definition(value);return value


def windows(value):
    result={};phases={p['id']:p for p in value['phases']}
    for identity,(phase_id,label,actors)in WINDOWS.items():
        p=phases[phase_id];operations=[o['id']for o in p['operations']];rows={}
        for u in value['units']:
            represented=None;basis='not_applicable'
            if u['id'] in actors:kind='actor';basis='window_reference'
            elif u['role']=='command':kind='command_reference'
            elif phase_id=='huining_assembly'and u['id']=='re.red.army4.division10':kind='covered_reference';represented='re.red.army4';basis='prior_reference'
            else:
                kind='outside_window';order=[p['id']for p in value['phases']]
                if any(r['status']=='reported_present'and order.index(r['phase_id'])<order.index(phase_id)for r in u['presence']):basis='prior_reference'
            rows[u['id']]=dict(representation=kind,represented_by=represented,presence_basis=basis,
                extent='只计本地已说明投入载荷；未核人数装备与余部，不能宣称整军同点。'if kind=='actor'else'保留历史身份参考，不额外投入人员、装备、粮弹或单位位置。',opening='requires_explicit_estimate',
                operation_ids=[o['id']for o in p['operations']if u['id']in o['unit_ids']],operational_reference=None,evidence=copy.deepcopy(u['evidence']))
        result[identity]=dict(format=cw.FORMAT,id=identity,version='1.0.0',label=label,battle=BATTLE,historical_initial=dict(profile_id=value['id'],version=value['version'],definition_hash=hi.digest(value)),
            start_phase_id=phase_id,phase_ids=[phase_id],bounds={k:copy.deepcopy(p['execution_window'][k])for k in ('start','end','kind','note')},units=rows,
            sectors=[dict(id=identity+'-assembly',label=label+'的来源方向',position=None,unit_ids=list(actors),operation_ids=operations,evidence=copy.deepcopy(p['evidence']))],
            milestones=[dict(operation_id=o,phase_id=phase_id,policy='reference_only')for o in operations],
            limitations='独立本地会合窗口，不是全方面军、全长征或消灭敌军任务。史实仅约束来源身份、节点和精度；部署、人数、装备、路线、库存与会合阈值须显式估计，开放过程不强迫历史结果。')
    return result


def objective_binding(value):
    rows={}
    for p in value['phases']:
        if not p.get('execution_window'):continue
        refs=p['evidence'];rows[p['id']]=dict(guidance=dict(team='red',profile='breakout',objective_label=p['label']+'的会合与保存目标',
            scope_note=p['scope']+'；以联络、分路到达和保存条件计算，不因没有蓝方而自动获胜。',not_covered=['全长征或全会师战区过程','逐单位历史兵额、装备、部署及后勤标定'],evidence=copy.deepcopy(refs)),
            source_hashes={e['source_id']:hi.digest(value['sources'][e['source_id']])for e in refs})
    return dict(initial_definition_hash=hi.digest(value),phases=rows)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--check',action='store_true');args=p.parse_args();value=build();items=windows(value)
    artifacts={hi.DATA_ROOT/'LM15-reunion/1.1.0.json':value}
    for identity,item in items.items():
        cw.validate_definition(item,hi._materialize(value,item['start_phase_id'])['historical_initial']);artifacts[cw.DATA_ROOT/identity/'1.0.0.json']=item
    for path,item in artifacts.items():
        if path.exists():
            if json.loads(path.read_text())!=item:raise SystemExit('Published version differs; create a new version: '+str(path))
        elif args.check:raise SystemExit('Missing source/window: '+str(path))
        else:path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(item,ensure_ascii=False,indent=2)+'\n')
    path=ROOT/'data/historical_objective_bindings.json';data=json.loads(path.read_text());wanted=objective_binding(value);actual=data['profiles']['LM15-reunion'].get('1.1.0')
    if actual is not None and actual!=wanted:raise SystemExit('Existing objective pin differs; review explicitly')
    if args.check and actual!=wanted:raise SystemExit('New LM15 objective pin missing')
    if actual is None:data['profiles']['LM15-reunion']['1.1.0']=wanted;path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    print('LM15 new source and three independent windows consistent; old versions/default unchanged')


if __name__=='__main__':main()
