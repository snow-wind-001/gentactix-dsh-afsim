<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import OperationProgress from './OperationProgress.vue';
import type { RuntimeProgress } from '../types';

const props = defineProps<{ tabs: { id: string; label: string; short: string }[]; activeTab: string; picking: boolean;
  busy: string; progress: RuntimeProgress; outcome: 'success' | 'failed' | 'cancelled' | null;
  error: string; cancelling: boolean; disconnected: boolean }>();
const emit = defineEmits<{ select: [id: string]; panelOpen: [] }>();
const leftOpen = ref(false), rightOpen = ref(false);
const topTab = ref<'controls' | 'status' | 'layers' | null>(null);
const lastPanel = ref<'left' | 'right' | 'top'>('top');
const topTabs = [{id:'controls',label:'推演操作'}, {id:'status',label:'目标与运行'}, {id:'layers',label:'地图图层'}] as const;
const activeTitle = computed(() => props.tabs.find(t => t.id === props.activeTab)?.label || '分析工作区');
function focusMap(focus = false) {
  leftOpen.value = false; rightOpen.value = false; topTab.value = null;
  if (focus) { emit('panelOpen'); void nextTick(() => document.querySelector<HTMLElement>('.map-workbench .map-fill')?.focus()); }
}
function prepareOpen(panel: 'left' | 'right' | 'top') {
  if (panel === 'top') { leftOpen.value = false; rightOpen.value = false; }
  else topTab.value = null;
  if (window.innerWidth < 1100) {
    if (panel !== 'left') leftOpen.value = false;
    if (panel !== 'right') rightOpen.value = false;
    if (panel !== 'top') topTab.value = null;
  }
  lastPanel.value = panel; emit('panelOpen');
}
function toggleLeft() { if (leftOpen.value) close('left'); else { prepareOpen('left'); leftOpen.value = true; } }
function toggleTop(id: 'controls' | 'status' | 'layers') {
  if (topTab.value === id) close('top'); else { prepareOpen('top'); topTab.value = id; }
}
function selectTab(id: string) {
  if (rightOpen.value && props.activeTab === id) close('right');
  else { prepareOpen('right'); emit('select', id); rightOpen.value = true; }
}
function close(panel: 'left' | 'right' | 'top') {
  const trigger = panel === 'left' ? 'left-toggle' : panel === 'right' ? 'analysis-tab-' + props.activeTab : 'top-' + topTab.value;
  if (panel === 'left') leftOpen.value = false;
  if (panel === 'right') rightOpen.value = false;
  if (panel === 'top') topTab.value = null;
  void nextTick(() => document.querySelector<HTMLElement>(`[data-testid="${trigger}"]`)?.focus());
}
function escape(event: KeyboardEvent) {
  if (event.key !== 'Escape' || event.defaultPrevented || props.picking) return;
  const target = event.target as HTMLElement;
  const panel = target.closest('[data-testid="left-panel"]') ? 'left' : target.closest('[data-testid="analysis-panel"]') ? 'right' : target.closest('[data-testid="top-panel"]') ? 'top' : lastPanel.value;
  if ((panel === 'left' && leftOpen.value) || (panel === 'right' && rightOpen.value) || (panel === 'top' && topTab.value)) {
    event.preventDefault(); event.stopPropagation(); close(panel);
  }
}
function tabKey(event: KeyboardEvent, index: number) {
  const count = props.tabs.length;
  let next = index;
  if (event.key === 'ArrowDown') next = (index + 1) % count;
  else if (event.key === 'ArrowUp') next = (index + count - 1) % count;
  else if (event.key === 'Home') next = 0;
  else if (event.key === 'End') next = count - 1;
  else return;
  event.preventDefault();
  const id = props.tabs[next].id;
  prepareOpen('right'); emit('select', id); rightOpen.value = true;
  void nextTick(() => document.getElementById('analysis-tab-' + id)?.focus());
}
watch(() => props.picking, value => { if (value) focusMap(); });
function openStatus(){prepareOpen('top');topTab.value='status';}
defineExpose({ focusMap,openAnalysis:selectTab,openStatus });
</script>

<template>
  <section class="map-workbench" data-testid="map-workbench" aria-label="地图推演工作台" @keydown="escape">
    <OperationProgress :busy="busy" :progress="progress" :outcome="outcome" :error="error" :cancelling="cancelling" :disconnected="disconnected" />
    <nav class="workbench-top-tabs" aria-label="地图上方工具">
      <button v-for="item in topTabs" :key="item.id" :data-testid="'top-' + item.id" :class="{active:topTab===item.id}"
        :aria-expanded="topTab===item.id" aria-controls="workbench-top-panel" @click="toggleTop(item.id)">{{ item.label }}<span aria-hidden="true">{{ topTab===item.id ? '⌃' : '⌄' }}</span></button>
    </nav>
    <section v-show="topTab" id="workbench-top-panel" data-testid="top-panel" class="workbench-drawer top-drawer" aria-label="地图上方工具面板">
      <header class="drawer-heading"><div><small>工作台工具</small><strong>{{ topTabs.find(t=>t.id===topTab)?.label }}</strong></div><button @click="close('top')" aria-label="向上收起工具面板">⌃</button></header>
      <div class="drawer-scroll">
        <div v-show="topTab==='controls'"><slot name="controls" /></div>
        <div v-show="topTab==='status'"><slot name="status" /></div>
        <div v-show="topTab==='layers'" id="workbench-map-tools"><slot name="layers" /></div>
      </div>
    </section>

    <nav class="workbench-left-rail" aria-label="左侧想定标签">
      <button data-testid="left-toggle" :class="{active:leftOpen}" :aria-expanded="leftOpen" aria-controls="workbench-left-panel" @click="toggleLeft"><span aria-hidden="true">☷</span><span>想定</span><span>控制</span></button>
      <button data-testid="focus-map" @click="focusMap(true)" title="收起全部面板，专注地图" aria-label="专注地图"><svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><path d="M7 3H3v4m10-4h4v4M3 13v4h4m6 0h4v-4" /></svg><span>地图</span></button>
    </nav>
    <aside v-show="leftOpen" id="workbench-left-panel" data-testid="left-panel" class="workbench-drawer left-drawer" aria-label="想定与控制">
      <header class="drawer-heading"><div><small>场景设置</small><strong>想定与控制</strong></div><button @click="close('left')" aria-label="收起想定与控制">‹</button></header>
      <div class="drawer-scroll"><slot name="left" /></div>
    </aside>

    <nav class="workbench-right-rail" role="tablist" aria-orientation="vertical" aria-label="右侧分析标签">
      <button v-for="(item,index) in tabs" :key="item.id" :id="'analysis-tab-'+item.id" :data-testid="'analysis-tab-'+item.id"
        role="tab" :class="{active:rightOpen&&activeTab===item.id}" :aria-selected="rightOpen&&activeTab===item.id" :aria-expanded="rightOpen&&activeTab===item.id"
        :tabindex="activeTab===item.id ? 0 : -1" :aria-label="item.label" :title="item.label" aria-controls="workbench-analysis-panel"
        @click="selectTab(item.id)" @keydown="tabKey($event,index)"><span>{{ item.short }}</span></button>
    </nav>
    <aside v-show="rightOpen" id="workbench-analysis-panel" data-testid="analysis-panel" class="workbench-drawer analysis-drawer" role="tabpanel" :aria-labelledby="'analysis-tab-'+activeTab">
      <header class="drawer-heading"><div><small>战局分析</small><strong>{{ activeTitle }}</strong></div><button @click="close('right')" aria-label="收起右侧分析">›</button></header>
      <div class="drawer-scroll"><slot name="analysis" /></div>
    </aside>
    <main class="workbench-canvas"><slot name="map" /></main>
    <div class="workbench-feedback"><slot name="feedback" /></div>
  </section>
</template>

<style scoped>
.map-workbench { --rail: 44px; --drawer-bg: #0b1c2b; --drawer-shadow: 0 14px 40px #020d19a8; flex: 1; min-height: 0; position: relative; overflow: hidden; isolation: isolate; }
.workbench-canvas { position: absolute; inset: 0 var(--rail); }
.workbench-canvas :deep(.map-wrap) { height: 100%; }
.workbench-top-tabs { position: absolute; top: 10px; left: 50%; transform: translateX(-50%); z-index: 900; display: flex; padding: 3px; gap: 3px; background: #0a1c2df5; border: 1px solid #355369; border-radius: 5px; box-shadow: 0 3px 14px #03101c55; max-width: calc(100% - 100px); }
.workbench-top-tabs button { display: flex; align-items: center; justify-content: center; gap: 12px; min-height: 34px; padding: 6px 15px; font-size: 12px; white-space: nowrap; border: 1px solid transparent; background: transparent; border-radius: 3px; }
.workbench-top-tabs button.active { background: #193b4b; border-color: #4c8a9a; color: #c9f1ed; }
.workbench-top-tabs button span { font-size: 16px; color: #a4bbc6; }
.workbench-left-rail, .workbench-right-rail { --tab-surface: #102536; position: absolute; top: 0; bottom: 0; width: var(--rail); z-index: 1050; background: #081a29; display: flex; flex-direction: column; align-items: stretch; gap: 6px; padding: 64px 0 8px; overflow-y: auto; scrollbar-width: thin; scrollbar-color: #365567 transparent; }
.workbench-left-rail { left: 0; border-right: 1px solid #284455; }
.workbench-right-rail { right: 0; border-left: 1px solid #284455; }
.workbench-left-rail button, .workbench-right-rail button { position: relative; isolation: isolate; flex: 0 0 auto; min-height: 54px; padding: 12px 0; border: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; background: transparent; color: #98b3c3; font-size: 12px; font-weight: 500; transition: background-color 120ms, color 120ms; }
.workbench-right-rail button { border-radius: 0 14px 14px 0; margin-right: 3px; }
.workbench-left-rail button:first-child { min-height: 96px; margin-left: 3px; border-radius: 14px 0 0 14px; }
.workbench-left-rail button > span:first-child { font-size: 18px; }
.workbench-left-rail button:last-child { margin: auto 5px 0; border-radius: 18px; font-size: 10px; }
.workbench-right-rail button:hover:not(.active), .workbench-left-rail button:hover:not(.active) { background: #152f42; color: #e0edf2; }
.workbench-right-rail button.active, .workbench-left-rail button.active { z-index: 2; background: var(--tab-surface); color: #deefef; box-shadow: inset 0 1px #3a586b, inset 0 -1px #3a586b; }
.workbench-right-rail button.active { margin-left: -1px; border-left: 1px solid var(--tab-surface); }
.workbench-left-rail button.active { margin-right: -1px; border-right: 1px solid var(--tab-surface); }
.workbench-right-rail button.active::before, .workbench-right-rail button.active::after,
.workbench-left-rail button.active::before, .workbench-left-rail button.active::after { content: ''; position: absolute; width: 10px; height: 10px; pointer-events: none; }
.workbench-right-rail button.active::before { left: 0; top: -10px; background: radial-gradient(circle at 100% 0, transparent 10px, var(--tab-surface) 10.5px); }
.workbench-right-rail button.active::after { left: 0; bottom: -10px; background: radial-gradient(circle at 100% 100%, transparent 10px, var(--tab-surface) 10.5px); }
.workbench-left-rail button.active::before { right: 0; top: -10px; background: radial-gradient(circle at 0 0, transparent 10px, var(--tab-surface) 10.5px); }
.workbench-left-rail button.active::after { right: 0; bottom: -10px; background: radial-gradient(circle at 0 100%, transparent 10px, var(--tab-surface) 10.5px); }
.workbench-drawer { position: absolute; z-index: 1000; background: #102536; border: 1px solid #385569; border-radius: 5px; box-shadow: var(--drawer-shadow); display: flex; flex-direction: column; overflow: hidden; }
.left-drawer { left: var(--rail); top: 60px; border-left: 0; border-radius: 0 10px 10px 0; bottom: 12px; width: min(330px, calc(100% - 104px)); }
.analysis-drawer { right: var(--rail); top: 60px; border-right: 0; border-radius: 10px 0 0 10px; bottom: 12px; width: min(460px, calc(100% - 104px)); }
.top-drawer { left: 50%; transform: translateX(-50%); top: 60px; width: min(840px, calc(100% - 112px)); max-height: calc(100% - 80px); }
.drawer-heading { flex: 0 0 auto; padding: 13px 16px; display: flex; align-items: center; justify-content: space-between; gap: 14px; border-bottom: 1px solid #2b4354; background: #102536; }
.drawer-heading div { display: flex; align-items: baseline; gap: 10px; min-width: 0; }
.drawer-heading small { font-size: 10px; color: #8ca9b9; white-space: nowrap; }
.drawer-heading strong { font-size: 14px; font-weight: 550; color: #e2edf2; }
.drawer-heading button { min-width: 32px; min-height: 30px; padding: 0 5px; background: transparent; color: #b5c9d2; font-size: 24px; line-height: 1; }
.drawer-scroll { flex: 1; min-height: 0; overflow: auto; overscroll-behavior: contain; scrollbar-width: thin; scrollbar-color: #3f5f71 transparent; }
.workbench-feedback { position: absolute; z-index: 1100; left: calc(var(--rail) + 12px); bottom: 12px; max-width: min(620px, calc(100% - 112px)); pointer-events: none; }
.workbench-feedback:empty { display: none; }
.workbench-canvas :deep(.leaflet-top) { top: 58px; }
.workbench-canvas :deep(.command-launch) { top: auto; bottom: 28px; right: auto; left: 12px; }
.workbench-canvas :deep(.command-panel) { top: 65px; bottom: 80px; max-height: none; right: auto; left: 12px; }
.workbench-canvas :deep(.pick-banner) { top: 62px; left: 62px; }
.workbench-drawer :deep(button), .workbench-top-tabs button, .workbench-left-rail button, .workbench-right-rail button { transition: background-color 140ms ease, border-color 140ms ease, color 140ms ease; }
.workbench-drawer :deep(:is(button,input,select,textarea,summary):focus-visible), nav button:focus-visible { outline: 2px solid #90d6cf; outline-offset: -3px; }
@media (max-width: 680px) {
  .map-workbench { --rail: 36px; }
  .workbench-top-tabs { top: 8px; max-width: calc(100% - 80px); }
  .workbench-top-tabs button { padding: 6px 7px; gap: 4px; font-size: 11px; }
  .top-drawer { top: 58px; width: calc(100% - 84px); max-height: calc(100% - 70px); }
  .left-drawer, .analysis-drawer { top: 58px; width: calc(100% - 84px); bottom: 10px; }
  .drawer-heading { padding: 10px; }
  .drawer-heading div { gap: 7px; }.drawer-heading small { display: none; }
  .workbench-right-rail button { min-height: 53px; }
  .workbench-canvas :deep(.command-panel) { left: 5px; width: calc(100% - 10px); max-width: none; top: 60px; bottom: 64px; }
  .workbench-canvas :deep(.pick-banner) { left: 5px; right: 5px; }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
</style>
