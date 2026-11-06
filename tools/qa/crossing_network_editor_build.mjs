// Compile the actual Vue editor into an isolated component harness, no API mocks.
import fs from 'node:fs';
import path from 'node:path';
import {parse,compileScript,compileStyle} from '../../frontend/node_modules/@vue/compiler-sfc/dist/compiler-sfc.esm-browser.js';
import {transform} from '../../frontend/node_modules/esbuild/lib/main.js';
const root='.cache/qa/crossing-network-ui-2026-10-29/dist';
const source=fs.readFileSync('frontend/src/components/CrossingParametersEditor.vue','utf8');
const {descriptor}=parse(source,{filename:'CrossingParametersEditor.vue'});
const code=compileScript(descriptor,{id:'data-v-network-qa',inlineTemplate:true}).content;
const compiled=await transform(code,{loader:'ts',format:'esm',target:'es2022'});
fs.writeFileSync(root+'/network-editor.js',compiled.code.replaceAll('from "vue"','from "./vue.js"').replaceAll("from 'vue'","from './vue.js'"));
fs.copyFileSync('frontend/node_modules/vue/dist/vue.esm-browser.prod.js',root+'/vue.js');
fs.writeFileSync(root+'/network-editor.css',compileStyle({source:descriptor.styles[0].content,id:'data-v-network-qa',scoped:true}).code);
const apiRoot=process.argv[2];if(!apiRoot)throw new Error('Pass isolated API evidence directory');
fs.copyFileSync(path.join(apiRoot,'parameters.json'),root+'/network-input.json');
const css=fs.readdirSync(root+'/assets').find(p=>p.endsWith('.css'));
fs.writeFileSync(root+'/network-editor.html',`<!doctype html><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>多渡点编辑器组件验证</title>
<link rel="stylesheet" href="assets/${css}"><link rel="stylesheet" href="network-editor.css"><style>body{display:block;overflow:auto;padding:20px;background:#0e2230;color:#cfdee4}#editor{max-width:1000px;margin:auto}</style><div id="editor"></div>
<script type="module">import {createApp,reactive,h} from './vue.js';import Editor from './network-editor.js';
const inputs=await(await fetch('network-input.json')).json();const state=reactive({facility:inputs.facility,rules:inputs.rules,disabled:false});
Editor.__scopeId='data-v-network-qa';window.qa=state;createApp({render:()=>h(Editor,state)}).mount('#editor');</script>`);
console.log('Actual editor compiled into isolated harness');
