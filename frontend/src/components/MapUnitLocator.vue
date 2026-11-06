<script setup lang="ts">
import {computed,nextTick,ref} from 'vue';
import type {MapUnitEntry,UnitOverlapGroup} from '../mapUnits';
const props=defineProps<{units:MapUnitEntry[];groups:UnitOverlapGroup[];selected:string;picking:boolean}>();
const emit=defineEmits<{select:[id:string]}>();
const opened=ref(false),search=ref(''),team=ref(''),inView=ref(false);
const trigger=ref<HTMLButtonElement|null>(null);
function close(){opened.value=false;void nextTick(()=>trigger.value?.focus());}
const visible=computed(()=>new Set(props.groups.flatMap(g=>g.ids)));
const overlap=computed(()=>new Map(props.groups.filter(g=>g.ids.length>1).flatMap(g=>g.ids.map(id=>[id,g.ids.length] as const))));
const stacks=computed(()=>props.groups.filter(g=>g.ids.length>1).length);
const filtered=computed(()=>props.units.filter(u=>(!team.value||u.team===team.value)&&(!inView.value||visible.value.has(u.id))&&
 (!search.value.trim()||[u.name,u.id,u.source_id,u.echelon].some(v=>v.toLowerCase().includes(search.value.trim().toLowerCase())))));
function choose(id:string){if(!props.picking){emit('select',id);opened.value=false;}}
</script>

<template>
 <section class="unit-locator" data-testid="map-unit-locator" @keydown.esc.stop.prevent="close">
  <button ref="trigger" class="locator-trigger" type="button" :aria-expanded="opened" aria-controls="map-unit-locator-panel" @click="opened=!opened">
   单位 <b>{{units.length}}</b><span v-if="stacks"> · {{stacks}}组重叠</span><span aria-hidden="true">{{opened?'⌃':'⌄'}}</span>
  </button>
  <div v-if="opened" id="map-unit-locator-panel" class="locator-panel" aria-label="地图单位定位" data-testid="map-unit-list">
   <header><strong>定位计算单位</strong><button type="button" aria-label="关闭单位定位" @click="close">×</button></header>
   <label>搜索部队<input v-model="search" type="search" aria-label="地图单位搜索" placeholder="番号、名称或ID"></label>
   <div class="locator-filters"><label>阵营<select v-model="team" aria-label="地图单位阵营"><option value="">双方</option><option value="red">红方</option><option value="blue">蓝方</option></select></label><label><input v-model="inView" type="checkbox">仅当前视野</label></div>
   <p class="locator-count" role="status">筛选 {{filtered.length}} / 登记 {{units.length}} · 当前视野 {{visible.size}}</p>
   <p v-if="picking" class="locator-note">请先完成或取消地图选点。</p>
   <ul><li v-for="u in filtered" :key="u.id"><button type="button" :data-locate-unit="u.id" :class="[{selected:u.id===selected},u.team]" :disabled="picking" @click="choose(u.id)">
    <span class="locator-name">{{u.team==='red'?'红':'蓝'}} · {{u.name||'未命名单位'}}</span>
    <small>{{u.echelon}} · {{u.status}}<template v-if="overlap.has(u.id)"> · {{overlap.get(u.id)}}单位重叠</template><template v-else-if="u.position&&!visible.has(u.id)"> · 视野外</template></small>
    <small class="locator-id">{{u.source_id||u.id}}</small>
   </button></li></ul>
   <p v-if="!filtered.length" class="locator-note">没有匹配的已登记单位。</p>
   <footer>教学全知视图。点选仅定位并打开单位操作，不改变实际位置或到场状态；未知部署不补画坐标。</footer>
  </div>
 </section>
</template>

<style scoped>
.unit-locator{position:absolute;left:54px;top:70px;z-index:850;font-size:12px;color:#dbe6ed}
.locator-trigger{display:flex;align-items:center;gap:8px;padding:7px 11px;min-height:34px;border:1px solid #446174;border-radius:5px;background:#0c2333f5;box-shadow:0 3px 12px #06121e66;font-size:12px}
.locator-trigger b{font-variant-numeric:tabular-nums;color:#d1e9ec}.locator-trigger>span:last-child{margin-left:5px;color:#98bac4}
.locator-panel{width:min(350px,calc(100vw - 130px));max-height:min(620px,calc(100vh - 190px));display:flex;flex-direction:column;margin-top:7px;padding:12px;background:#0b2031fc;border:1px solid #416174;border-radius:6px;box-shadow:0 12px 30px #020d19a8;overflow:hidden}
header{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}header button{padding:0 7px;font-size:21px;background:transparent;border:0}
label{display:flex;gap:6px;align-items:center;color:#aec5d1;font-size:11px}.locator-panel>label{display:block}.locator-panel>label input{display:block;width:100%;margin-top:5px}
input,select{min-height:30px;border:1px solid #37596a;background:#091b29;color:#deebef;border-radius:3px;padding:4px 7px;font-size:12px}
.locator-filters{display:flex;justify-content:space-between;margin-top:8px}.locator-filters input{min-height:0;accent-color:#79bcc6}
.locator-count{color:#a4c0ca;font-size:11px;margin:9px 0}ul{padding:0;margin:0;list-style:none;overflow:auto;min-height:0;scrollbar-width:thin}li+li{border-top:1px solid #253e4f}
li button{width:100%;padding:10px 8px;border:0;border-left:2px solid transparent;background:transparent;text-align:left;display:grid;gap:4px;border-radius:0;min-height:62px}
li button:hover{background:#18384a}li button.selected{background:#23434c;border-left-color:#d9c98d}.locator-name{font-size:12px;line-height:1.4}.red .locator-name{color:#efaba7}.blue .locator-name{color:#a7caef}
small{font-size:10px;color:#a6bdc9;overflow-wrap:anywhere}.locator-id{color:#7895a5}footer,.locator-note{font-size:10px;color:#98b3c2;line-height:1.6}footer{border-top:1px solid #294657;padding-top:9px;margin-top:8px}
button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid #8bd3d4;outline-offset:1px}
@media(max-width:680px){.unit-locator{left:48px;top:68px}.locator-panel{max-height:calc(100vh - 210px)}}
</style>
