<script setup lang="ts">
import type { AirOperations,Snapshot } from '../types';
defineProps<{ data: AirOperations;availability?:Snapshot['aviation_availability'] }>();
const availabilityLabels={pending:'尚未到达可用时段',active:'可用时段内',expired:'已退出可用时段'};
const phases: Record<string,string> = {launch:'起飞入场',air_defense:'防空响应',strike:'打击',abort_target_moved:'目标脱离，中止打击',returned:'返场'};
function time(seconds: number) { return `+${Math.floor(seconds/60)}分${(seconds%60).toFixed(1)}秒`; }
</script>

<template>
  <section class="air-panel" aria-label="航空任务与战果" data-testid="air-operations">
    <header><strong>航空任务与战果</strong><span>航空计算资源 · 估计参数</span></header>
    <p class="muted">时间为本轮内偏移。地图按任务回执显示航路；DSH过程估计与AFSIM原生回传分别标注，非实时雷达航迹。</p>
    <p class="muted">航空打击通过人员与装备损失影响态势；当前未计算空中遮断运输。</p>
    <p v-if="data.version==='afsim-air-teaching-1'" class="muted">旧版无目标支援的“影响到货”规则与当前目标航空任务分别记账。</p>
    <div v-for="(pool, team) in data.assets" :key="team" class="pool">
      <b>{{ team === 'red' ? '红方' : '蓝方' }}</b> 完好 {{ pool.ready }} / 投入 {{ pool.committed }} 架 · 损失 {{ pool.destroyed }} 架 · 累计 {{ pool.sorties }} 架次 · 航空弹药 {{ pool.ordnance }} · 航空燃油 {{ pool.fuel }} 工作单位
    </div>
    <details v-if="data.pools" data-testid="air-resource-pools" open><summary>逐部队资源账</summary><div v-for="(pool,id) in data.pools" :key="id" class="pool"><b>{{pool.name}}</b> · {{pool.team==='red'?'红方':'蓝方'}}<br>完好 {{pool.ready}} / 投入 {{pool.committed}} 架 · 损失 {{pool.destroyed}} 架 · {{pool.sorties}} 架次 · 航空弹药 {{pool.ordnance}} · 航空燃油 {{pool.fuel}} 工作单位<br><small>{{id}} · 数量为本局计算配置，非历史实力表</small><p v-if="availability?.[id]" :data-air-availability="id">{{availabilityLabels[availability[id]!.status]}} · {{availability[id]!.start}} — {{availability[id]!.end??'持续可用'}}<br><small>{{availability[id]!.assumption}}；完好不等于已到场或有足够油弹可出动。</small></p></div></details>
    <p v-if="!data.missions.length">本轮无航空出动。以下为近期任务记录，非本轮新增战果。</p>
    <article v-for="task in (data.missions.length ? data.missions : data.recent_missions?.slice(-6) ?? [])" :key="task.id">
      <b>{{ task.requester }} → {{ task.target }}</b><p v-if="task.pool_id">航空部队：{{data.pools?.[task.pool_id]?.name??task.pool_id}}</p><p>{{task.source==='dsh_model_estimate'?'DSH过程估计':'AFSIM原生任务回传'}} · T+{{ task.turn }} · {{ task.package }} 架出动 · 高度 {{ task.altitude_m }}m（计算设定） · {{ task.outcome === 'strike' ? '完成打击并返场' : '未投弹，任务中止后返场' }}</p>
      <ol><li v-for="(event,index) in task.events" :key="index"><time>{{ time(event.seconds) }}</time> {{ phases[event.phase] ?? event.phase }}</li></ol>
      <p>期望效果：人员减员 {{ task.personnel_effect }}，装备损失 {{ task.equipment_effect }}；己方飞机损失 {{ task.aircraft_lost }} 架。投弹 {{ task.ordnance_spent }}，耗油 {{ task.fuel_spent }} 工作单位。</p>
      <p v-if="task.target_turn_effects">该目标当轮实际空袭减员 {{ task.target_turn_effects.air_casualties }} 人、装备损失 {{ task.target_turn_effects.air_equipment_destroyed }}；地面火力减员 {{ task.target_turn_effects.ground_casualties }} 人。同目标同轮合计，请勿跨任务相加。</p>
      <p class="muted">{{ task.effect_basis }}；实际战损见人员装备账。</p>
    </article>
    <details><summary>参数与能力范围</summary><p>{{ data.assumptions }}</p><code>{{ data.version }}</code></details>
  </section>
</template>

<style scoped>
.air-panel { margin:0; padding:12px 16px; border:1px solid #325263; border-radius:6px; background:#0b202d; color:#ccdde5; font-size:12px; }
header { display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; color:#e5d09e; } header span,.muted { color:#91adb9; }
.pool { padding:7px 0; border-bottom:1px solid #254353; line-height:1.8; } article { padding:10px 0; border-bottom:1px solid #325263; } p { margin:6px 0; line-height:1.65; overflow-wrap:anywhere; }
ol { display:flex; gap:10px 22px; padding-left:20px; flex-wrap:wrap; } time { color:#80cfbb; font-variant-numeric:tabular-nums; } summary { cursor:pointer; }
</style>
