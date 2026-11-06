<script setup lang="ts">
import {computed,ref} from 'vue';
import type {CampaignLifecycleConfiguration,CampaignLifecycleState,CampaignPlanConfiguration} from '../types';
const props=defineProps<{configuration:CampaignLifecycleConfiguration;state:CampaignLifecycleState;goals?:CampaignPlanConfiguration}>();
const expanded=ref(false),labels=computed(()=>Object.fromEntries((props.goals?.nodes??[]).map(n=>[n.id,n.label])));
const visible=computed(()=>expanded.value?props.configuration.phases:props.configuration.phases.slice(0,8));
const current=computed(()=>props.configuration.phases[props.state.phase_index]);
const elapsed=computed(()=>Math.max(0,props.state.sample_at-(props.state.phases[current.value.id].entered_at??0)));
const duration=(seconds:number)=>seconds>=3600?(seconds/3600).toFixed(1)+'小时':(seconds/60).toFixed(0)+'分钟';
const statuses={pending:'待激活',active:'当前阶段',completed:'已完成'};
</script>

<template>
 <section class="lifecycle" data-testid="campaign-lifecycle" aria-label="连续会战阶段">
  <h4>连续会战阶段 · {{state.phase_index+1}} / {{configuration.phases.length}}</h4>
  <p data-testid="lifecycle-current"><b>{{current.label}}</b> · {{state.status==='completed'?'全部阶段已完成':state.status==='interrupted'?'阶段链已中断':'进行中'}}</p>
  <p v-if="state.reason">{{state.reason}}</p>
  <p v-if="state.status==='active'&&current.minimum_duration_seconds" data-testid="lifecycle-duration">本阶段已推进 {{duration(elapsed)}} · 最短还需 {{duration(Math.max(0,current.minimum_duration_seconds-elapsed))}}</p>
  <p class="scope">阶段沿同一战局推进，单位、命令和资源持续记账；阶段里程碑不等于当前仍控制阵地。{{configuration.finish_policy==='all_phases'?'全部阶段完成后，双方总目标仍须满足。':'双方总目标可提前结算并中断后续阶段。'}}</p>
  <ol id="campaign-stage-list">
   <li v-for="phase in visible" :key="phase.id" :data-phase-id="phase.id" :class="{current:state.phases[phase.id].status==='active'}">
    <div><b>{{phase.label}}</b><span>{{statuses[state.phases[phase.id].status]}}</span></div>
    <p v-if="phase.minimum_duration_seconds">最短持续 {{duration(phase.minimum_duration_seconds)}}；间隙也照常计算时间与消耗。</p>
    <p v-if="phase.goal_ids.length">阶段目标：{{phase.goal_ids.map(i=>labels[i]??'目标资料未载').join('、')}}</p>
    <p class="scope">进入：{{state.phases[phase.id].entered_at===null?'尚未激活':'累计'+duration(state.phases[phase.id].entered_at!)}} · 完成：{{state.phases[phase.id].completed_at===null?'未完成':'累计'+duration(state.phases[phase.id].completed_at!)}}</p>
   </li>
  </ol>
  <button v-if="configuration.phases.length>8" type="button" :aria-expanded="expanded" aria-controls="campaign-stage-list" @click="expanded=!expanded">{{expanded?'收起阶段':'显示全部 '+configuration.phases.length+' 个阶段'}}</button>
  <p class="scope">此版本不改变参战单位集合，不自动下令、补员或重编。</p>
 </section>
</template>

<style scoped>
.lifecycle{border-block:1px solid var(--border,#284552);padding:12px 0;margin:12px 0}.lifecycle h4{margin:0;color:#e0e9eb}.lifecycle p{line-height:1.6;margin:7px 0}.scope{color:var(--text-muted,#9fb4c0);font-size:12px}.lifecycle ol{list-style:none;padding:0;margin:0}.lifecycle li{padding:10px 0;border-top:1px solid var(--border,#284552)}.lifecycle li>div{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap}.lifecycle li span{color:#b6c8cd;font-size:12px}.lifecycle .current{border-left:2px solid #c9b47d;padding-left:10px}.lifecycle li p{overflow-wrap:anywhere}.lifecycle button{font:inherit;font-size:12px;background:transparent;color:inherit;border:1px solid var(--border,#284552);padding:6px 10px;border-radius:5px;cursor:pointer}.lifecycle button:focus-visible{outline:2px solid #7cb5d2;outline-offset:2px}
</style>
