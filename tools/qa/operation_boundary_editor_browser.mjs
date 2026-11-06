import fs from 'node:fs';import {createRequire} from 'node:module';
const require=createRequire(fs.realpathSync(process.argv[2]));const {chromium}=require('playwright-core');
const root='.cache/qa/operation-boundary-2026-11-02';const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage();const checks=[],errors=[];page.on('pageerror',e=>errors.push(String(e)));
const check=(v,label)=>{if(!v)throw Error(label);checks.push(label);};
try{
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:19138/');await page.getByTestId('operation-boundary-editor').waitFor();
  const before=await page.evaluate(()=>JSON.stringify(window.qa.snapshot));check(await page.locator('.nato-marker').count()===6,width+' initial6units');
  check(await page.locator('.operation-boundary').count()===1,width+' initial boundary');
  const enabled=page.getByRole('checkbox',{name:'启用作战区边界'});await enabled.uncheck();check(await page.locator('.operation-boundary').count()===0,width+' explicit disable removes preview only');
  await enabled.check();check(await page.locator('.operation-boundary').count()===1,width+' enabling draws new draft boundary');
  const radius=page.getByRole('spinbutton',{name:'作战区半径',exact:true});await radius.fill('');
  check(await page.locator('.operation-boundary').count()===0,width+' incomplete number does not crash map');await radius.fill('2.8');
  check(await page.locator('.operation-boundary').count()===1,width+' corrected number redraws draft');
  await page.getByRole('button',{name:'增加出入通路',exact:true}).click();check(await page.locator('.operation-route').count()===2,width+' adds separately identified route');
  await page.getByRole('button',{name:'移除通路',exact:true}).last().click();check(await page.locator('.operation-route').count()===1,width+' removes candidate route');
  await page.getByRole('button',{name:'地图设置区外点',exact:true}).click();await page.locator('.map-fill').click({position:{x:120,y:240}});
  check(await page.evaluate(()=>window.qa.events.length)===1,width+' map point event updates selected route endpoint');
  check(await page.evaluate(()=>window.qa.pending===null),width+' completed pick clears selection');
  check(await page.evaluate(()=>JSON.stringify(window.qa.snapshot))===before,width+' candidate editing does not modify actual initial world');
  await page.screenshot({path:root+'/editor-'+width+'.png'});
 }
 check(!errors.length,'no editor/map application errors');
 fs.writeFileSync(root+'/editor-browser-review.json',JSON.stringify({passed:true,checks,count:checks.length,errors,scope:'Actual editor and MapView with captured QA input; component event wiring, not full composer revalidation'},null,2));console.log('PASS',checks.length,'editor checks');
}catch(e){fs.writeFileSync(root+'/editor-browser-failure.json',JSON.stringify({error:String(e),checks,errors},null,2));await page.screenshot({path:root+'/editor-browser-failure.png'});throw e;}finally{await browser.close();}
