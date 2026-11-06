import fs from 'node:fs';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(process.env.PLAYWRIGHT_PACKAGE || import.meta.url);
const {chromium}=require('playwright-core');
const out=process.env.QA_OUTPUT||'.cache/qa/map-path-focus',tag=process.env.QA_TAG||'check',ui=process.env.QA_UI_URL,api=process.env.QA_API_URL,sid=process.env.QA_SESSION_ID;assert(ui&&api&&sid,'Set isolated QA_UI_URL, QA_API_URL and a22-unit QA_SESSION_ID');fs.mkdirSync(out,{recursive:true});
let browser,page;const checks=[],errors=[],posts=[];
const check=(value,label)=>{assert(value,label);checks.push(label);};
try{
 browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_EXECUTABLE?{executablePath:process.env.PLAYWRIGHT_EXECUTABLE}:{}),args:['--no-sandbox','--disable-dev-shm-usage']});
 page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(30000);
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST'&&r.url().includes('/api/'))posts.push(new URL(r.url()).pathname);});
 await page.addInitScript(({api,sid})=>{window.gentactix={backendUrl:api};localStorage.setItem('gentactix-session',sid);},{api,sid});
 await page.goto(ui);
 await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
 await page.locator('.nato-marker').nth(21).waitFor();
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});await page.waitForTimeout(400);
  const hits=await page.evaluate(()=>{
   for(const e of document.querySelectorAll('[data-qa-path]'))delete e.dataset.qaPath;
   const r=document.querySelector('.map-fill').getBoundingClientRect(),found=new Map();
   for(let y=Math.max(120,r.top+20);y<Math.min(innerHeight-40,r.bottom-20);y+=12)
    for(let x=Math.max(65,r.left+20);x<Math.min(innerWidth-65,r.right-20);x+=12){
     const e=document.elementFromPoint(x,y);
     if(e?.matches('path.leaflet-interactive')&&!found.has(e))found.set(e,{x,y,large:e.getBoundingClientRect().width>150});
    }
   return [...found.entries()].sort((a,b)=>Number(b[1].large)-Number(a[1].large)).slice(0,6).map(([element,hit],index)=>{element.dataset.qaPath=String(index);return{...hit,id:String(index)};});
  });check(hits.length>0,width+' actual clickable range/goal paths found');
  for(const [index,hit]of hits.entries()){
   await page.mouse.click(hit.x,hit.y);
   // Reproduce the SVG focus state observed in installed Electron. Some
   // headless Chromium builds leave pointer-clicked SVG paths unfocused.
   await page.locator(`path[data-qa-path="${hit.id}"]`).evaluate(e=>{e.setAttribute('tabindex','0');e.focus();});
   const active=await page.evaluate(()=>{const e=document.activeElement,s=getComputedStyle(e),r=e.getBoundingClientRect();return{tag:e.tagName,classes:e.getAttribute('class'),outline:s.outlineStyle,focusVisible:e.matches(':focus-visible'),width:r.width,height:r.height};});
   check(active.tag==='path',width+' pointer focused actual SVG path '+index);
   check(!active.focusVisible,width+' pointer focus distinguished from keyboard '+index);
   await page.screenshot({path:out+'/map-focus-'+tag+'-'+width+'.png',fullPage:true});
   check(active.outline==='none',width+' pointer never draws a rectangular path focus outline '+index);
  }
  const keyboard=await page.evaluate(()=>{const e=document.activeElement;e.dataset.qaFocus='last';return e.getAttribute('tabindex');});
  check(keyboard==='0',width+' explicitly focusable QA SVG exercises keyboard path');
  await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab');
  const focus=await page.evaluate(()=>{const e=document.activeElement,s=getComputedStyle(e);return{same:e.dataset.qaFocus==='last',visible:e.matches(':focus-visible'),outline:s.outlineStyle,filter:s.filter};});
  await page.screenshot({path:out+'/map-focus-'+tag+'-'+width+'-keyboard.png',fullPage:true});
  check(focus.same&&focus.visible&&focus.outline==='none',width+' keyboard focus never draws a rectangular path outline');
  check(focus.filter.includes('drop-shadow'),width+' keyboard focus follows the actual path geometry');
  for(const direction of ['in','out']){
   await page.locator('.leaflet-control-zoom-'+direction).click();
   await page.waitForTimeout(400);
   await page.locator('path[data-qa-path]').last().evaluate(e=>e.focus());
   await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab');
   const zoomFocus=await page.evaluate(()=>{const e=document.activeElement,s=getComputedStyle(e);return{path:e.matches('path.leaflet-interactive'),visible:e.matches(':focus-visible'),outline:s.outlineStyle,filter:s.filter};});
   check(zoomFocus.path&&zoomFocus.visible&&zoomFocus.outline==='none'&&zoomFocus.filter.includes('drop-shadow'),width+' zoom '+direction+' retains geometric keyboard focus without a box');
  }
  check(await page.locator('.nato-marker').count()===22,width+' all unit markers retained');
 }
 check(posts.length===0,'display-only test never submits or advances the world');check(errors.length===0,'no renderer error');
 fs.writeFileSync(out+'/map-focus-'+tag+'.json',JSON.stringify({passed:true,checks,posts,errors,qa_focus_reproduction:'Headless Chromium path explicitly receives tabindex=0 to reproduce actual installed Electron focused SVG; no world/data mock',scope:'Real frontend with unchanged22-unit QA case, pointer and keyboard SVG focus styles only'},null,2));
 console.log('PASS',checks.length,'pointer/key focus checks');
}catch(e){fs.writeFileSync(out+'/map-focus-'+tag+'-failure.json',JSON.stringify({error:String(e),checks,posts,errors},null,2));console.error(String(e));process.exitCode=1;}
finally{if(browser)await browser.close();}
