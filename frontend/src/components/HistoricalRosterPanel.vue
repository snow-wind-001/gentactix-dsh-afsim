<script setup lang="ts">
import {computed,onBeforeUnmount,ref,watch} from 'vue';
import {api} from '../api';
import type {HistoricalInitialSnapshot,HistoricalRosterUnit} from '../types';

const props=defineProps<{battle:string;initial?:HistoricalInitialSnapshot;operationBound?:boolean}>();
const profile=ref<HistoricalInitialSnapshot|null>(null),loading=ref(false),error=ref('');
const query=ref(''),team=ref('all'),phase=ref('');
let generation=0,controller:AbortController|undefined;
async function load(){
  const current=++generation;
  controller?.abort();controller=new AbortController();
  error.value='';profile.value=null;loading.value=false;
  if(props.initial){profile.value=props.initial;phase.value=props.initial.phase_id;return;}
  if(!props.battle)return;
  loading.value=true;
  try{
    const data=await api.historicalInitial(props.battle,controller.signal);
    if(current!==generation)return;
    profile.value=data.initial;phase.value=data.initial?.phase_id??'';
  }catch(e){if(current===generation)error.value=String(e);}
  finally{if(current===generation)loading.value=false;}
}
watch(()=>[props.battle,props.initial?.definition_hash,props.initial?.phase_id],()=>{query.value='';team.value='all';void load();},{immediate:true});
onBeforeUnmount(()=>{generation++;controller?.abort();});
const all=computed(()=>profile.value?.definition.units??[]);
const byId=computed(()=>new Map(all.value.map(u=>[u.id,u])));
const visible=computed(()=>all.value.filter(u=>(team.value==='all'||team.value===u.team)&&
  `${u.name} ${u.id} ${u.echelon} ${u.parent_id?byId.value.get(u.parent_id)?.name:''}`.includes(query.value.trim())));
const commandCount=computed(()=>all.value.filter(u=>u.role==='command').length);
const presenceLabels:Record<string,string>={reported_present:'该阶段参战有记载',campaign_participant:'累计参战，阶段实到待核',later_participant:'后续参战',outside_scope:'未纳入当前计算范围，史料参考保留',unverified:'该阶段未核'};
function presence(u:HistoricalRosterUnit){return presenceLabels[u.presence.find(r=>r.phase_id===phase.value)?.status??'unverified'];}
function depth(u:HistoricalRosterUnit){let n=0,p=u.parent_id;while(p&&n<8){n++;p=byId.value.get(p)?.parent_id??null;}return n;}
</script>

<template>
  <section class="historical-roster" data-testid="historical-roster" aria-label="历史部队编制与来源">
    <header><h3>历史部队编制</h3><span>{{initial?'本局固定档案':'资料参考'}}</span></header>
    <p class="scope">{{initial?'档案已绑定本局；以下为参战参考，不证明当前全部到场。':'本局未绑定此档案；以下仅供核对，不是当前战场单位。'}}</p>
    <p v-if="loading" role="status">正在读取历史编制…</p>
    <p v-else-if="error" role="alert">{{error}} <button @click="load">重新读取</button></p>
    <p v-else-if="!profile" data-testid="historical-roster-missing">本战役尚未整理具名编制档案。来源事件和教学模板不能替代历史部队初态。</p>
    <template v-else>
      <p class="identity">{{profile.profile_id}} · v{{profile.version}}<br><small>定义摘要 {{profile.definition_hash.slice(0,12)}}</small></p>
      <div class="counts" data-testid="historical-roster-counts"><strong>{{all.length}}</strong> 条编制登记 · 指挥机构 {{commandCount}} 条</div>
      <p class="scope">上级与下级并列登记，不能相加计算总兵力。缺载人数、装备、位置为未知，不是零。</p>
      <label>浏览参战阶段<select v-model="phase" aria-label="浏览参战阶段"><option v-for="p in profile.definition.phases" :value="p.id" :key="p.id">{{p.label}} · {{p.date.label}}</option></select></label>
      <small>浏览阶段不会改变当前对局或证明单位在本帧到场。</small>
      <div class="filters"><label>查找部队<input v-model="query" type="search" placeholder="番号、层级或上级" aria-label="查找历史部队"></label><label>阵营<select v-model="team" aria-label="历史部队阵营"><option value="all">双方</option><option value="red">红方</option><option value="blue">蓝方</option></select></label></div>
      <p class="scope" role="status">显示 {{visible.length}} / {{all.length}} 条</p>
      <ol class="unit-list" aria-label="历史编制列表">
        <li v-for="u in visible" :key="u.id" :data-historical-unit="u.id" :class="u.team">
          <div :style="{paddingInlineStart:Math.min(depth(u),4)*8+'px'}"><strong>{{u.name}}</strong><span class="echelon">{{u.echelon}} · {{u.role==='command'?'指挥机构':'部队'}}</span></div>
          <small>上级：{{u.parent_id?byId.get(u.parent_id)?.name??'待核':'未载或独立列示'}}<br>{{presence(u)}}</small>
          <p class="facts">档案人数 {{u.facts.personnel.value??'未知'}} · 装备 {{u.facts.equipment.value===null?'未知':'有分类记录'}} · 位置 {{u.facts.position.value?'有位置依据（需核阶段）':'待定位'}}</p>
          <details><summary>来源与统计范围</summary><small>{{u.id}}</small><p>{{u.facts.personnel.scope}}</p><p>{{u.facts.position.scope}}</p><ul><li v-for="(e,i) in u.evidence" :key="i"><a :href="profile.definition.sources[e.source_id]?.url" target="_blank" rel="noopener noreferrer">{{profile.definition.sources[e.source_id]?.title}}</a><p>{{e.locator}}</p></li></ul></details>
        </li>
      </ol>
      <p v-if="!visible.length" role="status">没有符合筛选条件的部队。</p>
      <details class="coverage"><summary>档案覆盖与证据限制</summary><ul><li v-for="note in profile.definition.coverage.notes" :key="note">{{note}}</li></ul><p>{{operationBound?'本局已用独立估计参数绑定过程计算；档案事实仍保持来源精度，不能把模型数值当作历史实到。':'过程计算模型尚未绑定；编制非空不代表AFSIM交战已验收。'}}</p><p v-for="(s,id) in profile.definition.sources" :key="id"><a :href="s.url" target="_blank" rel="noopener noreferrer">{{s.title}}</a> · {{s.publisher}}<br>{{s.original_archive_examined?'记录为已核原件':'原始档案未逐页核验'}}；{{s.limitations}}</p></details>
    </template>
  </section>
</template>

<style scoped>
.historical-roster{padding:18px;color:#ccdade;font-size:13px;line-height:1.6;min-width:0}
header{display:flex;align-items:center;justify-content:space-between;gap:12px}h3{margin:0;color:#edf3f4;font-size:16px}header span,.identity,small{color:#98adb7}.scope{color:#b7bdba}.counts{border-block:1px solid #304752;padding:10px 0}.counts strong{font-size:24px;color:#e1cd9d;margin-right:4px}.identity{overflow-wrap:anywhere}.filters{display:grid;grid-template-columns:minmax(0,1fr) 90px;gap:10px;margin-top:14px}label{display:block}input,select{display:block;box-sizing:border-box;width:100%;margin:5px 0 3px;padding:8px;border:1px solid #35505d;background:#102632;color:#e0e9eb;border-radius:4px}input:focus-visible,select:focus-visible,summary:focus-visible{outline:2px solid #8dd9d0;outline-offset:2px}.unit-list{list-style:none;padding:0}.unit-list>li{border-left:2px solid #5b83a6;border-bottom:1px solid #2b414d;padding:12px 9px;overflow-wrap:anywhere}.unit-list>li.red{border-left-color:#ae6a67}.echelon{display:block;color:#98adb7;font-size:11px}.facts{font-size:12px;margin:7px 0}summary{cursor:pointer;color:#c5d8da}details{margin-top:7px}details p{margin:5px 0}.coverage{border-top:1px solid #304752;padding-top:12px}a{color:#8cd9d0}ul{padding-left:18px}button{cursor:pointer}
</style>
