/** Read-only review of the actual mixed human/Native AFSIM frame. */
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire('/home/spikebai/.nvm/versions/node/v22.20.0/lib/node_modules/@playwright/cli/package.json');
const {chromium}=require('playwright-core');
const base=process.argv[2],ui=process.argv[3],attempt=process.argv[4];
if(!base||!ui||!/^[a-z0-9-]+$/.test(attempt))throw Error('Require evidence root, UI and unused attempt');
const root=base+'/afsim/'+attempt;if(fs.existsSync(root))throw Error('Preserve earlier evidence');fs.mkdirSync(root);
const info=JSON.parse(fs.readFileSync(base+'/afsim/case.json'));
const url=info.api+'/api/sessions/'+info.session_id;
async function get(path){const response=await fetch(url+path);if(!response.ok)throw Error('Read failed '+response.status);return response.json();}
const checks=[],writes=[],errors=[];const check=(v,m)=>{if(!v)throw Error(m);checks.push(m);};
const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
page.on('pageerror',e=>errors.push(e.message));
page.on('request',r=>{if(['POST','PUT','PATCH','DELETE'].includes(r.method()))writes.push(new URL(r.url()).pathname);});
await page.addInitScript(i=>{window.gentactix={backendUrl:i.api};localStorage.setItem('gentactix-session',i.session_id);},info);
try{
 const before=(await get('/export')).session,progress=await get('/progress');
 check(!progress.active,'the actual committed AFSIM frame is idle');
 const decisions=before.trajectory.at(-1).decisions.filter(d=>d.source==='native_unit_agent');
 check(decisions.length===2&&decisions.every(d=>d.proposal?.source==='dsh_native_unit_order_tool'),'both actual unit Agent submissions are retained');
 check(before.war_state.afsim.model_skipped===true,'the same frame skipped only its extra global planner');
 await page.goto(ui,{waitUntil:'domcontentloaded'});
 const work=page.getByTestId('map-workbench'),saved=page.getByRole('tab',{name:/已保存战局/});
 await Promise.race([work.waitFor(),saved.waitFor()]);
 if(!await work.isVisible()){await saved.click();await page.locator(`[data-session-id="${info.session_id}"] .open-battle`).click();}
 await work.waitFor();await page.getByRole('button',{name:/^目标与运行/}).click();
 const panel=page.getByTestId('afsim-status');await panel.waitFor();
 const text=await panel.innerText();
 check(text.includes('未额外调用全局规划模型')&&text.includes('单位Agent的调用见决策记录'),'current UI distinguishes global planning from unit Agent calls');
 check(!text.includes('人工命令完整')&&!text.includes('未调用模型。'),'current UI removes the false all-manual/no-model claim');
 for(const width of [1440,900]){await page.setViewportSize({width,height:1000});await page.screenshot({path:root+'/status-'+width+'.png'});}
 check(writes.length===0,'read-only review submits no mutations');
 check(JSON.stringify((await get('/export')).session)===JSON.stringify(before),'complete typed world and trajectory stay unchanged');
 check(JSON.stringify(await get('/progress'))===JSON.stringify(progress),'operation state stays unchanged');
 check(errors.length===0,'no application exceptions');
 fs.writeFileSync(root+'/result.json',JSON.stringify({passed:true,checks,writes,errors,session_id:info.session_id,turn:before.turn_count,ui,text,scope:'Read-only actual mixed Agent/human frame, not a new physical or model run.'},null,2));
 console.log('PASS',checks.length,'read-only mixed-Agent execution label checks');
}catch(error){fs.writeFileSync(root+'/result.json',JSON.stringify({passed:false,error:String(error),checks,writes,errors},null,2));throw error;}
finally{await browser.close();}
