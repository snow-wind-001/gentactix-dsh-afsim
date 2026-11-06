import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require=createRequire(new URL('../../frontend/package.json',import.meta.url));
const { build }=require('esbuild');
const result=await build({stdin:{contents:`export { classifyUnit } from './frontend/src/unitTypes.ts'; export { unitSymbolId } from './frontend/src/militarySymbols.ts';`,
  resolveDir:process.cwd(),loader:'ts'},bundle:true,format:'esm',platform:'node',write:false});
const module=await import('data:text/javascript;base64,'+Buffer.from(result.outputFiles[0].contents).toString('base64'));
for(const name of ['装甲','装甲排','装甲部队','armor','  ARMOR  ','坦克装甲兵']){
 assert.equal(module.classifyUnit(name)?.id,'armor');
 assert.equal(module.unitSymbolId({name:'test',type:name}),'armor');
}
for(const [name,id] of [['装甲步兵','mechanized'],['装甲侦察','recon'],['装甲运输','transport'],['反坦克','anti_tank']])
 assert.equal(module.classifyUnit(name)?.id,id);
assert.equal(module.classifyUnit('未登记的未来兵种'),undefined);
console.log('PASS shared unit-type aliases and specialist precedence');
