import fs from 'node:fs';
import {parse,compileScript,compileStyle} from '../../frontend/node_modules/@vue/compiler-sfc/dist/compiler-sfc.esm-browser.js';
import {transform} from '../../frontend/node_modules/esbuild/lib/main.js';
const root='.cache/qa/support-dynamics-ui/dist';
const {descriptor}=parse(fs.readFileSync('frontend/src/components/SupportDynamicsEditor.vue','utf8'),{filename:'SupportDynamicsEditor.vue'});
const script=compileScript(descriptor,{id:'data-v-time-support',inlineTemplate:true}).content;
const compiled=await transform(script,{loader:'ts',format:'esm',target:'es2022'});
fs.writeFileSync(root+'/support-editor.js',compiled.code.replaceAll('from "vue"','from "./vue.js"'));
fs.copyFileSync('frontend/node_modules/vue/dist/vue.esm-browser.prod.js',root+'/vue.js');
fs.writeFileSync(root+'/support-editor.css',compileStyle({source:descriptor.styles[0].content,id:'data-v-time-support',scoped:true}).code);
const css=fs.readdirSync(root+'/assets').find(p=>p.endsWith('.css'));
fs.writeFileSync(root+'/support-editor.html',`<!doctype html><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>时间保障编辑器 QA</title>
<link rel="stylesheet" href="assets/${css}"><link rel="stylesheet" href="support-editor.css"><style>body{display:block;overflow:auto;padding:20px;background:#0e2230;color:#cfdee4}#editor{max-width:900px;margin:auto}</style><div id="editor"></div>
<script type="module">import {createApp,reactive,h} from './vue.js';import Editor from './support-editor.js';
const state=reactive({value:undefined,disabled:false});window.qa=state;Editor.__scopeId='data-v-time-support';
createApp({render:()=>h(Editor,{modelValue:state.value,disabled:state.disabled,'onUpdate:modelValue':value=>state.value=value})}).mount('#editor');</script>`);
console.log('Compiled actual editor into isolated harness');
