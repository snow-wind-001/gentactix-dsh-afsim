import {createRequire} from 'node:module';
const require=createRequire(new URL('../../frontend/package.json',import.meta.url));const {build}=require('esbuild');
const code=`export {personnelStrengthPct,unitInactive} from './frontend/src/personnelProjection.ts';export {unitPopup} from './frontend/src/tactical.ts';export {unitMilitaryHtml} from './frontend/src/militarySymbols.ts';`;
const result=await build({stdin:{contents:code,resolveDir:process.cwd(),loader:'ts'},bundle:true,format:'esm',platform:'node',write:false});
const mod=await import('data:text/javascript;base64,'+Buffer.from(result.outputFiles[0].contents).toString('base64'));
let raw='';for await(const part of process.stdin)raw+=part;
process.stdout.write(JSON.stringify(JSON.parse(raw).map(u=>({percent:mod.personnelStrengthPct(u),inactive:mod.unitInactive(u),popup:mod.unitPopup(u),symbol:mod.unitMilitaryHtml(u,'red')}))));
