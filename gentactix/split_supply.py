"""Frozen independent stock contract; reference checks never allocate cargo."""
import math

VERSION='split-stocks-1'


def validate_config(cfg):
    if not isinstance(cfg,dict) or set(cfg)!={'version','food_mass_share','priority','assumption'} or cfg['version']!=VERSION:
        raise ValueError('分类粮弹配置字段或版本非法')
    share=cfg['food_mass_share']
    if type(share) not in (int,float) or not math.isfinite(share) or not .01<=share<=.99:
        raise ValueError('分类粮弹质量份额须为0.01至0.99')
    if cfg['priority'] not in ('food','ammo') or not isinstance(cfg['assumption'],str) or not cfg['assumption'].strip() or len(cfg['assumption'])>4000:
        raise ValueError('分类粮弹优先级及估计依据非法')


def configuration(world):
    return world.get('mission',{}).get('definition',{}).get('supply_distribution')


def equivalent(cfg, food, ammo):
    """Mass-equivalent legacy package units, not food received or item counts."""
    return food*cfg['food_mass_share']+ammo*(1-cfg['food_mass_share'])


def validate_state(world):
    cfg=configuration(world)
    for node in world.get('supply_nodes',[]):
        goods=node.get('commodities')
        if not cfg:
            if goods is not None:raise ValueError('未启用分类粮弹却出现分类库存')
            continue
        validate_config(cfg)
        if not isinstance(goods,dict) or set(goods)!={'food','ammo'} or any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in goods.values()):
            raise ValueError('分类粮弹库存缺失或非法')
        if not math.isclose(node['stock'],equivalent(cfg,goods['food'],goods['ammo']),rel_tol=0,abs_tol=1e-6):
            raise ValueError('分类粮弹库存与质量当量不一致')


def instruction(cfg,*,scheduled=False):
    return ('分类粮弹模型split-stocks-1：仓库commodities.food/ammo分别记账；初态由旧包单位拆为各stock份，'
        '后续独立扣减，未运输的另一类留在仓库，不丢弃或凭空生成。'
        f'粮食质量份额={cfg["food_mass_share"]}，弹药份额={1-cfg["food_mass_share"]}；均为显式估计。'
        'stock和delivery仅是质量当量（food*粮份额+ammo*弹份额），不是各类到货量。'
        'resource_ledger.version=dsh-resource-ledger-2，每个单位额外提交food_received、ammo_received；'
        '期末粮弹分别=期初+(对应received-spent)/scale。'
        + ('启用定时补给时，food_spent逐段计算，各到货时点前不得透支；每类按该时点空余与周期服务上限核对，共享仓库装卸和运输吨位。' if scheduled else
           'food_spent按已启用耗粮规则，轮末弹药不能支付本轮射击。每类到货不超过本类轮初容量及行动上限（待命2*scale，主动补给8*scale）；两类共用运输载重、路线和仓库。') +
        'supply_nodes更新须同时含commodities两类余额和相符stock；分类燃油炮弹等仍单独记账。'
        '满弹不阻止补粮，满粮不阻止补弹。依据：'+cfg['assumption'])
