/** Builds the actual MapView against captured real22/34unit snapshots. */
import fs from 'node:fs';
import path from 'node:path';
import {build} from '../../frontend/node_modules/vite/dist/node/index.js';
import vue from '../../frontend/node_modules/@vitejs/plugin-vue/dist/index.mjs';
const out=path.resolve('.cache/qa/state-observation-map-2026-11-01/map-harness');fs.mkdirSync(out,{recursive:true});
const fixture22=JSON.parse(fs.readFileSync('.cache/qa/fixed-parameters-2026-11-01/campaign-turn-responses.json')).initial;
const fixture34=JSON.parse(fs.readFileSync('.cache/qa/scenario-resume-2026-11-01/fresh-post-turn-response.json'));
fs.writeFileSync(out+'/fixtures.json',JSON.stringify({22:fixture22,34:fixture34}));
const source=path.resolve('frontend/src');
fs.writeFileSync(out+'/main.ts',`
import {createApp,reactive,h} from '${path.resolve('frontend/node_modules/vue/dist/vue.esm-bundler.js')}';
import MapView from '${source}/components/MapView.vue';import '${path.resolve('frontend/node_modules/leaflet/dist/leaflet.css')}';import '${source}/styles.css';
const fixtures=await(await fetch('./fixtures.json')).json();const count=new URL(location.href).searchParams.get('count')||'22';
const state=reactive({snap:fixtures[count],selection:null as {team:string;name:string}|null,events:[],picking:null});window.qa=state;
createApp({render:()=>h(MapView,{snap:state.snap,selftest:false,selectedUnit:state.selection,picking:state.picking,
 'onUnit-select':(team:string,name:string)=>{state.selection={team,name};state.events.push({team,name});}})}).mount('#app');
`);
fs.writeFileSync(out+'/index.html','<!doctype html><html lang="zh-CN"><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>实际战局标图 QA</title><style>html,body,#app{width:100%;height:100%;margin:0}.map-shell{height:100%!important}.map-toolbar{position:absolute;top:0;left:0;right:0;z-index:800}</style><div id="app"></div><script type="module" src="/main.ts"></script></html>');
await build({configFile:false,root:out,base:'./',plugins:[vue()],resolve:{alias:{vue:path.resolve('frontend/node_modules/vue/dist/vue.esm-bundler.js')}},build:{outDir:path.join(out,'dist'),target:'esnext',emptyOutDir:true}});
fs.copyFileSync(out+'/fixtures.json',out+'/dist/fixtures.json');console.log('Built actual MapView harness',out+'/dist');
