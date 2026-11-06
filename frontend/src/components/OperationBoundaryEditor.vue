<script setup lang="ts">
import type {MapPoint,OperationBoundary} from '../types';
const props=defineProps<{modelValue?:OperationBoundary;area:{center:MapPoint;radius_km:number};compatible:boolean;disabled:boolean}>();
const emit=defineEmits<{'update:modelValue':[value:OperationBoundary|undefined];pick:[key:'center'|'inside'|'outside',route:number]}>();
function enable(checked:boolean){
 if(!checked){emit('update:modelValue',undefined);return;}
 const center={...props.area.center};
 emit('update:modelValue',{version:'operation-boundary-1',center,radius_km:props.area.radius_km*.7,
  assumption:'待复核的计算边界；不是已考证历史战线。',routes:[{id:'red-exit-1',team:'red',inside:{...center},
   outside:{lat:center.lat+props.area.radius_km*.9/111.195,lng:center.lng},corridor_km:.05,assumption:'待复核的直线通路；无道路容量或DEM。'}]});
}
function add(){if(props.modelValue)props.modelValue.routes.push({id:'route-'+crypto.randomUUID().slice(0,8),team:'blue',
 inside:{...props.area.center},outside:{lat:props.area.center.lat+props.area.radius_km*.9/111.195,lng:props.area.center.lng},
 corridor_km:.05,assumption:'待说明通路来源或估计依据。'});}
</script>
<template>
 <fieldset :disabled="disabled" class="boundary-editor" data-testid="operation-boundary-editor">
  <legend>作战区域与场外通路</legend>
  <label><input type="checkbox" :checked="!!modelValue" :disabled="!compatible||disabled" aria-label="启用作战区边界" @change="enable(($event.target as HTMLInputElement).checked)">显式区分作战区与仿真世界</label>
  <p v-if="!compatible">须先配置会战目标图；旧几何局保留原规则。</p>
  <template v-if="modelValue">
   <p>场外仍在同一物理世界，保持实际位置、伤损与消耗，也可能受击。直线通路未经历史标定；修改后须重新验证。</p>
   <div class="boundary-grid"><label>区内中心纬度<input v-model.number="modelValue.center.lat" type="number" step="0.0001"></label><label>区内中心经度<input v-model.number="modelValue.center.lng" type="number" step="0.0001"></label><label>作战区半径 km<input v-model.number="modelValue.radius_km" type="number" min="0.05" step="0.1" aria-label="作战区半径"></label></div>
   <button type="button" @click="emit('pick','center',-1)">地图设置作战区中心</button>
   <label>边界依据<textarea v-model="modelValue.assumption" rows="2"></textarea></label>
   <details v-for="(route,i) in modelValue.routes" :key="i" open class="boundary-route">
    <summary>{{route.team==='red'?'红':'蓝'}}方 · {{route.id}}</summary>
    <div class="boundary-grid"><label>通路ID<input v-model="route.id"></label><label>阵营<select v-model="route.team"><option value="red">红方</option><option value="blue">蓝方</option></select></label><label>通路半宽 km<input v-model.number="route.corridor_km" type="number" step="0.01" min="0.001" max="2"></label></div>
    <p>区内点 {{route.inside.lat.toFixed(5)}}, {{route.inside.lng.toFixed(5)}} → 区外点 {{route.outside.lat.toFixed(5)}}, {{route.outside.lng.toFixed(5)}}</p>
    <button type="button" @click="emit('pick','inside',i)">地图设置区内点</button><button type="button" @click="emit('pick','outside',i)">地图设置区外点</button>
    <label>通路依据<textarea v-model="route.assumption" rows="2"></textarea></label>
    <button type="button" :disabled="modelValue.routes.length<=1" @click="modelValue.routes.splice(i,1)">移除通路</button>
   </details>
   <button type="button" :disabled="modelValue.routes.length>=64" @click="add">增加出入通路</button>
  </template>
 </fieldset>
</template>
<style scoped>
.boundary-editor{margin:12px 0;border:1px solid var(--line);padding:12px;min-width:0}.boundary-editor p{font-size:11px;line-height:1.65;color:var(--muted)}.boundary-editor label{display:block;font-size:11px;margin:7px 0}.boundary-editor input:not([type=checkbox]),select,textarea{width:100%;min-width:0}.boundary-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:8px}.boundary-route{border-top:1px solid var(--line);margin-top:12px;padding-top:8px}.boundary-editor button{margin:3px 6px 3px 0;font-size:11px}
</style>
