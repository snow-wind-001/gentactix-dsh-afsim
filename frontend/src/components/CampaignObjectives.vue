<script setup lang="ts">
import { computed, ref } from 'vue';
import type { CampaignPlanConfiguration, CampaignPlanState } from '../types';
const props=defineProps<{configuration:CampaignPlanConfiguration;state:CampaignPlanState;requiredTurns:number}>();
const team=ref<'all'|'red'|'blue'>('all'),expanded=ref(false);
const rows=computed(()=>props.configuration.nodes.filter(n=>team.value==='all'||n.team===team.value));
const visible=computed(()=>expanded.value?rows.value:rows.value.slice(0,8));
const labels=computed(()=>Object.fromEntries(props.configuration.nodes.map(n=>[n.id,n.label])));
const activeTeams=computed(()=>(['red','blue'] as const).filter(t=>props.configuration.outcomes[t].node_ids.length));
const statuses:Record<string,string>={pending:'尚未运行',waiting_phase:'等待阶段采样',waiting_time:'等待激活',waiting_dependency:'等待前置目标',waiting_arrival:'等待部队到场',blocked:'受阻',active:'执行中',holding:'保持中',completed:'已达成'};
const duration=(seconds:number)=>seconds>=3600?(seconds/3600).toFixed(1)+'小时':(seconds/60).toFixed(0)+'分钟';
</script>

<template>
 <section class="objectives" data-testid="campaign-objectives" aria-label="会战多方向目标">
  <div class="heading"><strong>会战多方向目标</strong><label>查看 <select v-model="team" aria-label="目标阵营"><option value="all">{{activeTeams.length===2?'双方':'参演方'}}</option><option v-for="t in activeTeams" :key="t" :value="t">{{t==='red'?'红方':'蓝方'}}</option></select></label></div>
  <p class="scope">按当前物理态势评分；目标图不自动下令。一个方向达成后，其余方向继续。</p>
  <p v-if="activeTeams.length===1" class="scope" data-testid="single-team-goals">本窗口仅计算{{activeTeams[0]==='red'?'红方':'蓝方'}}转移目标；未建模敌方不表示整个战区没有敌军，也不会因对方为空自动获胜。</p>
  <p v-if="Object.values(state.nodes).some(n=>n.status==='waiting_phase')" class="scope">目标按本轮起始阶段采样；刚进入阶段的目标最早在下一轮评分。</p>
  <div class="outcomes"><span v-for="t in activeTeams" :key="t">{{t==='red'?'红方':'蓝方'}}连续达标 {{state.side_progress[t]}} / {{requiredTurns}} 轮</span></div>
  <ol>
   <li v-for="node in visible" :key="node.id" :data-goal-id="node.id" :class="{met:state.nodes[node.id].status==='completed'}">
    <div class="node-heading"><span class="side" :class="node.team">{{node.team==='red'?'红方':'蓝方'}}</span><b>{{node.label}}</b><span class="status">{{statuses[state.nodes[node.id].status]??'状态未知'}}</span></div>
    <p>{{state.nodes[node.id].reason}}<template v-if="node.hold_seconds"> · 已保持{{duration(state.nodes[node.id].held_seconds)}} / {{duration(node.hold_seconds)}}</template></p>
    <p v-if="node.after.node_ids.length" class="dependency">前置（{{node.after.mode==='all'?'全部':'任一'}}）：{{node.after.node_ids.map(id=>labels[id]??id).join('、')}}</p>
    <p v-if="node.latch&&state.nodes[node.id].status==='completed'&&!state.nodes[node.id].condition" class="note">里程碑已经达成，当前条件已不满足；不表示仍控制阵地。</p>
   </li>
  </ol>
  <button v-if="rows.length>8" type="button" @click="expanded=!expanded">{{expanded?'收起':'显示全部 '+rows.length+' 项目标'}}</button>
  <p class="scope">保持时间从首次满足的回合端点起保守计时；未观测的回合内部不补算控制时长。</p>
 </section>
</template>

<style scoped>
.objectives{border-block:1px solid var(--border,#284552);padding:14px 0;margin:12px 0}.heading,.node-heading,.outcomes{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.heading{justify-content:space-between}.heading label,.scope,.dependency{font-size:12px;color:var(--text-muted,#9fb4c0)}.heading select{font:inherit;color:inherit;background:var(--surface,#102b39);border:1px solid var(--border,#284552);border-radius:5px;padding:4px 6px}.scope{line-height:1.6;margin:8px 0}.outcomes{font-size:12px;justify-content:space-between;margin:10px 0}ol{list-style:none;padding:0;margin:0}li{padding:11px 0;border-top:1px solid var(--border,#284552)}li p{font-size:12px;line-height:1.6;margin:5px 0 0}.node-heading b{flex:1;min-width:100px;font-weight:600}.side{font-size:11px;border-left:2px solid;padding-left:6px}.red{color:#ed9d94}.blue{color:#9fc2ef}.status{font-size:12px;color:var(--text-muted,#9fb4c0)}.met .status{color:#92d7af}.note{color:#d4bb83}button{font:inherit;font-size:12px;border:1px solid var(--border,#284552);background:transparent;color:inherit;border-radius:5px;padding:6px 10px;cursor:pointer}button:focus-visible,select:focus-visible{outline:2px solid #7cb5d2;outline-offset:2px}
</style>
