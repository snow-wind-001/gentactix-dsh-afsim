/** Observe an actually running DSH operation through the normal app. */
import fs from 'node:fs';import {createRequire} from 'node:module';
const require=createRequire(fs.realpathSync(process.argv[2]));const {chromium}=require('playwright-core');
const root='.cache/qa/boundary-lifecycle-2026-11-02',api='http://127.0.0.1:19140/api';
const sid=JSON.parse(fs.readFileSync(root+'/controlled/narrative/case.json')).session_id;
const browser=await chromium.launch({channel:'chrome',headless:true}),page=await browser.newPage();
const errors=[],writes=[],checks=[];page.on('pageerror',e=>errors.push(String(e)));
page.on('request',r=>{if(r.url().startsWith(api)&&r.method()!=='GET')writes.push(r.url());});
const get=async()=>await(await fetch(`${api}/sessions/${sid}/progress`)).json();
try{
 const before=await get();if(!before.active)throw Error('No confirmed live operation; this probe is not a simulated progress demo');
 await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19140'});
 await page.goto('http://127.0.0.1:19089/');await page.getByRole('tab',{name:/已保存战局/}).click();
 await page.locator(`[data-session-id="${sid}"] .open-battle`).click();
 await page.locator('[data-testid="operation-progress"][data-state="running"]').waitFor();checks.push('actual running state recovered');
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});
  const line=page.getByTestId('operation-progress');if(!await line.isVisible())throw Error('actual progress line not visible');
  if(!await page.getByTestId('operation-elapsed').isVisible())throw Error('elapsed time missing');
  checks.push(width+' actual colored progress and elapsed visible');await page.screenshot({path:`${root}/actual-progress-${width}.png`});
 }
 const after=await get();if(errors.length||writes.length)throw Error('browser error or unrequested API mutation');
 fs.writeFileSync(root+'/progress-browser.json',JSON.stringify({passed:true,session_id:sid,checks,errors,writes,
   active_before:before.active,active_after:after.active,scope:'Actual in-flight model operation, read-only UI; not uninterrupted full-history stability'},null,2));
 console.log('PASS actual live model progress UI');
}catch(error){fs.writeFileSync(root+'/progress-browser-failure.json',JSON.stringify({error:String(error),errors,writes,checks},null,2));throw error;}
finally{await browser.close();}
