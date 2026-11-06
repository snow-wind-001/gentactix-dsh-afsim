/** Real editor and MapView over a captured, validated six-identity QA initial state. */
import fs from 'node:fs';import path from 'node:path';
import {build} from '../../frontend/node_modules/vite/dist/node/index.js';import vue from '../../frontend/node_modules/@vitejs/plugin-vue/dist/index.mjs';
const root=path.resolve('.cache/qa/operation-boundary-2026-11-02/editor-harness');fs.mkdirSync(root,{recursive:true});
const fixture=JSON.parse(fs.readFileSync('.cache/qa/operation-boundary-2026-11-02/afsim/case.json')).initial;
const source=path.resolve('frontend/src');
fs.writeFileSync(root+'/fixture.json',JSON.stringify(fixture));
fs.writeFileSync(root+'/main.ts',`
import {createApp,reactive,h} from '${path.resolve('frontend/node_modules/vue/dist/vue.esm-bundler.js')}';
import MapView from '${source}/components/MapView.vue';import Editor from '${source}/components/OperationBoundaryEditor.vue';
import '${path.resolve('frontend/node_modules/leaflet/dist/leaflet.css')}';import '${source}/styles.css';
const snapshot=await(await fetch('./fixture.json')).json();const p=snapshot.war_state.mission.definition.historical_calculation.parameters;
const state=reactive({config:JSON.parse(JSON.stringify(p.operation_boundary)),pending:null,events:[],snapshot});window.qa=state;
createApp({render:()=>{const snap=JSON.parse(JSON.stringify(state.snapshot));
 if(state.config)snap.war_state.mission.definition.operation_boundary=JSON.parse(JSON.stringify(state.config));else delete snap.war_state.mission.definition.operation_boundary;
 return h('div',{style:'width:100%;height:100%'},[h(MapView,{snap,selftest:false,picking:state.pending?'move':null,
 'onMap-target':point=>{const pick=state.pending;if(!pick)return;if(pick.key==='center')state.config.center=point;else state.config.routes[pick.route][pick.key]=point;state.events.push(point);state.pending=null;}}),
 h('aside',{id:'qa-editor'},[h(Editor,{modelValue:state.config,area:p.area,compatible:true,disabled:false,
 'onUpdate:modelValue':value=>state.config=value,onPick:(key,route)=>state.pending={key,route}})])]);}}).mount('#app');
`);
fs.writeFileSync(root+'/index.html','<!doctype html><html lang="zh-CN"><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>作战区编辑 QA</title><style>html,body,#app{width:100%;height:100%;margin:0}#qa-editor{position:absolute;right:12px;top:55px;width:min(380px,44vw);max-height:80vh;overflow:auto;background:#0b2033ee;padding:12px;z-index:900}.map-shell{height:100%!important}.map-toolbar{position:absolute;top:0;left:0;right:0;z-index:800}</style><div id="app"></div><script type="module" src="/main.ts"></script></html>');
await build({configFile:false,root,base:'./',plugins:[vue()],resolve:{alias:{vue:path.resolve('frontend/node_modules/vue/dist/vue.esm-bundler.js')}},build:{outDir:root+'/dist',target:'esnext',emptyOutDir:true}});
fs.copyFileSync(root+'/fixture.json',root+'/dist/fixture.json');console.log('Built actual boundary editor/map harness');
