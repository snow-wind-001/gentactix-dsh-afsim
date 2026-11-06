import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(fs.realpathSync(process.argv[2]));const {chromium}=require('playwright-core');
const root='.cache/qa/scenario-resume-2026-11-01',sid=JSON.parse(fs.readFileSync(root+'/browser-direct-review.json')).session_id;
const base='http://127.0.0.1:19132',url=base+'/api/sessions/'+sid;
const get=async path=>{const r=await fetch(path);if(!r.ok)throw Error('GET '+r.status);return r.json();};
const before=await get(url);if(before.turn_count!==0)throw Error('QA turn already executed');
const q=await get(url+'/commands');const orders=q.units.filter(u=>u.available).map(u=>({unit_id:u.id,action:'hold',duration:'next'}));
const queued=await fetch(url+'/commands',{method:'PUT',headers:{'content-type':'application/json'},body:JSON.stringify({expected_turn:q.turn,revision:q.revision,world_version:q.world_version,control_team:'red',director:true,no_fire:true,unit_agents:[],orders})});
if(!queued.ok)throw Error('Queue rejected '+await queued.text());
const afterQueue=await get(url);if(JSON.stringify(afterQueue.war_state)!==JSON.stringify(before.war_state))throw Error('Command queue changed physical state');
fs.writeFileSync(root+'/pre-turn-response.json',JSON.stringify(before));console.log('QUEUED',orders.length,'bilateral holds, no_fire');
const browser=await chromium.launch({channel:'chrome',headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});
try{
 await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19132'});
 await page.goto('http://127.0.0.1:19089/');await page.getByRole('tab',{name:/已保存战局/}).click();
 await page.locator(`[data-session-id="${sid}"] .open-battle`).click();await page.getByTestId('map-workbench').waitFor();
 if(await page.locator('.nato-marker').count()!==34)throw Error('Cold UI lacks source units');
 let result=null;page.on('response',async r=>{if(r.url()===url+'/next'&&r.request().method()==='POST')result={http:r.status(),body:await r.json()};});
 await page.getByRole('button',{name:'推进一轮',exact:true}).click();console.log('FRONTEND_ADVANCE');
 const until=Date.now()+900000;while(!result&&Date.now()<until)await new Promise(r=>setTimeout(r,1000));
 fs.writeFileSync(root+'/turn-response.json',JSON.stringify(result));if(!result||result.http!==200)throw Error('Turn incomplete/rejected: '+JSON.stringify(result?.body?.detail));
 const after=await get(url);fs.writeFileSync(root+'/post-turn-response.json',JSON.stringify(after));
 if(after.turn_count!==1)throw Error('Expected one actual turn');
 const units=[...after.war_state.red_units,...after.war_state.blue_units];if(units.length!==34)throw Error('Roster loss');
 await page.screenshot({path:root+'/browser-34-delay-after-turn.png'});
 const review={passed:true,session_id:sid,units:units.length,orders:orders.length,before_time:before.war_state.current_time,after_time:after.war_state.current_time,
  afsim_status:after.afsim?.status,returncode:after.afsim?.returncode,scope:'API bilateral holds/no_fire plus actual frontend advance; manual QA, not autonomous decisions or historical combat'};
 fs.writeFileSync(root+'/turn-review.json',JSON.stringify(review,null,2));console.log('COMPLETE',JSON.stringify(review));
}finally{await browser.close();}
