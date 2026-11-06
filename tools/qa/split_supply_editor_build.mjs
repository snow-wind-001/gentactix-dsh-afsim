import fs from 'node:fs';
import {parse,compileScript,compileStyle} from '../../frontend/node_modules/@vue/compiler-sfc/dist/compiler-sfc.esm-browser.js';
import {transform} from '../../frontend/node_modules/esbuild/lib/main.js';
const root='.cache/qa/split-supply-ui/dist';
const {descriptor}=parse(fs.readFileSync('frontend/src/components/SplitSupplyEditor.vue','utf8'),{filename:'SplitSupplyEditor.vue'});
const script=compileScript(descriptor,{id:'data-v-split-supply',inlineTemplate:true}).content;
const compiled=await transform(script,{loader:'ts',format:'esm',target:'es2022'});
fs.writeFileSync(root+'/split-editor.js',compiled.code.replaceAll('from "vue"','from "./vue.js"'));
fs.copyFileSync('frontend/node_modules/vue/dist/vue.esm-browser.prod.js',root+'/vue.js');
fs.writeFileSync(root+'/split-editor.css',compileStyle({source:descriptor.styles[0].content,id:'data-v-split-supply',scoped:true}).code);
const css=fs.readdirSync(root+'/assets').find(p=>p.endsWith('.css'));
fs.writeFileSync(root+'/split-editor.html',`<!doctype html><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>分类补给编辑器 QA</title>
<link rel="stylesheet" href="assets/${css}"><link rel="stylesheet" href="split-editor.css"><style>body{display:block;overflow:auto;padding:20px;background:#0e2230;color:#cfdee4}#editor{max-width:900px;margin:auto}</style><div id="editor"></div>
<script type="module">import {createApp,reactive,h} from './vue.js';import Editor from './split-editor.js';
const state=reactive({value:undefined,disabled:false});window.qa=state;Editor.__scopeId='data-v-split-supply';
createApp({render:()=>h(Editor,{modelValue:state.value,disabled:state.disabled,'onUpdate:modelValue':value=>state.value=value})}).mount('#editor');</script>`);
console.log('Compiled actual editor into isolated harness');
