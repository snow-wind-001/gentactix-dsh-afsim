/** Post-cold runtime mass table and no-write browser inspection. */
import fs from 'node:fs';import {createRequire} from 'node:module';
const require=createRequire('/home/spikebai/.nvm/versions/node/v22.20.0/lib/node_modules/@playwright/cli/package.json'),{chromium}=require('playwright-core');
const base=process.argv[2]??'.cache/qa/personnel-rations-2026-11-03',root=base+'/readonly-browser';if(fs.existsSync(root))throw Error('Preserve evidence');fs.mkdirSync(root);
const info=JSON.parse(fs.readFileSync(base+'/'+(process.argv[3]??'t2-independent/turn-case.json'))),sid=info.session_id;
const browser=await chromium.launch({channel:'chrome',headless:true}),page=await browser.newPage({viewport:{width:1440,height:1000}}),checks=[],errors=[],writes=[];
const check=(v,m)=>{if(!v)throw Error(m);checks.push(m);};page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(!['GET','HEAD','OPTIONS'].includes(r.method()))writes.push(r.url());});
await page.addInitScript(({api,sid})=>{window.gentactix={backendUrl:api};localStorage.setItem('gentactix-session',sid);},{api:info.api,sid});
const get=async()=>{const r=await fetch(info.api+'/api/sessions/'+sid+'/export');if(!r.ok)throw Error('HTTP'+r.status);return(await r.json()).session;};
try{
 const before=await get();await page.goto(info.ui);
 const workbench=page.getByTestId('map-workbench'),savedTab=page.getByRole('tab',{name:/已保存战局/});await Promise.race([workbench.waitFor(),savedTab.waitFor()]);
 if(!await workbench.isVisible()){await savedTab.click();await page.locator(`[data-session-id="${sid}"] .open-battle`).click();}await workbench.waitFor();
 check(before.turn_count===(info.turn??2),'cold branch at retainedT'+(info.turn??2));check(before.war_state.red_units.length===4,'all four source units retained');
 await page.getByTestId('top-status').click();await page.getByTestId('resource-readiness').locator('summary').click();
 const cells=page.getByTestId('unit-ration-mass');check(await cells.count()===4,'four runtime unit mass/capacity rows');
 const text=await cells.allTextContents();check(text.every(x=>x.includes('随队0.0')&&x.includes('kg')),'depleted stock shown as0kg for every unit');
 check(text.every(x=>x.includes('0.75 kg／人日')),'same explicit per-person basis shown');
 for(const cap of ['4250.0','3600.0','4500.0','4400.0'])check(text.some(x=>x.includes(cap)),'registered carrying capacity '+cap+'kg shown');
 await page.screenshot({path:root+'/runtime-mass-1440.png'});await page.setViewportSize({width:900,height:1000});await page.screenshot({path:root+'/runtime-mass-900.png'});
 check(writes.length===0,'inspection creates no write requests');check(errors.length===0,'no application exceptions');check(JSON.stringify(before)===JSON.stringify(await get()),'entire API session unchanged by browser inspection');
 fs.writeFileSync(root+'/result.json',JSON.stringify({passed:true,checks,count:checks.length,errors,writes},null,2));console.log('PASS',checks.length,'post-cold runtime mass rows');
}catch(error){fs.writeFileSync(root+'/result.json',JSON.stringify({passed:false,error:String(error),checks,errors,writes},null,2));await page.screenshot({path:root+'/failure.png'}).catch(()=>{});throw error;}
finally{await browser.close();}
