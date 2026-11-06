<script setup lang="ts">
import type {CampaignPlanConfiguration} from '../types';
defineProps<{value:CampaignPlanConfiguration;disabled:boolean}>();
const emit=defineEmits<{'pick-goal':[id:string]}>();
function number<T extends object>(target:T,key:keyof T,event:Event,factor=1){target[key]=Number((event.target as HTMLInputElement).value)*factor as T[keyof T];}
</script>
<template>
 <fieldset :disabled="disabled" class="goal-inputs" data-testid="campaign-goal-inputs"><legend>参演方目标参数</legend>
  <p>目标只按实际态势评分，不自动下令。地域、阈值与时长为计算估计；修改后须重新验证。</p>
  <details v-for="node in value.nodes" :key="node.id" :data-goal-input="node.id"><summary>{{node.team==='red'?'红方':'蓝方'}} · {{node.label}}</summary>
   <div class="grid"><label>激活延迟（小时）<input type="number" min="0" :value="node.not_before_seconds/3600" @input="number(node,'not_before_seconds',$event,3600)" :aria-label="`${node.label}激活延迟小时`"></label>
    <label>连续保持（分钟）<input type="number" min="0" :value="node.hold_seconds/60" @input="number(node,'hold_seconds',$event,60)" :aria-label="`${node.label}保持分钟`"></label>
    <label v-if="node.condition.kind==='preserve'">投入兵力保存比例<input type="number" min="0.001" max="1" step="0.05" :value="Number(node.condition.minimum_fraction)" @input="number(node.condition,'minimum_fraction',$event)" :aria-label="`${node.label}保存比例`"></label>
    <template v-if="node.condition.kind==='resources'"><label>随队粮秣下限<input type="number" min="0" max="100" :value="Number(node.condition.minimum_food)" @input="number(node.condition,'minimum_food',$event)" :aria-label="`${node.label}粮秣下限`"></label><label>随队弹药下限<input type="number" min="0" max="100" :value="Number(node.condition.minimum_ammo)" @input="number(node.condition,'minimum_ammo',$event)" :aria-label="`${node.label}弹药下限`"></label></template>
    <template v-if="node.condition.region"><label>纬度<input type="number" v-model.number="node.condition.region.center.lat" :aria-label="`${node.label}纬度`" step="0.0001" min="-90" max="90"></label><label>经度<input type="number" v-model.number="node.condition.region.center.lng" :aria-label="`${node.label}经度`" step="0.0001" min="-180" max="180"></label><label>半径 km<input type="number" v-model.number="node.condition.region.radius_km" :aria-label="`${node.label}半径`" step="0.1" min="0.01" max="20"></label>
     <label>{{node.condition.kind==='defend'?'保持部署人数':'最少到达人员'}}<input type="number" :value="Number(node.condition.minimum_personnel)" @input="number(node.condition,'minimum_personnel',$event)" :aria-label="`${node.label}最少人员`" min="1"></label></template>
   </div>
   <p v-if="node.condition.kind==='defend'">部署区允许接敌；以“{{value.nodes.find(target=>target.id===node.condition.against_node)?.label??node.condition.against_node}}”的核心地域及人数门槛判断突破，不等待对方保持计时。对抗方向固定，核心参数在对应蓝方或红方目标中设置。</p>
   <button v-if="node.condition.region" type="button" @click="emit('pick-goal',node.id)">地图设置{{node.label}}</button>
   <p>{{node.unit_ids.length}}个固定承担身份；{{node.after.node_ids.length?'须先满足所列前置目标':'无前置目标'}}。</p>
   <label>估计依据<textarea v-model="node.assumption" rows="2" :aria-label="`${node.label}估计依据`"></textarea></label>
  </details>
 </fieldset>
</template>
<style scoped>
.goal-inputs{border:0;border-block:1px solid #294553;padding:14px 0;margin:12px 0;min-width:0}legend,summary{color:#cfdee4}summary{cursor:pointer}p{color:#9db6c5;line-height:1.6;font-size:12px}label{display:block;color:#aec6d2;margin-top:9px}input,textarea{display:block;width:100%;box-sizing:border-box;margin-top:4px}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px 12px}details{border-top:1px solid #294553;padding:12px 0;margin-top:10px}button{font-size:11px;margin-top:8px}@media(max-width:600px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>
