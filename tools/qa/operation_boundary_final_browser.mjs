/** Read-only normal UI review of both cold-restored execution backends. */
import fs from 'node:fs';import {createRequire} from 'node:module';
const require=createRequire(fs.realpathSync(process.argv[2]));const {chromium}=require('playwright-core');
const root='.cache/qa/operation-boundary-2026-11-02';const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage();const checks=[],errors=[],writes=[];page.on('pageerror',e=>errors.push(String(e)));
page.on('request',r=>{if(r.url().startsWith('http://127.0.0.1:19136/')&&r.method()!=='GET')writes.push({method:r.method(),url:r.url()});});
const check=(v,label)=>{if(!v)throw Error(label);checks.push(label);};
try{
 await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19136'});
 for(const engine of ['afsim','narrative'])for(const width of [1440,900]){
  const fixture=JSON.parse(fs.readFileSync(root+'/'+engine+'/case.json')),sid=fixture.session_id,url='http://127.0.0.1:19136/api/sessions/'+sid;
  const before=await(await fetch(url)).json();await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:19089/');
  await page.getByRole('tab',{name:/已保存战局/}).click();await page.locator(`[data-session-id="${sid}"] .open-battle`).click();
  await page.getByTestId('map-unit-locator').waitFor();check(await page.locator('.nato-marker').count()===6,engine+width+' all6units');
  check(await page.locator('.operation-boundary').count()===1,engine+width+' circle visible');check(await page.locator('.operation-route').count()===1,engine+width+' registered route visible');
  await page.getByTestId('map-unit-locator').locator('.locator-trigger').click();await page.getByRole('searchbox',{name:'地图单位搜索'}).fill('第159师');await page.locator('[data-locate-unit]').click();
  const status=await page.getByTestId('unit-participation-status').innerText();check(status.includes(engine==='afsim'?'场外待命':'在场作战'),engine+width+' actual participation state');
  check(status.includes(engine==='afsim'?'作战区外':'作战区内'),engine+width+' position zone label');
  const after=await(await fetch(url)).json();check(JSON.stringify(after.war_state)===JSON.stringify(before.war_state),engine+width+' view preserves entire world');
  await page.screenshot({path:root+'/final-'+engine+'-'+width+'.png'});
 }
 check(!writes.length,'no actual API writes');check(!errors.length,'no browser application errors');
 fs.writeFileSync(root+'/final-browser-review.json',JSON.stringify({passed:true,checks,count:checks.length,errors,writes,scope:'Normal app/both cold restored worlds1440/900 read-only access; NativeT13offmap,DSHT12returned'},null,2));console.log('PASS',checks.length,'final browser checks');
}catch(e){fs.writeFileSync(root+'/final-browser-failure.json',JSON.stringify({error:String(e),checks,errors,writes},null,2));await page.screenshot({path:root+'/final-browser-failure.png'});throw e;}finally{await browser.close();}
