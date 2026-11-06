<script setup lang="ts">
import {watch} from 'vue';
import type {CrossingFacility} from '../types';
const props=defineProps<{facility:CrossingFacility;rules:Record<string,unknown>;disabled:boolean;networkChild?:boolean}>();
const weights=[['armor','装甲'],['artillery','火炮'],['air_defense','防空'],['engineer','工兵'],['transport','运输']] as const;
function toggle(event:Event){
 if(props.disabled)return;
 if(!(event.target as HTMLInputElement).checked){delete props.facility.crossing_model;delete props.facility.crossing_network;return;}
 const {lat,lng}=props.facility;
 props.facility.crossing_model={version:'formation-crossing-1',barrier:{a:{lat,lng:lng-.005},b:{lat,lng:lng+.005}},
  banks:{a:{lat:lat-.001,lng},b:{lat:lat+.001,lng}},throughput_work_per_hour:1000,
  equipment_work:{armor:10,artillery:5,air_defense:5,engineer:0,transport:2},build_progress_per_engineer_hour:10,
  supply_work_per_unit:100,assumption:''};
 props.rules.bridge_enabled=true;
}
function toggleFerry(event:Event){
 const model=props.facility.crossing_model;if(!model||props.disabled)return;
 if(props.facility.crossing_network||props.networkChild)return;
 if(!(event.target as HTMLInputElement).checked){delete model.ferry;return;}
 model.ferry={version:'formation-ferry-1',assumption:'',boats:[{id:'boat1',name:'计算舟艇1',team:'red',seats:30,
  equipment_work_capacity:0,speed_mps:1,load_seconds:30,unload_seconds:30,initial_bank:'a',assumption:''}]};
}
function addBoat(){const f=props.facility.crossing_model?.ferry;if(!f||f.boats.length>=8)return;
 let n=1;while(f.boats.some(b=>b.id===`boat${n}`))n++;
 f.boats.push({id:`boat${n}`,name:`计算舟艇${n}`,team:'red',seats:30,equipment_work_capacity:0,
  speed_mps:1,load_seconds:30,unload_seconds:30,initial_bank:'a',assumption:''});}
function addSite(){
 const base=props.facility;if(props.disabled||props.networkChild||!base.crossing_model||base.crossing_model.ferry)return;
 const net=base.crossing_network??{version:'formation-crossing-network-1' as const,sites:[]};if(net.sites.length>=7)return;
 let n=2;while([base,...net.sites].some(s=>s.id===`${base.id}_site${n}`))n++;
 const site=JSON.parse(JSON.stringify(base)) as CrossingFacility;
 delete site.crossing_network;delete site.crossing_receipt;delete site.ferry_state;
 site.id=`${base.id}_site${n}`;site.name=`待配置渡点 ${n}`;site.used=0;site.crossing_model!.assumption='';
 net.sites.push(site);base.crossing_network=net;
}
function removeSite(index:number){
 if(props.disabled)return;const net=props.facility.crossing_network;if(!net)return;
 net.sites.splice(index,1);if(!net.sites.length)delete props.facility.crossing_network;
}
watch(()=>props.facility.crossing_model?.barrier,value=>{
 if(value&&!props.disabled)for(const site of props.facility.crossing_network?.sites??[])if(site.crossing_model)
  site.crossing_model.barrier=JSON.parse(JSON.stringify(value));
},{deep:true});
</script>
<template>
 <details class="crossing-editor" data-testid="crossing-editor"><summary>{{networkChild?facility.name:'渡河通道与工程保障'}}</summary>
  <fieldset :disabled="disabled">
   <label v-if="!networkChild" class="toggle"><input type="checkbox" :checked="!!facility.crossing_model" @change="toggle" aria-label="使用版本化渡运模型">使用有限河段与共享吞吐模型</label>
   <p>开启后给出可编辑的几何和能力草稿；须核对全部参数并说明依据，再重新验证。它们是计算估计，不能当作历史河槽或已考证渡口。</p>
   <template v-if="facility.crossing_model">
    <div class="grid">
     <label>设施名称<input v-model="facility.name" aria-label="渡运设施名称"></label>
     <label>设施纬度<input type="number" v-model.number="facility.lat" min="-85" max="85" step="0.0001"></label>
     <label>设施经度<input type="number" v-model.number="facility.lng" min="-180" max="180" step="0.0001"></label>
     <label>轮初施工进度 %<input type="number" v-model.number="facility.progress" min="0" max="100"></label>
     <label>轮初完整度 %<input type="number" v-model.number="facility.integrity" min="0" max="100"></label>
     <label>设施材料（包）<input type="number" v-model.number="facility.materials" min="0" step="1"></label>
     <label>工作量 / 小时<input type="number" v-model.number="facility.crossing_model.throughput_work_per_hour" min="0.01" max="1000000" aria-label="渡运每小时吞吐"></label>
     <label>每工兵组小时施工进度<input type="number" v-model.number="facility.crossing_model.build_progress_per_engineer_hour" min="0.0001" max="1000"></label>
     <label>每标准补给份渡运工作量<input type="number" v-model.number="facility.crossing_model.supply_work_per_unit" min="0.01" max="1000000"></label>
    </div>
    <div v-for="key in (['barrier','banks'] as const).filter(k=>!networkChild||k!=='barrier')" :key="key"><h4>{{key==='barrier'?'有限河线两端（各渡点共用）':'通道两岸入口 / 出口'}}</h4><div class="grid">
     <template v-for="bank in (['a','b'] as const)" :key="bank">
      <label>{{bank.toUpperCase()}} 纬度<input type="number" v-model.number="facility.crossing_model[key][bank].lat" min="-85" max="85" step="0.0001" :aria-label="`${key}-${bank}纬度`"></label>
      <label>{{bank.toUpperCase()}} 经度<input type="number" v-model.number="facility.crossing_model[key][bank].lng" min="-180" max="180" step="0.0001" :aria-label="`${key}-${bank}经度`"></label>
     </template>
    </div></div>
    <h4>每件可用装备的附加工作量</h4><div class="grid"><label v-for="[key,label] in weights" :key="key">{{label}}<input type="number" v-model.number="facility.crossing_model.equipment_work[key]" min="0" max="100"></label></div>
    <label>几何、能力与计量依据<textarea v-model="facility.crossing_model.assumption" rows="3" required aria-label="渡运估计依据"></textarea></label>
    <label v-if="!networkChild&&!facility.crossing_network" class="toggle"><input type="checkbox" :checked="!!facility.crossing_model.ferry" @change="toggleFerry" aria-label="使用舟艇运输">舟艇运输（整分队登乘）</label>
    <template v-if="facility.crossing_model.ferry">
     <p>每艘一次乘载一个容量允许的计算分队。船速、船数、座位与装卸时间须核对并说明估计；人数过多须在初态划分。此模式使用舟艇，不自动切为已建桥通行；未建水流、沉船、船上射击及仓库跨河货运。</p>
     <label>舟艇总依据<textarea v-model="facility.crossing_model.ferry.assumption" aria-label="舟艇总依据"></textarea></label>
     <article v-for="(boat,i) in facility.crossing_model.ferry.boats" :key="boat.id" data-testid="ferry-config-row">
      <b>{{boat.id}} · {{boat.name}}</b><button type="button" :disabled="facility.crossing_model.ferry.boats.length===1" @click="facility.crossing_model.ferry.boats.splice(i,1)">移除此艇</button>
      <div class="grid"><label>舟艇名称<input v-model="boat.name"></label><label>归属<select v-model="boat.team"><option value="red">红方</option><option value="blue">蓝方</option></select></label>
       <label>座位 人<input v-model.number="boat.seats" type="number" min="1" max="10000"></label>
       <label>装备工作量容量<input v-model.number="boat.equipment_work_capacity" type="number" min="0"></label>
       <label>船速 m/s<input v-model.number="boat.speed_mps" type="number" min="0.01" max="30" step="0.1"></label>
       <label>装载 秒<input v-model.number="boat.load_seconds" type="number" min="1"></label><label>卸载 秒<input v-model.number="boat.unload_seconds" type="number" min="1"></label>
       <label>初始岸<select v-model="boat.initial_bank"><option value="a">A岸</option><option value="b">B岸</option></select></label></div>
      <label>本艇估计依据<textarea v-model="boat.assumption"></textarea></label>
     </article>
     <button type="button" :disabled="facility.crossing_model.ferry.boats.length>=8" @click="addBoat">增加计算舟艇</button>
    </template>
    <template v-if="!networkChild&&!facility.crossing_model.ferry">
     <h4>同河多渡点</h4><p>各点独立排队，共用全场部队和仓库。按登记通道最短距离选点；原队列保持原点，不自动绕开关闭或受威胁路线。新增项复制几何供编辑，必须核对岸点、能力与依据；当前不支持多渡点舟艇调度。</p>
     <article v-for="(site,i) in facility.crossing_network?.sites??[]" :key="site.id" data-testid="crossing-site-row">
      <button type="button" @click="removeSite(i)" :aria-label="`移除渡点 ${site.name}`">移除此渡点</button>
      <CrossingParametersEditor :facility="site" :rules="rules" :disabled="disabled" network-child />
     </article>
     <button type="button" :disabled="(facility.crossing_network?.sites.length??0)>=7" @click="addSite">增加独立渡点</button>
    </template>
    <p>人员数与装备折算为工作量；仅完成排队或登船不能称已登岸。桥式通行保留原有共享物资吞吐；舟艇模式另记船位与乘载分队，人员账不因登乘增减。桥头战斗和历史水文仍须另行核验。</p>
   </template>
  </fieldset>
 </details>
</template>
<style scoped>
details{border-block:1px solid #294553;margin:12px 0;font-size:12px;line-height:1.6}summary{padding:10px 0;cursor:pointer;color:#cfdee4}fieldset{border:0;padding:0 0 12px;min-width:0}p{color:#9db6c5}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}label{display:block;color:#aec6d2}input,textarea{display:block;box-sizing:border-box;width:100%;margin-top:4px}.toggle{display:flex;align-items:center;gap:8px}.toggle input{width:auto;margin:0}h4{font-size:12px;font-weight:600;margin:14px 0 6px}@media(max-width:600px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>
