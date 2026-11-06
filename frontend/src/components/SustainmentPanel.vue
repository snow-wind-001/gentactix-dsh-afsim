<script setup lang="ts">
import type {SustainmentView} from '../types';
defineProps<{value:SustainmentView}>();
const teams=['red','blue'] as const;
const number=(n:number)=>n.toLocaleString('zh-CN',{maximumFractionDigits:2});
</script>

<template>
 <section class="sustainment" aria-label="剩余时段粮秣预算" data-testid="sustainment-budget">
  <div class="heading"><strong>粮秣预算</strong><span>{{value.horizon_kind==='rolling_plan'?'滚动规划':'剩余'}} {{value.remaining_turns}} 轮 · 每轮 {{value.step}}</span></div>
  <p v-if="value.horizon_kind==='rolling_plan'">此为向后滚动的保障预算，不是战局结束倒计时；耗尽库存仍会限制行动。</p>
  <p>按当前可用编组全部待命估算；库存工作量与粮食质量分列。</p>
  <p v-if="value.dynamics?.version==='personnel-rations-1'" data-testid="personnel-ration-basis">每人每日粮食 {{number(value.dynamics.ration_kg_per_person_day??0)}} kg；每粮食工作量 {{number(value.dynamics.food_kg_per_work??0)}} kg。需求随当前人数计算，属于显式估计，尚未历史标定。</p>
  <p v-else-if="value.dynamics">时间模型：待命每小时 {{number(value.dynamics.food_work_per_hour??0)}} 工作量；缺粮累计 {{number(value.dynamics.incapacity_after_hours)}} 小时后起算非战斗失能。参数未经历史或生理标定。</p>
  <article v-for="team in teams" :key="team" :data-testid="'sustainment-'+team" :class="{short:value.teams[team].optimistic_food_shortfall>0}">
   <b>{{team==='red'?'红方':'蓝方'}} · {{value.teams[team].available_units}} 个可用实体</b>
   <p v-if="value.teams[team].on_hand_food_kg!==undefined" :data-testid="'ration-mass-'+team">粮食质量：随队 {{number(value.teams[team].on_hand_food_kg??0)}} kg · 仓库 {{number(value.teams[team].warehouse_food_kg??0)}} kg · 待命需求 {{number(value.teams[team].minimum_hold_food_kg??0)}} kg。</p>
   <p v-if="value.remaining_turns===0">已到配置截止回合，暂无后续预算。</p>
   <p v-else-if="value.teams[team].optimistic_food_shortfall>0" class="warning">即使现有库存全部可达，仍缺 {{number(value.teams[team].optimistic_food_shortfall)}} 工作量。</p>
   <p v-else>总量未显示缺口；仍需核对运输、补给线和单位分配。</p>
   <dl><div><dt>随队粮秣</dt><dd>{{number(value.teams[team].on_hand_food)}}</dd></div><div><dt>{{value.supply_distribution?'仓库粮秣':'仓库补给包'}}</dt><dd>{{number(value.teams[team].warehouse_food??value.teams[team].warehouse_packages)}}</dd></div><div v-if="value.supply_distribution"><dt>仓库弹药</dt><dd>{{number(value.teams[team].warehouse_ammo??0)}}</dd></div><div><dt>待命所需粮秣</dt><dd>{{number(value.teams[team].minimum_hold_food)}}</dd></div></dl>
   <p v-if="value.supply_distribution">粮弹分别记账，共用运力；{{value.supply_distribution.priority==='food'?'粮秣':'弹药'}}优先。</p>
   <p v-if="value.teams[team].waiting_count">{{value.teams[team].waiting_count}} 个实体仍在等待，当前规则下也消耗粮秣。</p>
   <p v-if="value.teams[team].zero_food_count" class="warning">{{value.teams[team].zero_food_count}} 个实体粮秣已耗尽。</p>
   <p v-if="value.dynamics">最大累计缺粮 {{number(value.teams[team].max_shortage_hours??0)}} 小时；本轮非战斗失能 {{number(value.teams[team].last_noncombat_losses??0)}} 人（不是阵亡）。</p>
   <p v-if="value.teams[team].full_ammo_blocks_food_count" class="warning">{{value.teams[team].full_ammo_blocks_food_count}} 个实体满弹；当前粮弹绑定补给包可能无法补粮。</p>
  </article>
  <details><summary>估算范围与规则限制</summary><p>{{value.scope}}</p><p v-if="value.dynamics">{{value.dynamics.assumption}}</p></details>
 </section>
</template>

<style scoped>
.sustainment{margin:12px 0;padding:12px;border:1px solid #31515e;border-radius:4px;color:#c9dbe4;background:#0c2330;font-size:12px;line-height:1.65;overflow-wrap:anywhere}
.heading{display:flex;justify-content:space-between;flex-wrap:wrap;gap:4px 16px}.heading strong{color:#e7d19c}.heading span,dt{color:#a5bac5}p{margin:6px 0}
article{border-left:2px solid #5b8f9c;padding:8px 10px;margin:8px 0;background:#102b38}article.short{border-color:#e1b46b}.warning{color:#efcc91}
dl{display:flex;flex-wrap:wrap;gap:8px 24px;margin:6px 0}dl div{flex:1 1 90px}dd{margin:0;font-variant-numeric:tabular-nums;color:#e5edf0}summary{cursor:pointer;color:#abc9d4}
</style>
