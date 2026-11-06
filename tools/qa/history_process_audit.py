"""Inventory implemented history/process contracts, not historical-effectiveness validation.

Uses installed source cards and executable definitions; performs no model calls
and does not modify saved campaigns. Required mechanisms below are a design
assessment, explicitly separate from measured implementation properties.
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from gentactix import combined_arms, history_replay, sim_clock

# The first field describes the historical problem represented by the local
# source cards, not a claim that the executable model implements it.
REQUIREMENTS = {
    '淞沪会战': ('市区抵抗→沿江登陆→罗店/大场争夺→杭州湾侧背威胁→撤离', '登陆点与到达梯队、沿水网补给、侧翼预警和撤退通道', 'P1'),
    '太原会战': ('平型关/忻口正面牵制与敌后破袭并行→娘子关侧翼失守→撤离', '多轴线协同、交通延误、侧翼突破触发而非八回合存活', 'P1'),
    '平型关伏击战': ('运输纵队进入伏击区→封口分割→近战→脱离', '行军纵队、隐蔽/暴露、伏击区与敌增援；占领桥东不能代表伏击成功', 'P1'),
    '徐州会战总览': ('滕县/临沂/台儿庄并行→日军扩张包围→主力突围', '子战场时间同步、援军到达、合围缺口；总览须拆局部切片', 'P2'),
    '台儿庄战役': ('城内坚守↔临沂阻援→外围反击→敌军撤退', '街区控制、守城消耗与外围合围的时限耦合', 'P1'),
    '武汉会战': ('江上推进与南北岸作战→万家岭局部包围→主力撤离', '江运/要塞/侧翼多轴线、疏散完成度与非战斗减员', 'P2'),
    '万家岭战役': ('深入→局部包围→阻援与收缩→围歼程度判定', '包围封闭度、空投/增援、残部突围；占点不等于歼灭', 'P1'),
    '桂南会战与昆仑关攻坚': ('周边高地争夺→关隘攻坚→阻援→巩固', '山地道路、步炮装协同、增援计时；不得预设旅团全灭', 'P1'),
    '第一次长沙会战': ('多河线迟滞→纵深接近→侧翼反击→日军撤离', '河线分层、进攻补给距离、撤离触发；存活八轮不足以代表会战', 'P2'),
    '第二次长沙会战': ('前沿突破→长沙方向推进→调整与撤出', '与第一次、第三次分开配置部署、通信与撤退条件', 'P2'),
    '第三次长沙会战': ('前沿诱入→长沙守城→外翼向心反击→追击', '炉底/炉壁、多路合围到达同步和补给顶点', 'P1'),
    '百团大战': ('交通破袭→据点攻坚→反扫荡', '铁路网连通/修复、据点警戒、敌反应延迟和根据地损耗', 'P1'),
    '冀中五一反扫荡': ('合围与封锁→隐蔽分散/转移→持续反扫荡', '表面占领与地下组织独立、平民与补给网络、长期追捕成本', 'P2'),
    '豫湘桂战役总览': ('豫中→长衡→桂柳，跨战区铁路轴线推进', '战区交接、铁路/机场网络、有效兵力与指挥失效；拆分阶段', 'P2'),
    '衡阳保卫战': ('外围接敌→多次总攻→援军受阻→守军耗竭', '分次进攻与休整、围城库存、救援时限、撤离/停战选择', 'P1'),
    '敌后局部反攻总览': ('选择局部目标→集中攻坚/打援→巩固根据地', '目标群与区域控制、分散转集中成本；不能压成单桥争夺', 'P2'),
    '车桥战役': ('隐蔽接近→攻点→阻援→巩固/撤出', '攻点/打援两组命令、交通节点、日伪军分别记账', 'P1'),
    '湘西会战': ('山地阻击→航空遮断→局部反击→日军退却', '地面多轴线与航空架次、补给线、目标复核；现有航空仅局部抽象', 'P1'),
    '缅北滇西反攻总览': ('缅北/滇西并行攻坚→交通线贯通', '双战区、河谷道路/据点与航空运输；航空任务不等于战区复原', 'P2'),
    '全面反攻与受降总览': ('反攻命令→地方停火/继续抵抗→缴械登记→交通与城市接收', '地区命令服从、交涉/拒降/缴械状态、受降权限；不得第4轮全局停火', 'P0'),
    '湘江战役': ('渡口抢占→阻击掩护→中央纵队过江→后卫撤离', '分列战斗/非战斗纵队、渡场容量、道路排队与后卫接替', 'P1'),
    '强渡乌江': ('侦察与试渡→夺取桥头→架桥→主力通过', '船/浮桥工程并行、桥头掩护和通行吞吐；不以到出口代替渡江', 'P1'),
    '四渡赤水': ('土城接触与调整→多次渡河/转向→遵义反击→脱离合围', '渡口网络、敌我不完全情报、机动/追堵速度、四阶段可选转向', 'P1'),
    '中央红军巧渡金沙江': ('佯动→夺取渡口与船只→连续摆渡→脱离追击', '船只与班次、追兵时距、隐蔽渡场；非必须歼敌的渡河组织', 'P1'),
    '强渡大渡河与飞夺泸定桥': ('安顺场渡河→两岸分路→奔袭→夺桥→主力通过', '船容量与桥梁状态、两岸时钟、疲劳和敌援到达', 'P1'),
    '懋功会师与雪山草地转移': ('会师→补给/路线分歧→翻山与草地转移→分路', '多路指挥、非战斗损耗、粮食/宿营和战略路线；不能强制持续交战', 'P2'),
    '嘉陵江战役': ('多渡点突击→桥头扩张→纵深发展与分割', '渡点/桥梁网络、主攻与助攻、增援反应；当前突围目标失配', 'P1'),
    '包座战役': ('围点→援军进入→打援→围歼与通道开放', '围点/打援分兵、援军到达、退路控制；当前突围目标失配', 'P1'),
    '腊子口战斗': ('正面压制→攀崖迂回→侧后突击→通路开放', '隘口正面与攀崖可达性、分队同步；不是通用出口移动', 'P1'),
    '直罗镇战役': ('诱入→围点/阻援→突围与围歼', '诱敌判断、封闭退路、俘虏与伤亡分账；当前突围目标失配', 'P1'),
    '百丈关战役': ('初期推进→敌增兵反扑→消耗顶点→撤退重组', '兵力到达、续战阈值、撤退秩序；不能把南下失利简化为向出口移动', 'P1'),
    '红二十五军长征': ('独立转移→多次突围与建基→继续北上→会师', '跨月路线、追堵、补充/脱离与根据地；应拆局部节点', 'P2'),
    '乌蒙山回旋战': ('分路追堵→连续转向与迂回→摆脱包围', '道路图、情报时延、追踪与反追踪、疲劳；固定出口不足', 'P1'),
    '红二六军团抢渡金沙江': ('组织渡口→连续摆渡→转移主力', '渡船吞吐、纵队排队、追兵窗口；无接触不强造交战', 'P1'),
    '甘孜会师至三大主力会师': ('多路集结→北上→先头接应→总部与主力会师', '多军团身份、路线同步、补给与会师判定；会师不是歼灭战', 'P2'),
    '第一次战役': ('隐蔽开进→遭遇→分途反击→稳定战线', '通信管制、接触发现、前锋/后续梯队；通用占点失配', 'P1'),
    '第二次战役': ('诱敌→东西线反击→分割阻击→追击/撤离', '东西线独立、严寒冻伤、追击通道和海运撤离', 'P1'),
    '第三次战役': ('突破既设阵地→追击→城市占领→补给极限', '突破/追击速度、城市时间窗口与向第四次战役传递状态', 'P2'),
    '第四次战役': ('西线迟滞↔东线反击→逐次后撤→新兵团集结', '多线时间换空间、增援到达、攻击补给周期；当前为占点进攻目标', 'P1'),
    '第五次战役': ('第一阶段进攻→东线转兵→补给顶点→转移阻击', '阶段换向、空中遮断、摩托化追击与通信中断；不预设180师结局', 'P1'),
    '夏秋季防御战役': ('夏季进攻→秋季进攻→要点争夺/反坦克→稳定战线', '双时段/双线、洪水与遮断、工事火力及谈判压力', 'P2'),
    '秋季战术反击作战': ('多点有限攻击→反扑争夺→巩固或主动撤出', '目标群、炮兵火力分配、攻克/巩固分开、交替休整', 'P1'),
    '上甘岭战役': ('地表阵地争夺↔坑道存续→补给/换防→反击巩固', '地表/坑道双状态、水弹兵员补给与炮兵周期；存活八轮不等于守住两高地', 'P1'),
    '夏季反击战役含金城战役': ('多阶段反击→金城突破→纵深发展→巩固与停战', '火力准备、突破口/纵深道路、谈判截止及土地巩固', 'P2'),
    '长平之战': ('坚守→指挥调整/出击→佯退→分割断粮→突围或投降', '粮道网络、分割/封闭程度、四十六日围困与投降；保留史料数字口径', 'P2'),
}


def audit():
    rows = []
    for spec in combined_arms.catalog():
        battle = spec['battle']; short = battle.split('-')[1] if '-' in battle else battle
        process, missing, priority = REQUIREMENTS[short]
        source = history_replay.dataset(battle)
        frames = [history_replay.frame(battle, i) for i in range(len(source['events']))]
        initial = spec['initial_state']
        labels = [u['name'] for team in ('red_units', 'blue_units') for u in initial[team]]
        rows.append({'battle': battle, 'card': 'corpus/' + battle + '.md',
            'source_event_count': len(frames), 'structured_force_records': len(source['forces']),
            'replay_unit_counts': sorted({len(f['red_units']) + len(f['blue_units']) for f in frames}),
            'open_model': spec['combined_rules']['version'], 'open_goal_profile': spec['combined_rules']['goal_profile'],
            'open_unit_count': len(labels), 'open_units_all_synthetic_labels': all('教学' in x for x in labels),
            'open_seconds_per_turn': sim_clock.duration_seconds(spec['time_step']), 'open_deadline_turn': spec['deadline_turn'],
            'process_assessment': '尚不能重现完整历史作战过程',
            'required_process_design': process, 'missing_process_design': missing, 'priority': priority,
            'assessment_basis': '执行初态/目标/事件帧与本地史料卡的合同审计；非逐场真实模型或历史效能验收'})
    assert len(rows) == len(REQUIREMENTS) == 45
    assert all((ROOT / r['card']).is_file() for r in rows)
    return rows


def main():
    rows = audit()
    target = ROOT / 'docs/历史过程逐场审计.json'
    target.write_text(json.dumps({'scope': '原CA兼容模板与严格事件帧的合同审计；DSH派生配置另行验收，不代表史料全部重新核实', 'battles': rows}, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'catalog': len(rows), 'with_structured_force_records': sum(r['structured_force_records'] > 0 for r in rows),
        'synthetic_open_initials': sum(r['open_units_all_synthetic_labels'] for r in rows),
        'replay_frames': sum(r['source_event_count'] for r in rows),
        'replay_frames_with_units': sum(any(r['replay_unit_counts']) for r in rows), 'output': str(target)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
