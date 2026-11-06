<script setup lang="ts">
import type {AviationParameters} from '../types';
defineProps<{parameters:Record<string,AviationParameters>;identities?:{id:string;name:string;team:string}[];disabled:boolean}>();
const rules=[['package','单任务飞机数'],['fuel_per_aircraft','每架次燃油工作量'],['preparation_s','准备时间 s'],
 ['speed_mps','航路速度 m/s'],['altitude_m','计算飞行高度 m'],['target_radius_km','目标复核半径 km'],
 ['personnel_per_effective_aircraft','每有效飞机人员效应上限'],['equipment_per_effective_aircraft','每有效飞机装备效应上限']] as const;
</script>
<template>
 <section aria-label="航空计算参数" data-testid="aviation-parameters">
  <p>航空部队与地面编组分别记账。以下数量、入场点和效能是计算参数；出动架数不等于历史飞机库存，入场点不代表已考证机场。</p>
  <details v-for="(pool,id) in parameters" :key="id"><summary>{{identities?.find(u=>u.id===id)?.name??id}} · 航空资源</summary>
   <fieldset :disabled="disabled"><small>{{id}} · 身份与来源由初态绑定</small><div class="grid">
    <label>投入飞机（架）<input type="number" v-model.number="pool.initial.committed" min="0" max="100000" step="1" :aria-label="`${id}投入飞机`"></label>
    <label>航空弹药工作量<input type="number" v-model.number="pool.initial.ordnance" min="0" max="10000000" step="1"></label>
    <label>航空燃油工作量<input type="number" v-model.number="pool.initial.fuel" min="0" max="10000000" step="1"></label>
    <label>入场点纬度<input type="number" v-model.number="pool.entry.lat" min="-90" max="90" step="0.0001"></label>
    <label>入场点经度<input type="number" v-model.number="pool.entry.lng" min="-180" max="180" step="0.0001"></label>
    <label v-for="[key,label] in rules" :key="key">{{label}}<input type="number" v-model.number="pool.rules[key]" min="0" :step="key==='target_radius_km'?'0.01':'1'"></label>
    <template v-if="pool.availability">
     <label>估计可用起点<input type="datetime-local" v-model="pool.availability.start" step="1" :aria-label="`${id}航空可用起点`"></label>
     <label>估计退出时点（留空为持续可用）<input type="datetime-local" :value="pool.availability.end" step="1" :aria-label="`${id}航空退出时点`" @input="pool.availability.end=($event.target as HTMLInputElement).value||null"></label>
    </template>
   </div><label>参数依据与范围（修改数量和规则后请同步核对）<textarea v-model="pool.assumption" rows="2" :aria-label="`${id}航空估计依据`"></textarea></label></fieldset>
   <label v-if="pool.availability">可用时段依据（估计不当作史实）<textarea v-model="pool.availability.assumption" :disabled="disabled" :aria-label="`${id}航空可用时段依据`"></textarea></label>
  </details>
 </section>
</template>
<style scoped>
section{border-block:1px solid #294553;margin:12px 0;font-size:12px;line-height:1.6}p,small{color:#9db6c5}details{margin:10px 0}summary{cursor:pointer;color:#cfdee4}fieldset{border:0;padding:10px 0;min-width:0}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}label{display:block;color:#aec6d2}input,textarea{display:block;width:100%;box-sizing:border-box;margin-top:4px}small{display:block;overflow-wrap:anywhere}@media(max-width:600px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>
