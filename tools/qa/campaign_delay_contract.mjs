import { createRequire } from 'node:module';
const require=createRequire(new URL('../../frontend/package.json',import.meta.url));
const {build}=require('esbuild');
const result=await build({stdin:{contents:`export {historicalCampaignGoalAllowed} from './frontend/src/historicalGoals.ts';`,resolveDir:process.cwd(),loader:'ts'},bundle:true,format:'esm',platform:'node',write:false});
const module=await import('data:text/javascript;base64,'+Buffer.from(result.outputFiles[0].contents).toString('base64'));
let input='';for await(const part of process.stdin)input+=part;
process.stdout.write(JSON.stringify(JSON.parse(input).map(p=>module.historicalCampaignGoalAllowed(p.parameters??p,p.interaction))));
