import { createRequire } from 'node:module';
const require=createRequire(new URL('../../frontend/package.json',import.meta.url));
const { build }=require('esbuild');
const result=await build({stdin:{contents:`export { resolveEngagementRadius,impactSectorVertices } from './frontend/src/tactical.ts';`,
 resolveDir:process.cwd(),loader:'ts'},bundle:true,format:'esm',platform:'node',write:false});
const m=await import('data:text/javascript;base64,'+Buffer.from(result.outputFiles[0].contents).toString('base64'));
let input='';for await(const part of process.stdin)input+=part;
const w=JSON.parse(input),u=w.red_units[2];
const ranges=['bombard','suppress','fire'].map(weapon_action=>m.resolveEngagementRadius({attacker:u.name,
 attacker_pos:[u.lat,u.lng],lat:u.lat+.04,lng:u.lng,weapon_action,radius:99999,weapon_range_m:99999},w,u.lat+.04,u.lng).radius);
process.stdout.write(JSON.stringify({ranges,sector:m.impactSectorVertices(70,125,70.03,125.08,6000)}));
