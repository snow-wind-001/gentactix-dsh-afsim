/** Read-only recovered live progress, map interaction and responsive evidence. */
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(fs.realpathSync(process.argv[2]));const {chromium}=require('playwright-core');
const root=process.argv[3]??'.cache/qa/wjl22-continuous-2026-11-02';
const apiRoot=process.env.GENTACTIX_QA_API_URL??'http://127.0.0.1:19217';
const uiRoot=process.env.GENTACTIX_QA_UI_URL??'http://127.0.0.1:19218';
if(![apiRoot,uiRoot].every(url=>/^http:\/\/127\.0\.0\.1:\d+$/.test(url)))throw Error('Owned local QA URLs required');
if(fs.existsSync(root+'/busy-review.json'))throw Error('Preserve prior browser evidence');
const sid=JSON.parse(fs.readFileSync(root+'/cases.json','utf8')).narrative;
const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];
const posts=[];page.on('request',r=>{if(r.method()==='POST')posts.push(r.url());});
page.on('pageerror',e=>errors.push(String(e)));
await page.addInitScript(({id,url})=>{window.gentactix={backendUrl:url};localStorage.setItem('gentactix-session',id);},{id:sid,url:apiRoot});
try{
 await page.goto(uiRoot);
 await page.getByTestId('map-workbench').waitFor({timeout:60000});
 const line=page.getByTestId('operation-progress');await line.waitFor();
 if(await line.getAttribute('data-state')!=='running')throw Error('Recovered operation did not show running');
 if(await line.getAttribute('role')!=='progressbar')throw Error('Running progress accessibility role absent');
 if(await page.locator('.nato-marker').count()!==22)throw Error('Recovered map missing actors');
 if(!await page.locator('.advance-button').isDisabled())throw Error('Duplicate advance enabled during operation');
 await page.locator('.leaflet-control-zoom-in').click();
 await page.screenshot({path:root+'/busy-recovered-1440.png'});
 await page.setViewportSize({width:900,height:800});
 await page.screenshot({path:root+'/busy-recovered-900.png'});
 const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);
 if(overflow||errors.length||posts.length)throw Error('Overflow, application errors or unexpected write');
 const result={passed:true,session_id:sid,markers:22,duplicate_advance_disabled:true,recovered_real_progress:true,
  map_zoom_works:true,responsive_widths:[1440,900],errors,posts,elapsed_recovery_issue:'Not verified by this test; known local elapsed reset remains open',scope:'Read-only during real in-flight turn, no mock events or new commands'};
 fs.writeFileSync(root+'/busy-review.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}catch(e){await page.screenshot({path:root+'/busy-review-failure-'+Date.now()+'.png'});console.log('FAILED',String(e));process.exitCode=1;}
finally{await browser.close();}
