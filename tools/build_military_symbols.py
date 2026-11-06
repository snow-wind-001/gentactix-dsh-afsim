"""Rebuild the small application SVG vocabulary; source scans stay local references."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
# All strokes are project-drawn, normalized to 24 units; paths contain no text/fonts.
ROWS=[
 ('unknown','未知兵种','单位','point','M9 8a3 3 0 0 1 6 0c0 2-3 2-3 5M12 17h.01',[]),
 ('infantry','步兵编组','单位','point','M5 5h14v14H5ZM6 6l12 12M18 6 6 18',['mil-069']),
 ('armor','装甲编组','单位','point','M3 5h18v14H3ZM8 9h8a3 3 0 0 1 0 6H8a3 3 0 0 1 0-6',['mil-140']),
 ('artillery','炮兵与间瞄火力','单位','point','M4 5h16v14H4ZM12 10a2 2 0 1 0 0 4a2 2 0 1 0 0-4',[]),
 ('machine-gun','机枪分队','单位','point','M5 7h14v4H5ZM12 11v5M7 20l5-7 5 7',[]),
 ('mortar','迫击炮分队','单位','point','M7 4l8 14M5 5l4-2M12 19h8M15 17l4-5',[]),
 ('anti-tank','反坦克分队','单位','point','M4 5h16v14H4ZM7 16l10-8M11 8h6v6',[]),
 ('rocket','火箭炮分队','单位','point','M4 17h16M6 13l5-8M11 13l5-8M16 13l5-8M7 20h.01M17 20h.01',[]),
 ('motorized','摩托化步兵','单位','point','M4 4h16v13H4ZM6 6l12 9M18 6 6 15M7 20h.01M17 20h.01',[]),
 ('mechanized','机械化步兵','单位','point','M4 3h16v13H4ZM6 5l12 9M18 5 6 14M7 19h10a2 2 0 0 1 0 4H7a2 2 0 0 1 0-4',[]),
 ('recon','侦察分队','单位','point','M4 5h16v14H4ZM6 14l4-5h4l4 5M8 14h.01M16 14h.01',[]),
 ('air-defense','防空编组','单位','point','M4 5h16v14H4ZM7 15a5 5 0 0 1 10 0M12 13V8M10 10l2-2 2 2',['mil-051']),
 ('engineer','工兵编组','单位','point','M4 5h16v14H4ZM7 15V9h10v6M7 12h10',[]),
 ('logistics','运输保障','单位','point','M3 7h12v10H3ZM15 11h4l3 3v3h-7M6 17v2M18 17v2',['mil-142']),
 ('signal','通信编组','单位','point','M4 5h16v14H4ZM14 7l-5 6h6l-5 5',['mil-058']),
 ('cavalry','骑兵编组','单位','point','M4 5h16v14H4ZM7 16l10-8',[]),
 ('medical','医疗保障（应用图例）','单位','point','M4 5h16v14H4ZM7 12h3l2-4 2 8 2-4h2',[]),
 ('aircraft','航空力量','装备','point','M12 3v17M12 9l-9 5v2l9-3 9 3v-2ZM12 17l-4 4h8Z',['mil-024']),
 ('naval','水面舰艇','装备','point','M4 12h16l-3 7H7ZM8 12V8h8v4M12 8V4M10 5h5',['mil-104']),
 ('hq','指挥所','设施','point','M6 22V3h15v9H6',['mil-199']),
 ('observation','观察点','设施','point','M3 12s4-6 9-6 9 6 9 6-4 6-9 6-9-6-9-6ZM12 9v6M9 12h6',[]),
 ('supply-ammo','弹药补给点','设施','point','M4 4h16L12 21ZM9 7h6v4H9Z',['mil-045']),
 ('supply-fuel','油料补给点','设施','point','M8 4h8v16H8ZM8 8h8M8 16h8M16 7h3v9h2',['mil-046']),
 ('supply-depot','综合补给点','设施','point','M3 10l9-6 9 6v10H3ZM8 20V12h8v8',['mil-001']),
 ('bridge','桥梁与渡口','设施','point','M2 16h20M4 20V9M20 20V9M4 12c5-7 11-7 16 0M8 10v6M16 10v6',['add-002']),
 ('camp','集结点','设施','point','M3 20 12 4l9 16ZM9 20l3-7 3 7',[]),
 ('attack-axis','进攻方向','路线','line','M4 20 18 6M9 6h9v9',['mil-185']),
 ('retreat-route','转移与撤退路线','路线','line','M4 6h9c8 0 8 13 0 13H4M8 15l-4 4 4 4',['mil-172']),
 ('supply-route','补给运输路线','路线','line','M3 12h18M16 7l5 5-5 5',['mil-066']),
 ('defensive-line','防御线','路线','line','M2 15h20M5 15V9M12 15V9M19 15V9',['mil-194']),
 ('boundary','分界线','路线','line','M3 4l6 5 6 6 6 5',[]),
 ('obstacle','障碍地段','路线','line','M2 15h20M4 15l3-6 3 6M14 15l3-6 3 6',['add-001']),
 ('assembly-area','集结地域','地域','area','M4 5h16v14H4ZM8 9h8v6H8Z',['mil-180']),
 ('objective-area','目标地域','地域','area','M3 3h18v18H3ZM12 7v10M7 12h10',[]),
 ('minefield','雷场（标注，不参与解算）','地域','area','M3 3h18v18H3ZM7 7l4 4M11 7l-4 4M13 13l4 4M17 13l-4 4',[]),
]

def build():
    source=ROOT/'data/military-symbols-v2/core_catalog.json'
    refs=json.loads(source.read_text()) if source.exists() else json.loads((ROOT/'gentactix/military_symbol_reference.json').read_text())
    lookup={x['id']:x for x in refs}
    symbols=[]
    for ident,label,category,geometry,path,reference_ids in ROWS:
        symbols.append({'id':ident,'label':label,'category':category,'geometry':geometry,'path':path,
                        'anchor':[6,22] if ident=='hq' else [12,12],
                        'stroke_width':1.65,'source_ids':reference_ids,'design':'project_vector_redraw',
                        'meaning':'应用军事标图图例；非现行标准认证，不推定国别、年代、装备型号或历史部署'})
    target=ROOT/'gentactix/military_symbols.json'
    data={'version':'military-symbols-1','symbols':symbols,
          'unit_profile_symbols':{'command':'hq','transport':'logistics','rail':'logistics','medical':'medical','signal':'signal','engineer':'engineer','aviation':'aircraft','naval':'naval','air_defense':'air-defense','anti_tank':'anti-tank','rocket':'rocket','sp_artillery':'artillery','towed_artillery':'artillery','mortar':'mortar','mechanized':'mechanized','motorized':'motorized','armor':'armor','recon':'recon','machine_gun':'machine-gun','infantry':'infantry'},
          'reference':{'independent_examples':256,'svg_files':24247,'all_semantically_verified':False,
                       'scope':'256个独立示例；自动笔画组不能作为已命名军标。原扫描库本地按需读取，不随包发行。'}}
    target.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    # Metadata only: no original book paths or scanned page content in the public bundle.
    fields=['id','file','name_zh','category','source_pdf_page','source_figure','method','anchor_xy','anchor_verified_for_geographic_placement','limitations']
    (ROOT/'gentactix/military_symbol_reference.json').write_text(json.dumps([{k:r.get(k) for k in fields} for r in refs],ensure_ascii=False,indent=2)+'\n')
    print('Built',len(symbols),'application symbols and',len(refs),'reference metadata records')

if __name__=='__main__':build()
