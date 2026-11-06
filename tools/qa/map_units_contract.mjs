import {createRequire} from 'node:module';
const require=createRequire(new URL('../../frontend/package.json',import.meta.url));const {build}=require('esbuild');
const result=await build({stdin:{contents:`export {mapUnitEntries,unitOverlapGroups} from './frontend/src/mapUnits.ts';`,resolveDir:process.cwd(),loader:'ts'},bundle:true,format:'esm',platform:'node',write:false});
const mod=await import('data:text/javascript;base64,'+Buffer.from(result.outputFiles[0].contents).toString('base64'));let raw='';for await(const p of process.stdin)raw+=p;
const {kind,value}=JSON.parse(raw);process.stdout.write(JSON.stringify(kind==='entries'?mod.mapUnitEntries(value):mod.unitOverlapGroups(value.points,value.width,value.height)));
