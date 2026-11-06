<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { api } from '../api';
import type { MissionState, CounterfactualResult, CampaignState, CampaignPlanState, CampaignLifecycleState, Snapshot } from '../types';
import PhaseContinuation from './PhaseContinuation.vue';
import CampaignObjectives from './CampaignObjectives.vue';
import CampaignLifecycle from './CampaignLifecycle.vue';
const props = defineProps<{ mission: MissionState; campaign?:CampaignState; plan?:CampaignPlanState; lifecycle?:CampaignLifecycleState; sessionId: string; busy: boolean; currentTime?:string;modelEstimated?:boolean;readiness?:Snapshot['resource_readiness'] }>();
const emit=defineEmits<{snapshot:[Snapshot];busy:[boolean]}>();
const actionLabel=(action:string)=>({hold:'待命',move:'移动',fire:'攻击',resupply:'补给',sabotage:'破袭交通',repair:'修复交通',conceal:'隐蔽',air_support:'航空支援',accept:'接收',capture:'接近受降',bombard:'炮击',suppress:'火力压制',fortify:'构筑',build_bridge:'架桥/修桥',demolish:'破坏桥梁',repair_equipment:'装备维修',recon:'侦察',restore_comms:'恢复联络'} as Record<string,string>)[action] ?? action;
const pending = ref(false); const error = ref(''); const comparison = ref<CounterfactualResult | null>(null);
const owner=computed(()=>props.mission.definition.objective_team??'red');
const objectiveDriven=computed(()=>props.mission.definition.termination_mode==='objectives');
const splitSupply=computed(()=>props.mission.ledger.some(r=>r.food_received!==undefined));
const ownerLabel=computed(()=>owner.value==='red'?'红方':'蓝方');
const soloPlan=computed(()=>!!props.mission.definition.campaign_plan&&Object.values(props.mission.definition.campaign_plan.outcomes).some(r=>!r.node_ids.length));
const historicalPhase=computed(()=>{
 const initial=props.mission.definition.historical_calculation?.initial;
 return initial?.definition.phases.find(p=>p.id===initial.phase_id);
});
const outsideSourceWindow=computed(()=>{
 const end=historicalPhase.value?.execution_window?.end;
 return objectiveDriven.value&&!!end&&!!props.currentTime&&Date.parse(props.currentTime.replace(' ','T')+'Z')>=Date.parse(end+'Z');
});
const scopeLabel=computed(()=>props.plan?'会战多方向目标':props.campaign?'阶段联合目标':props.mission.definition.historical_calculation?'历史局部目标':props.mission.definition.id.startsWith('HS-')?'合成演习目标':'局部教学');
const campaignGoals=[['town_control','据点控制'],['relief_denied','阻援区域控制'],['force_preserved','有生力量保存']] as const;
const declaredGross=computed(()=>props.mission.ledger.length>0&&props.mission.ledger.every(r=>r.delivery_basis==='declared_gross_estimate'));
const canCompare=computed(()=>Array.isArray(props.mission.definition.initial_state?.[owner.value+'_units' as 'red_units'|'blue_units']));
const canContinueObjective=computed(()=>props.mission.definition.id.startsWith('HO-')&&!objectiveDriven.value&&props.mission.reason==='截止回合目标未达成');
async function continueObjective(){
 pending.value=true;error.value='';emit('busy',true);
 try{const basis=await api.phaseCandidates(props.sessionId);emit('snapshot',await api.objectiveBranch(props.sessionId,basis.world_version));}
 catch(e){error.value=String(e);}finally{pending.value=false;emit('busy',false);}
}
watch(() => [props.sessionId, props.mission.turn], () => { comparison.value = null; error.value = ''; });
async function compareHold() {
  if(!canCompare.value){error.value='缺少初始方别名单，无法确定待命对照的单位。';return;}
  pending.value = true; error.value = '';
  try {
    const initial=props.mission.definition.initial_state!;
    const ownNames=new Set(initial[owner.value+'_units' as 'red_units'|'blue_units']?.map(u=>u.name));
    comparison.value = await api.counterfactual(props.sessionId, { turn: props.mission.turn, mode: 'mission',
      orders: props.mission.last_orders.filter(o => !ownNames.has(o.unit)) });
  } catch (e) { error.value = String(e); }
  finally { pending.value = false; }
}
</script>
<template>
  <section class="mission-panel" :aria-label="scopeLabel" data-testid="mission-panel">
    <div class="mission-heading"><strong>{{scopeLabel}} · {{ mission.status === 'active' ? '进行中' : '已结算' }}</strong><span>{{objectiveDriven?'第 '+mission.turn+' 轮 · 按目标完成':mission.turn+' / '+mission.definition.deadline_turn+' 回合'}} · {{ mission.definition.time_step }}/轮</span></div>
    <p v-if="plan" data-testid="mission-objective-owner">{{soloPlan?'按参演方转移目标结算，不因对方为空自动获胜；不按参考轮数自动结束。':'双方按各自目标图结算，同时达标判为平局；不按参考轮数自动结束。'}}<template v-if="mission.definition.campaign_plan?.elimination_ends">{{soloPlan?'转移部队全部失能时无获胜方。':'一方全军失能也会触发结算。'}}</template></p>
    <p v-else data-testid="mission-objective-owner">目标方：{{ownerLabel}} · {{objectiveDriven?'目标连续达成或目标方无可用单位后结算，不按参考轮数自动结束':campaign?'联合条件在截止回合结算':'对应已冻结的局部判定条件'}}</p>
    <p v-if="outsideSourceWindow" class="muted" role="status" data-testid="outside-source-window">已到史料参考窗之外，继续按当前编制与资源推演；后续援军不会自动补入，结果属于反事实延伸。</p>
    <template v-if="canContinueObjective"><p>可保留本局记录，基于当前人员、装备、库存和时间创建不设自动时限的分支。原限时结果保留，原命令队列清空后重新下令。</p><button data-testid="continue-by-objectives" :disabled="busy||pending" @click="continueObjective">保留本局，按目标完成继续</button></template>
    <p v-if="error&&canContinueObjective" class="bad" role="alert">{{error}}</p>
    <p v-if="historicalPhase" class="muted" data-testid="historical-process-coverage">{{plan?'初始资料阶段':'当前阶段'}}：{{historicalPhase.label}}。<template v-if="plan">当前实体在同一世界按目标持续推进；这不证明后续历史部署和损失已标定。旧阶段续接入口暂不迁移目标图。</template><template v-else>{{mission.status==='completed'?'本阶段已结算，不等于整场战役完成。':'仅计算本阶段。'}}{{objectiveDriven?'本阶段可持续推进；切换阶段仍须使用已验证续接配置。':'连续计算须使用阶段续接；普通新建使用新的初态。'}}</template></p>
    <PhaseContinuation v-if="historicalPhase&&mission.status==='completed'&&!plan" :session-id="sessionId" :busy="busy" @snapshot="emit('snapshot',$event)" @busy="emit('busy',$event)" />
    <details v-if="readiness" data-testid="resource-readiness"><summary>随队资源可持续时间</summary><p class="muted">{{readiness.scope}} · {{readiness.horizon_kind==='rolling_plan'?'滚动规划未来':'当前窗口还剩'}}{{readiness.remaining_hours.toFixed(1)}}小时</p>
     <div class="table-scroll"><table><thead><tr><th>单位</th><th>待命粮食/小时</th><th>行军粮食/小时</th><th>弹药火力/分钟</th><th>炮击/分钟</th></tr></thead><tbody><tr v-for="r in readiness.units" :key="r.unit"><td>{{r.unit}}<small v-if="r.food_on_hand_kg!==undefined" data-testid="unit-ration-mass"><br>随队{{r.food_on_hand_kg?.toFixed(1)}}／携行容量{{r.food_capacity_kg?.toFixed(1)}} kg<br>{{r.ration_kg_per_person_day}} kg／人日（估计）</small></td><td>{{r.food_hold_hours?.toFixed(1)??'未配置按时耗粮'}}</td><td>{{r.food_move_hours?.toFixed(1)??'未知'}}</td><td>{{r.fire_work_minutes.toFixed(1)}}</td><td>{{r.artillery_minutes.toFixed(1)}}</td></tr></tbody></table></div>
    </details>
    <CampaignLifecycle v-if="lifecycle&&mission.definition.campaign_lifecycle" :configuration="mission.definition.campaign_lifecycle" :state="lifecycle" :goals="mission.definition.campaign_plan" />
    <CampaignObjectives v-if="plan&&mission.definition.campaign_plan" :configuration="mission.definition.campaign_plan" :state="plan" :required-turns="mission.definition.required_turns" />
    <ul v-else-if="campaign" class="campaign-goals" data-testid="campaign-goals"><li v-for="[key,label] in campaignGoals" :key="key" :class="{met:campaign.objective[key]}">{{label}}：{{mission.turn===0?'尚未运行':campaign.objective[key]?'满足':'未满足'}}</li></ul>
    <p><b>目标：</b>{{ mission.definition.goal }} <span v-if="mission.reason"> · {{ mission.reason }}<template v-if="mission.winner">（{{ mission.winner === 'red' ? '红方' : '蓝方' }}）</template></span></p>
    <p class="muted">目标圈与出口是示意位置，地图背景不构成已核验的战术地形。</p>
    <details v-if="mission.definition.assumptions"><summary>资料范围与建模假设</summary><p class="muted">{{ mission.definition.assumptions }}</p></details>
    <details><summary>目标进度、补给账与重放凭据</summary>
      <p v-if="plan">参演方按目标图连续达标要求结算；旧据点圈仅供原参数对照。</p>
      <p v-else-if="!campaign">连续满足 {{ mission.progress }} 轮 · 交通完好度 {{ mission.network }} · 组织存续 {{ mission.organization }}</p>
      <p v-else>三项条件须同时满足；占领据点不会提前结束当前计算窗口。</p>
      <div class="table-scroll" tabindex="0" role="region" aria-label="单位补给收支表" data-testid="mission-resource-table"><table><thead><tr><th>编组</th><th>行动</th><th>线路（回合开始）</th><th>{{splitSupply?'质量当量':'到货'}}</th><th v-if="splitSupply">粮食到货</th><th v-if="splitSupply">弹药到货</th><th>粮食消耗</th><th>弹药消耗</th><th>粮食余额</th><th>弹药余额</th></tr></thead><tbody><tr v-for="r in mission.ledger" :key="r.unit"><td>{{ r.unit }}</td><td>{{ actionLabel(r.action) }}</td><td>{{ r.supply_status }}</td><td>{{ r.delivery }}</td><td v-if="splitSupply">{{r.food_received??'未知'}}</td><td v-if="splitSupply">{{r.ammo_received??'未知'}}</td><td>{{r.food_spent??'未知'}}</td><td>{{r.ammo_spent??'未知'}}</td><td>{{ r.food_after }}</td><td>{{ r.ammo_after }}</td></tr></tbody></table></div>
      <p class="muted" data-testid="mission-resource-source">{{!mission.ledger.length?'尚无本轮已提交收支记录。':splitSupply?(modelEstimated?'DSH分类到货估计，收支已核对；':'AFSIM分类到货回执；')+'粮弹分别扣仓、共用载重；质量当量不是各类到货量，弹药工作量不是实弹发数。':modelEstimated?(declaredGross?'DSH估计收支已核对；到货为声明的毛到货，每份含一单位粮食和弹药，非AFSIM运输回执或真实吨数。':'旧DSH库存变化估计；到货按粮食净增加量展示，不能等同运输吞吐。'):'库存单位为教学工作量，非真实弹药发数；每份到货含一单位粮食和一单位弹药。'}}</p>
      <p class="hash">规则 {{ mission.version }} · 定义 {{ mission.definition_hash }}<br>初态 {{ mission.initial_hash }}</p>
      <button :disabled="busy || pending || mission.turn < 1 || !canCompare" @click="compareHold">{{ pending ? '正在重算…' : '对照上一轮：'+ownerLabel+'全部原地待命' }}</button>
      <p v-if="modelEstimated" class="muted">本对照调用DSH重新估计过程，具有随机性，不构成确定因果结论。</p>
      <p class="muted">保持另一方命令和决策前态势不变，只替换{{ownerLabel}}命令；对照结果不写回战局。</p>
      <p v-if="error" class="bad" role="alert">{{ error }}</p>
      <div v-if="comparison" class="table-scroll"><table><thead><tr><th>指标</th><th>原决策</th><th>待命对照</th><th>差值</th></tr></thead><tbody><tr v-for="m in comparison.metrics" :key="m.metric"><td>{{ m.metric }}</td><td>{{ m.factual }}</td><td>{{ m.alternative }}</td><td>{{ m.delta }}</td></tr></tbody></table></div>
    </details>
  </section>
</template>
<style scoped>
.mission-panel { flex: 0 0 auto; margin: 8px 12px; padding: 12px 16px; border: 1px solid #57655e; border-left: 3px solid #c9b47d; border-radius: 6px; background: #192831; font-size: 13px; max-height: 32vh; overflow: auto; }
.mission-heading { position: sticky; top: -12px; z-index: 1; background: #192831; padding: 8px 0; display: flex; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
p { margin: 7px 0; line-height: 1.5; } summary { cursor: pointer; } .hash { overflow-wrap: anywhere; font-size: 11px; color: #a6b6c2; }
.table-scroll { overflow-x: auto; } table { width: 100%; border-collapse: collapse; white-space: nowrap; } td, th { padding: 6px 10px; text-align: left; border-bottom: 1px solid #344651; }
.campaign-goals{display:flex;flex-wrap:wrap;gap:8px 20px;list-style:none;padding:0;color:#e0ba76}.campaign-goals .met{color:#85cfa9}
@media(max-width: 700px) { .mission-panel { margin: 6px; padding: 10px; max-height: 40vh; } }
</style>
