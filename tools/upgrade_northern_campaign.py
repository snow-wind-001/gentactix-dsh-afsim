"""Add dated army reports and Wuhan northern-front sources without migrating old versions."""
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from gentactix import historical_initial as hi,campaign_windows as cw

WH='抗日战争-武汉会战-1938.06至1938.10'
WJL='抗日战争-万家岭战役-1938.09下旬至1938.10'
PHASE='northern_sep17_18'
WINDOW='WH-northern-sep17-18'
NOTE=('北线已核身份与公开行动之上的探索计算范围；人数、装备、库存、坐标及目标阈值均为待填估计，'
      '不是历史实编或历史效能标定。不得将整个武汉会战总数均摊，不以既定历史战果自动扣人或判胜。')


def evidence(source,locator):return [dict(source_id=source,locator=locator)]


def measurement(identity,unit,date,statistic,value,population,locator):
    return dict(id=identity,date=dict(label=date,precision='range'),unit_ids=[unit],metric='personnel',
        quantity=dict(relation='eq',lower=value,upper=value,unit='persons'),statistic=statistic,
        population=population,evidence=evidence('WJL_GUO',locator),
        limitations='论文转引档案统计，原件数字未逐字核清；累计参战不是每天开局现员，损失分类按原口径，不自动作初态或裁决配额。')


def wanjialing():
    d=hi.definition(WJL,'1.4.0');d['version']='1.5.0'
    d['sources']['WJL_GUO']['limitations']+=(
        ' 2026-11-03视觉核读印刷124—125页：第74军9月30日至10月15日参战18998、死伤及生死不明9504；'
        '第66军10月7—12日参战8815、伤亡3613。两项期间与损失口径不同，不拆分为师级或每天定额。')
    phases={p['id']:p for p in d['phases']}
    for phase,rows in [('oct12_redeployment',[
        measurement('WJL-M-66-participants','ww2.cn.army66','1938-10-07至1938-10-12','reported_strength',8815,
            '第66军该六日统计范围的累计参战官兵；不是整军核定编制或10月6日现员。','印刷124页末至125页首；125页脚注转引7878204附表'),
        measurement('WJL-M-66-casualties','ww2.cn.army66','1938-10-07至1938-10-12','reported_casualties',3613,
            '上述第66军参战群体六日的伤亡合计；没有逐日及阵亡／负伤分项。','印刷125页首及脚注，参战8815和伤亡3613同段')]),
        ('oct17_withdrawal',[
        measurement('WJL-M-74-participants','ww2.cn.army74','1938-09-30至1938-10-15','reported_strength',18998,
            '第74军该期间累计参战官兵；不是第51／58师各18998人或某日开局现员。','印刷124页末及脚注，转引第36军团详报附表7878203'),
        measurement('WJL-M-74-losses','ww2.cn.army74','1938-09-30至1938-10-15','reported_casualties',9504,
            '第74军该期间死伤及生死不明合计；包含失联类别，不能全部解释为阵亡或与纯死伤口径混同。','印刷124页末，参战18998与死伤及生死不明9504同段')])]:
        phases[phase].setdefault('measurements',[]).extend(rows)
    d['coverage']['notes'].append('1.5.0补四条有明确军级对象和期间的统计；不是新增四个单位或兵额初态，不调整旧计算先验。')
    hi.validate_definition(d);return d


def wuhan():
    d=hi.definition(WH,'1.1.0');d['version']='1.2.0'
    for key,title,issue,url,limitation in [
        ('WH_ZX_DABIE7','大别烽烟（上）——“保卫大武汉”系列之七','第7期，第29—35页',
         'https://www.whzx.gov.cn/zxzl/wsl/whwszl/202508/P020250801384624511936.pdf',
         '核读富金山与沙窝—小界岭段；第61师归属、个别团号及末段伤亡分项有待原始资料复核，不据此补造行政隶属或精确兵额。'),
        ('WH_ZX_DABIE8','大别烽烟（下）——“保卫大武汉”系列之八','第8期，第39—45页',
         'https://www.whzx.gov.cn/zxzl/wsl/whwszl/202509/P020250910402058831607.pdf',
         '核读潢川、信罗段及部署、日期；URL上传月份不是纸本期号。伤亡战果仍为作者综合记述，不作确定开局实力或逐日杀伤。')]:
        d['sources'][key]=dict(title=title,url=url,publisher='武汉市政协《武汉文史资料》2025年'+issue+'，涂文学',
            evidence_kind='published_secondary',original_archive_examined=False,limitations=limitation)
    def ev(page,source='WH_ZX_DABIE7'):return evidence(source,'印刷'+page+'；公开研究转述，非本次亲阅原始军令')
    rows=[
        ('ww2.cn.group2','第2集团军','red','command','集团军',None,'33页'),
        ('ww2.cn.corps27','第27军团指挥部','red','command','军团',None,'41页'),
        ('ww2.cn.army71','第71军','red','formation','军',None,'31、33页'),
        ('ww2.cn.army59','第59军','red','formation','军',None,'40—41页'),
        ('ww2.cn.army30','第30军','red','formation','军',None,'33页'),
        ('ww2.cn.army42','第42军','red','formation','军',None,'33页'),
        ('ww2.cn.army51','第51军','red','formation','军',None,'33页'),
        ('ww2.cn.division36','第36师','red','formation','师','ww2.cn.army71','31—33页'),
        ('ww2.cn.division88','第88师','red','formation','师','ww2.cn.army71','31、33页'),
        ('ww2.cn.division87','第87师','red','formation','师','ww2.cn.army71','34—35页'),
        ('ww2.cn.division113','第113师','red','formation','师',None,'31页'),
        ('ww2.cn.division114','第114师','red','formation','师',None,'31页'),
        ('ww2.cn.division61','第61师（归属待核）','red','formation','师',None,'33页；与下篇40页的归属记述需另核'),
        ('ww2.cn.division38','第38师','red','formation','师','ww2.cn.army59','40—41页'),
        ('ww2.cn.division180','第180师','red','formation','师','ww2.cn.army59','40—41页'),
        ('ww2.cn.division30','第30师','red','formation','师','ww2.cn.army30','33页'),
        ('ww2.cn.division31','第31师','red','formation','师','ww2.cn.army30','33页'),
        ('ww2.cn.division27','第27师','red','formation','师','ww2.cn.army42','33页'),
        ('ww2.jp.division16','日军第16师团','blue','formation','师团',None,'31—33页'),
        ('ww2.jp.shinohara_detachment','日军筱原支队','blue','formation','支队','ww2.jp.division16','33页'),
        ('ww2.jp.okada_detachment','日军冈田支队','blue','formation','支队','ww2.jp.division10','39—41页')]
    existing={u['id'] for u in d['units']}
    for identity,name,team,role,echelon,parent,page in rows:
        if identity in existing:raise ValueError('新来源身份与既有条目冲突，须显式核对：'+identity)
        source='WH_ZX_DABIE8' if identity in {'ww2.cn.corps27','ww2.cn.army59','ww2.cn.division38','ww2.cn.division180','ww2.jp.okada_detachment'} else 'WH_ZX_DABIE7'
        e=ev(page,source)
        d['units'].append(dict(id=identity,name=name,team=team,role=role,echelon=echelon,parent_id=parent,evidence=e,
            presence=[dict(phase_id='campaign_reference',status='campaign_participant',evidence=copy.deepcopy(e))],
            facts={key:dict(value=None,evidence=[],scope='仅核身份及分期行动，未核逐单位同日人数、分类装备和坐标；缺载保持未知。')for key in ('personnel','equipment','position')}))
    units={u['id']:u for u in d['units']}
    for parent in ('ww2.cn.army71','ww2.cn.army59','ww2.cn.army30','ww2.cn.army42','ww2.jp.division16','ww2.jp.division10'):
        units[parent]['children_coverage']=dict(status='partial',scope='仅列有依据的下级或分遣；机关直属、余部和隶属生效日未齐，不证明完整覆盖。',evidence=copy.deepcopy(units[parent]['evidence']))
    pdef=[('sep2_12_fujinshan','富金山方向与后续撤离','1938-09-02至1938-09-12','WH_ZX_DABIE7','31—32页'),
          ('sep7_18_huangchuan','潢川河流与城防争夺','1938-09-07至1938-09-18','WH_ZX_DABIE8','40—41页'),
          ('sep17_oct24_shawo','沙窝—小界岭长期迟滞','1938-09-17至1938-10-24','WH_ZX_DABIE7','33—35页'),
          (PHASE,'北线17—18日：山地与潢川并行','1938-09-17至1938-09-18','WH_ZX_DABIE7','33页；下篇40—41页潢川同时段')]
    phases={}
    for identity,label,date,source,page in pdef:
        p=dict(id=identity,label=label,date=dict(label=date,precision='range',evidence=ev(page,source)),
            scope='只关联本方向具名部队和记录；事件不能当作全部单位在阶段首时刻已到场，未知兵额装备部署不补齐。',evidence=ev(page,source),operations=[],relations=[])
        phases[identity]=p;d['phases'].append(p)
    mountain=['ww2.cn.army71','ww2.cn.army30','ww2.cn.army42','ww2.cn.army51','ww2.jp.shinohara_detachment']
    plain=['ww2.cn.division38','ww2.cn.division180','ww2.jp.division10']
    present={
        'sep2_12_fujinshan':{'ww2.cn.army71','ww2.cn.division36','ww2.cn.division88','ww2.cn.division113','ww2.cn.division114','ww2.jp.division13','ww2.jp.division16'},
        'sep7_18_huangchuan':{'ww2.cn.army59','ww2.cn.division38','ww2.cn.division180','ww2.jp.division10','ww2.jp.okada_detachment'},
        'sep17_oct24_shawo':set(mountain)|{'ww2.cn.division36','ww2.cn.division88','ww2.cn.division87','ww2.cn.division30','ww2.cn.division31','ww2.cn.division27','ww2.cn.division61','ww2.jp.division13','ww2.jp.division16'},
        PHASE:set(mountain+plain)|{'ww2.cn.army59','ww2.jp.division16','ww2.jp.okada_detachment'}}
    for identity,p in phases.items():
        for u in d['units']:
            status='reported_present' if u['id'] in present[identity] else 'outside_scope'
            if u['role']=='command':status='campaign_participant'
            u['presence'].append(dict(phase_id=identity,status=status,evidence=copy.deepcopy(p['evidence'])))
    def op(phase,identity,kind,date,precision,ids,places,text,page,source='WH_ZX_DABIE7'):
        e=ev(page,source);phases[phase]['operations'].append(dict(id=identity,kind=kind,date=dict(label=date,precision=precision),unit_ids=ids,
            places=[dict(name=n,position=None,evidence=copy.deepcopy(e))for n in places],description=text,evidence=e,
            limitations='公开研究记述／转引；不据本条补造开局人数、精确阵位、原始到达钟点或强制历史结果。'))
    op('sep2_12_fujinshan','WH-Fujin-deployment','defense','1938-09月初，2日夜起交战','range',
       ['ww2.cn.army71','ww2.cn.division36','ww2.cn.division88','ww2.cn.division113','ww2.cn.division114','ww2.jp.division13'],
       ['史河西岸','富金山'],'公开文献列四师在史河西岸及富金山纵深约8公里布防；只记作战指挥，不据此把113／114师永久划归71军。','31页')
    op('sep2_12_fujinshan','WH-Fujin-reinforcement','relief','1938-09-09','day',['ww2.jp.division16','ww2.jp.division13'],['叶家集'],'第16师团主力抵叶家集支援；到达叶家集不等于同刻全师投入富金山。','31—32页')
    op('sep2_12_fujinshan','WH-Fujin-withdrawal','withdrawal','1938-09-11夜至12日','period',['ww2.cn.division36','ww2.jp.division13','ww2.jp.division16'],['富金山'],'第36师在反击后撤离，主峰夜间被占；12日附近防线继续变化，不设确定性历史胜负脚本。','32页')
    op('sep7_18_huangchuan','WH-Huangchuan-deployment','defense','1938-09-07起，布防确时未载','range',
       ['ww2.cn.army59','ww2.cn.division38','ww2.cn.division180','ww2.jp.okada_detachment'],['潢河左岸','十五里铺','潢川城','二十里铺'],
       '第180师在城东及城内，第38师为西侧预备并于春河集接敌；公开资料只给具名地域，不给GIS阵位。','40页','WH_ZX_DABIE8')
    op('sep7_18_huangchuan','WH-Huangchuan-flank','movement','1938-09-15','day',['ww2.jp.division10','ww2.cn.division38'],['息县','潢川以北'],
       '日军迂回威胁后路，第38师分路北向出击牵制；不把第10师团和其冈田支队计作两个完整师团。','41页','WH_ZX_DABIE8')
    op('sep7_18_huangchuan','WH-Huangchuan-withdrawal','withdrawal','1938-09-17夜至18日','period',
       ['ww2.cn.army59','ww2.cn.division38','ww2.cn.division180','ww2.jp.division10'],['潢川','经扶','光山'],
       '17日继续巷战、夜间部分突围，18日奉命后撤；过程可以作为分析参考，开放推演不强制失城。','41页','WH_ZX_DABIE8')
    op('sep17_oct24_shawo','WH-Shawo-deployment','defense','1938-09月中旬，17日接敌前后的部署段','range',
       mountain+['ww2.cn.group2'],['沙窝','余家集','小界岭','达权店','金刚台'],
       '第71军负责左翼，第30／42军为右翼，第51军在达权店至金刚台；这是本段部署叙述，不能倒推四军同一开局实力。','33页')
    op('sep17_oct24_shawo','WH-Shawo-later-contact','combat','1938-09-19至24日','range',
       ['ww2.cn.division36','ww2.cn.division88','ww2.cn.division30','ww2.cn.division31','ww2.cn.division27','ww2.cn.division61','ww2.jp.division13','ww2.jp.division16'],
       ['沙窝','新店','磨盘山','小界岭'],'19日后具名师逐次投入与反击，不能据此全部放入17日初态。第61师行政上级待核。','33—34页')
    op('sep17_oct24_shawo','WH-Shawo-final-transfer','withdrawal','1938-10月中下旬，24日后日军越山','range',
       ['ww2.cn.army71','ww2.cn.army30','ww2.jp.division16'],['大别山北麓','随县','小界岭'],
       '信阳失守后北麓守军择机转移；防线持久作战与武汉整体撤离相联系，不等于单一要点一失全战结束。','35页')
    op(PHASE,'WH-N17-mountain','combat','1938-09-17至18日','range',mountain,
       ['余家集','显山','沙窝','达权店','金刚台'],'17日筱原支队进攻第71军，18日在沙窝与第30、71军激战；其余为该段部署。','33页')
    op(PHASE,'WH-N17-plain','defense','1938-09-17至18日','range',plain+['ww2.cn.army59'],
       ['潢川','西关','潢河'],'17日城防与次日撤退构成另一条同时存在的方向，不与沙窝合成一个据点。','41页','WH_ZX_DABIE8')
    op(PHASE,'WH-N17-city-hours','combat','1938-09-17，15时、17时许及夜23时','hour',plain,
       ['潢川西关'],'公开文献记下午攻城、17时许城墙被破以及23时后续部队抵达；不同动作分列，不把约时加工为准确分钟。','41页','WH_ZX_DABIE8')
    for child in ['ww2.cn.army71','ww2.cn.army30','ww2.cn.army42']:
        phases[PHASE]['relations'].append(dict(id='WH-N17-command-'+child.rsplit('.',1)[-1],kind='operational_command',
            parent_id='ww2.cn.group2',child_id=child,scope='仅该段山地作战指挥参考，不改写全会战行政隶属；未知直属及余部另列。',evidence=ev('33页')))
    p=phases[PHASE];p['evidence']+=ev('40—41页','WH_ZX_DABIE8')
    p['geographic_scope']=dict(center=dict(lat=32.0,lng=115.4),radius_km=100,kind='model_scope_limit',
        note='连接大别山北麓和潢川方向的粗计算包络估计，不是1938年阵地、地形测绘或城市中心的精确坐标。',evidence=copy.deepcopy(p['evidence']))
    p['execution_window']=dict(start='1938-09-17T00:00:00',end='1938-09-19T00:00:00',kind='model_scope_limit',
        note='按两个日级记录日离散化；零时仅作模型日期边界，不声称发令或全员实到。开放模式目标未达可继续，援军不自动补入。',evidence=copy.deepcopy(p['evidence']))
    d['coverage']['notes']+=[
        '1.2.0新增第五战区北线具名部队及四个分期；仍不是整个武汉会战完整部署。',
        '富金山、潢川、沙窝时期不同，累计身份不默认同日到场；第10师团与其冈田支队、16师团与筱原支队不得双计。',
        '第61师的上级、113／114师行政隶属以及源文个别团号未核，不推断为第71军永久建制；不采入末段相互不合的伤亡分项。']
    hi.validate_definition(d);return d


def northern_window(d):
    phase=next(p for p in d['phases']if p['id']==PHASE);units={u['id']:u for u in d['units']}
    mountain=['ww2.cn.army71','ww2.cn.army30','ww2.cn.army42','ww2.cn.army51']
    plain=['ww2.cn.division38','ww2.cn.division180'];blue=['ww2.jp.division10','ww2.jp.shinohara_detachment']
    actors=mountain+plain+blue
    def selected_ancestor(identity):
        parent=units[identity]['parent_id']
        while parent:
            if parent in actors:return parent
            parent=units[parent]['parent_id']
    rows={}
    for identity,u in units.items():
        target=selected_ancestor(identity)
        if identity=='ww2.cn.army59':target='ww2.cn.division38'
        if identity=='ww2.jp.division16':target='ww2.jp.shinohara_detachment'
        kind='actor' if identity in actors else 'covered_reference' if target else 'command_reference' if u['role']=='command' else 'outside_window'
        rows[identity]=dict(representation=kind,represented_by=target if kind=='covered_reference'else None,
            presence_basis='reported_action' if kind=='actor'else 'window_reference' if kind in ('covered_reference','command_reference')else 'prior_reference' if identity in ('ww2.cn.division113','ww2.cn.division114','ww2.cn.division61')else 'not_applicable',
            extent=('本窗口当地投入载荷；不宣称整军／师团满编或精确开局部署。'if kind=='actor'else '仅作来源／编制参考，不另计兵力；未知余部与其他战线不得视为零。'),
            opening='requires_explicit_estimate',operation_ids=[o['id']for o in phase['operations']if identity in o['unit_ids']],
            operational_reference=next((r['id']for r in phase['relations']if r['child_id']==identity),None),evidence=copy.deepcopy(u['evidence']))
    def goal(identity,label,team,ids,kind,ops,after=()):
        condition=dict(kind='preserve',minimum_fraction=None)if kind=='preserve'else dict(kind=kind,region=dict(center=dict(lat=None,lng=None),radius_km=None),minimum_personnel=None)
        return dict(id=identity,label=label,team=team,unit_ids=ids,after=dict(mode='all',node_ids=list(after)),
            not_before_seconds=0,condition=condition,hold_seconds=0 if kind=='preserve'else None,latch=kind!='control',operation_ids=ops,assumption=NOTE)
    goals=[goal('red_mountain','保持山地迟滞方向','red',mountain,'control',['WH-N17-mountain']),
           goal('red_plain','保持潢川撤退通道','red',plain,'control',['WH-N17-plain']),
           goal('red_preserve','双方向保存投入兵力','red',mountain+plain,'preserve',['WH-N17-mountain','WH-N17-plain'],['red_mountain','red_plain']),
           goal('blue_mountain','突破山地纵深','blue',[blue[1]],'reach',['WH-N17-mountain']),
           goal('blue_plain','威胁平原后路','blue',[blue[0]],'reach',['WH-N17-plain'])]
    estimates={}
    for identity in actors:
        is_mountain=identity in mountain or identity==blue[1]
        estimates[identity]=dict(personnel=dict(minimum=2000 if units[identity]['echelon']in ('师','支队')else 5000,maximum=10000 if units[identity]['echelon']in ('师','支队')else 22000),
            equipment={k:dict(minimum=0,maximum=100 if k=='transport'else 50)for k in ('armor','artillery','air_defense','engineer','transport')},
            position=dict(center=dict(lat=31.7 if is_mountain else 32.1,lng=115.7 if is_mountain else 115.1),radius_km=35,assumption=NOTE+' 区域中心和35km半径是方向包络估计，不是部队阵位。'),
            role='infantry',direct_range_m=dict(minimum=100,maximum=1800),assumption=NOTE)
    value=dict(format=cw.FORMAT,id=WINDOW,version='1.0.0',label='武汉北线：9月17—18日山地／潢川并行窗口',battle=WH,
        historical_initial=dict(profile_id=d['id'],version=d['version'],definition_hash=hi.digest(d)),start_phase_id=PHASE,phase_ids=[PHASE],
        bounds=dict(start='1938-09-17T00:00:00',end='1938-09-19T00:00:00',kind='model_scope_limit',note=phase['execution_window']['note']),units=rows,
        sectors=[dict(id='mountain',label='大别山山地迟滞',position=None,unit_ids=mountain+[blue[1]],operation_ids=['WH-N17-mountain'],evidence=evidence('WH_ZX_DABIE7','33页')),
                 dict(id='plain',label='潢川河流与后路',position=None,unit_ids=plain+[blue[0]],operation_ids=['WH-N17-plain'],evidence=evidence('WH_ZX_DABIE8','40—41页'))],
        milestones=[dict(operation_id=o['id'],phase_id=PHASE,policy='reference_only')for o in phase['operations']],
        limitations=NOTE+' 仅北线两个方向；未纳入长江南北其他战场。16师团只由已记前出支队表示，余部不补造；10师团载荷包含冈田支队，不额外复制。',
        parameter_estimates=dict(version='campaign-estimates-1',historically_calibrated=False,assumption=NOTE,
            area=dict(center=phase['geographic_scope']['center'],radius_km=100,assumption=NOTE,evidence=phase['evidence']),actors=estimates,
            goal_template=dict(version='campaign-objectives-1',nodes=goals,outcomes=dict(red=dict(mode='all',node_ids=['red_preserve']),blue=dict(mode='any',node_ids=['blue_mountain','blue_plain'])),elimination_ends=False,assumption=NOTE)))
    cw.validate_definition(value,hi._materialize(d,PHASE)['historical_initial']);return value


def wjl_window(d):
    value=copy.deepcopy(cw.load('WJL-oct6-10','1.5.0'));value['version']='1.6.0'
    value['label']='万家岭：10月6—10日地面会战 · 有期军级统计参照'
    value['historical_initial']=dict(profile_id=d['id'],version=d['version'],definition_hash=hi.digest(d))
    value['limitations']+=' 1.6.0仅增接军级有期统计；第66军7—12日和第74军9月30日至10月15日均不与此窗口同期间，不将其损失当本窗口定额。'
    cw.validate_definition(value,hi._materialize(d,'oct6_orders')['historical_initial']);return value


def bounded_northern_window(d):
    value=northern_window(d);value['version']='1.1.0'
    value['label']+=' · 目标按方向约束'
    value['parameter_estimates']['goal_regions']={}
    for node in value['parameter_estimates']['goal_template']['nodes']:
        if 'region' not in node['condition']:continue
        mountain=node['id'].endswith('mountain')
        value['parameter_estimates']['goal_regions'][node['id']]=dict(
            center=dict(lat=31.7 if mountain else 32.1,lng=115.7 if mountain else 115.1),radius_km=35,
            assumption=NOTE+' 此35km方向包络与单位估计地域一致；约束整个目标圆，不是历史阵地测绘。')
    value['limitations']+=' 1.1.0增加目标地域方向约束，避免山地目标错放潢川方向；旧1.0.0及其已生成配置保持原样。'
    cw.validate_definition(value,hi._materialize(d,PHASE)['historical_initial']);return value


def binding(d,old):
    value=copy.deepcopy(old);value['initial_definition_hash']=hi.digest(d)
    for row in value['phases'].values():
        if 'guidance'in row:row['source_hashes']={i:hi.digest(d['sources'][i])for i in row['source_hashes']}
    if d['id']=='AJ06-wuhan':
        e=evidence('WH_ZX_DABIE7','33页山地部署与17—18日接敌')+evidence('WH_ZX_DABIE8','40—41页潢川部署与17—18日过程')
        value['phases'][PHASE]=dict(guidance=dict(team='red',profile='delay',objective_label='北线两方向迟滞与保存投入兵力',
            scope_note='山地与潢川分别设置地域与目标。数值与坐标须说明估计；历史失城不是开放推演必然结局。',
            not_covered=['完整武汉会战部署','未知机关直属及余部','历史人数装备库存和效能标定'],evidence=e),
            source_hashes={i:hi.digest(d['sources'][i])for i in {r['source_id']for r in e}})
    return value


def canonical_outputs(wjl,wh):
    """Synchronize sourced facts for ordinary corpus retrieval, without changing other battles."""
    data=ROOT/'data/anti_japanese_war'
    records=json.loads((data/'scenarios.json').read_text())
    bibliography=json.loads((data/'sources.json').read_text())
    by_id={s['id']:s for s in records['scenarios']}
    def append_unique(rows,key,row):
        old=next((r for r in rows if r.get(key)==row[key]),None)
        if old is not None:
            if ('detail_group'in row and 'detail_group'not in old
                    and old=={k:v for k,v in row.items()if k!='detail_group'}):
                old['detail_group']=row['detail_group']
            if old!=row:raise ValueError('Existing canonical evidence differs: '+row[key])
        else:rows.append(row)
    for key in ('WH_ZX_DABIE7','WH_ZX_DABIE8'):
        source=wh['sources'][key]
        row=dict(title=source['title'],publisher=source['publisher'],url=source['url'],
            supports='武汉北线富金山、潢川及沙窝—小界岭分期的具名单位、部署方向与行动；不证明逐单位实到数。',
            evidence_type='公开PDF相关原页视觉核读及文本对照',accessed='2026-11-03',
            original_archive_examined=False,caveat=source['limitations'])
        if key in bibliography['sources'] and bibliography['sources'][key]!=row:
            raise ValueError('Existing canonical source differs: '+key)
        bibliography['sources'][key]=row
    guo=bibliography['sources']['A_WJL_GUO']
    detail=' 2026-11-03增核印刷124—125页原图及脚注7878203、7878204；只引用论文所载军级分期参战和损失统计，未声称辨读馆藏原表。'
    if detail not in guo['caveat']:guo['caveat']+=detail
    if '124—125' not in guo['evidence_type']:guo['evidence_type']+='；增核印刷124—125页'
    s=by_id['AJ07']
    for p in wjl['phases']:
        for r in p.get('measurements',[]):
            if r['id'] not in {'WJL-M-66-participants','WJL-M-66-casualties','WJL-M-74-participants','WJL-M-74-losses'}:continue
            name='第66军' if '66-'in r['id']else '第74军'
            metric='期间参战官兵'if r['statistic']=='reported_strength'else '死伤及生死不明合计'if '74-'in r['id']else '期间伤亡合计'
            append_unique(s['figures'],'figure_key',dict(figure_key=r['id'],side='中国',metric=name+metric+'（人）',
                value=r['quantity']['lower'],qualifier='',scope=r['date']['label']+'；'+r['population'],
                note='不是10月6日开局现员、逐师分配额或本窗口固定损失；'+r['limitations'],sources=['A_WJL_GUO'],
                evidence_status='published_account',source_locator={'A_WJL_GUO':'；'.join(e['locator']for e in r['evidence'])}))
    warning='第66军7—12日和第74军9月30日至10月15日统计期间不同；后者含生死不明，不直接比较损失率，不作为10月6—10日逐日扣兵或开局兵额。'
    if warning not in s['uncertainties']:s['uncertainties'].append(warning)
    s=by_id['AJ06'];old_ids={u['id']for u in hi.definition(WH,'1.1.0')['units']}
    for key in ('WH_ZX_DABIE7','WH_ZX_DABIE8'):
        if key not in s['sources']:s['sources'].append(key)
    def locations(evidence):
        return {key:'；'.join(e['locator']for e in evidence if e['source_id']==key)for key in dict.fromkeys(e['source_id']for e in evidence)}
    for u in wh['units']:
        if u['id']in old_ids:continue
        description=('指挥参考，不生成为步兵或单独加入兵额；'if u['role']=='command'else '累计参战身份，须按所选阶段核对实际投入；')
        description+=('公开编制上级：'+u['parent_id']+'；'if u['parent_id']else '行政上级未在此补造；')
        description+='逐单位人数、分类装备和精确阵位未知。作战指挥配属不自动等于永久建制。'
        append_unique(s['forces'],'historical_unit_id',dict(historical_unit_id=u['id'],detail_group='北线分期参战单位与指挥参考',side='中国'if u['team']=='red'else '日本',
            unit=u['name'],description=description,sources=list(locations(u['evidence'])),evidence_status='published_account',source_locator=locations(u['evidence'])))
    precisions={'range':'日期范围','period':'时段','day':'日','hour':'小时'}
    for p in wh['phases']:
        for op in p.get('operations',[]):
            if not op['id'].startswith('WH-'):continue
            append_unique(s['events'],'event_key',dict(event_key=op['id'],date=op['date']['label'],time_label=op['date']['label'],
                precision=precisions[op['date']['precision']],event=op['description'],sources=list(locations(op['evidence'])),
                evidence_status='published_account',source_locator=locations(op['evidence'])))
    # Preserve the broad opening context and the final withdrawal, with the
    # dated northern details between them. Array order is also used by source
    # replay; appending September actions after October would reverse history.
    order=['WH-Fujin-deployment','WH-Huangchuan-deployment','WH-Fujin-reinforcement',
        'WH-Fujin-withdrawal','WH-Huangchuan-flank','WH-Shawo-deployment',
        'WH-N17-mountain','WH-N17-plain','WH-N17-city-hours','WH-Huangchuan-withdrawal',
        'WH-Shawo-later-contact','WH-Shawo-final-transfer']
    details={e['event_key']:e for e in s['events']if e.get('event_key')in order}
    context=[e for e in s['events']if e.get('event_key')not in details]
    end=next(i for i,e in enumerate(context)if e['date']=='1938-10-24')
    s['events']=context[:end]+[details[key]for key in order]+context[end:]
    for warning in [
        '北线新增富金山、潢川、沙窝—小界岭及9月17—18日并行范围；不同日期部队不全部装入同一开局。',
        '第10师团与冈田支队、第16师团与筱原支队不能重复计算；第61、113、114师的行政上级未据二手叙述强行确定。',
        '两篇大别烽烟印刷刊期为2025年第7、8期，上传路径月份不能当作期号；原文个别番号及末段伤亡分项不合处未作数值事实。',
        '沙窝、潢川的具名地域尚未配准1938年战图；计算范围的中心和半径是显式估计，不是各部队的精确阵位。']:
        if warning not in s['uncertainties']:s['uncertainties'].append(warning)
    return {data/'scenarios.json':records,data/'sources.json':bibliography}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');args=parser.parse_args()
    a,b=wanjialing(),wuhan();values={hi.DATA_ROOT/'AJ07-wanjialing/1.5.0.json':a,hi.DATA_ROOT/'AJ06-wuhan/1.2.0.json':b,
        cw.DATA_ROOT/'WJL-oct6-10/1.6.0.json':wjl_window(a),cw.DATA_ROOT/WINDOW/'1.0.0.json':northern_window(b),
        cw.DATA_ROOT/WINDOW/'1.1.0.json':bounded_northern_window(b)}
    for path,value in values.items():
        if path.exists():
            if json.loads(path.read_text())!=value:raise SystemExit('Do not overwrite an existing source version: '+str(path))
        elif args.check:raise SystemExit('Version missing: '+str(path))
        else:path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    path=ROOT/'data/historical_objective_bindings.json';pins=json.loads(path.read_text())
    for d,base in [(a,'1.4.0'),(b,'1.1.0')]:
        versions=pins['profiles'][d['id']];new=binding(d,versions[base])
        if d['version']in versions:
            if versions[d['version']]!=new:raise SystemExit('Existing goal pin differs')
        elif args.check:raise SystemExit('Missing goal pin')
        else:versions[d['version']]=new
    if not args.check:path.write_text(json.dumps(pins,ensure_ascii=False,indent=2)+'\n')
    for path,value in canonical_outputs(a,b).items():
        if json.loads(path.read_text())==value:continue
        if args.check:raise SystemExit('Canonical evidence needs synchronization: '+str(path))
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    print('Wuhan northern sources/window and dated Wanjialing army statistics consistent; old versions/default unchanged')


if __name__=='__main__':main()
