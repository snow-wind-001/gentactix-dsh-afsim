import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(fs.realpathSync(process.argv[2]));const {chromium}=require('playwright-core');
const root='.cache/qa/state-observation-map-2026-11-01',url='http://127.0.0.1:19132/api/sessions/83e8aaf89608';
const before=await(await fetch(url)).json();const browser=await chromium.launch({channel:'chrome',headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});
const mutations=[],errors=[],checks=[];page.on('request',r=>{if(r.method()!=='GET'&&r.url().startsWith('http://127.0.0.1:19132/'))mutations.push({method:r.method(),url:r.url()});});page.on('pageerror',e=>errors.push(String(e)));
const check=(v,label)=>{if(!v)throw Error(label);checks.push(label);};
try{
 await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19132'});await page.goto('http://127.0.0.1:19089/');
 await page.getByRole('tab',{name:/已保存战局/}).click();await page.locator('[data-session-id="83e8aaf89608"] .open-battle').click();
 await page.getByTestId('map-unit-locator').waitFor();check(await page.locator('.nato-marker').count()===34,'all34markersinactualworkspace');
 const trigger=page.getByTestId('map-unit-locator').locator('.locator-trigger');await trigger.click();const ids=await page.locator('[data-locate-unit]').evaluateAll(es=>es.map(e=>e.dataset.locateUnit));check(ids.length===34&&new Set(ids).size===34,'34uniquelocatorIDs');
 for(let i=0;i<ids.length;i++){
  if(i)await trigger.click();const button=page.locator('[data-locate-unit]').nth(i);const label=await button.locator('.locator-name').innerText();const name=label.slice(label.indexOf(' · ')+3);
  await button.click();await page.getByTestId('command-panel').waitFor();check((await page.getByTestId('command-panel').innerText()).includes(name),'actualcommandpanelshows '+name);
  check(await page.locator('.nato-marker.command-selected').getAttribute('data-map-unit-id')===ids[i],'highlightmatchesID '+ids[i]);
  await page.getByRole('button',{name:'收起指挥面板',exact:true}).click();
 }
 const after=await(await fetch(url)).json();check(JSON.stringify(after.war_state)===JSON.stringify(before.war_state),'all34selectionsleavephysicalworldexact');check(mutations.length===0,'unitaccessmakesnoAPIwrites');check(!errors.length,'noapplicationerrors');
 await page.screenshot({path:root+'/app-34-map-selection.png'});
 fs.writeFileSync(root+'/map-app-review.json',JSON.stringify({passed:true,checks,count:checks.length,mutations,errors,scope:'Actual application and saved34unit backend world; UI selection only, no model or physical turn'},null,2));console.log('PASS',checks.length,'actual app checks');
}catch(e){fs.writeFileSync(root+'/map-app-failure.json',JSON.stringify({error:String(e),checks,mutations,errors},null,2));await page.screenshot({path:root+'/map-app-failure.png'});throw e;}finally{await browser.close();}
