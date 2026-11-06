/** Verify an already committed UI round read-only; never retry /next after QA failure. */
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(fs.realpathSync(process.argv[2]));const {chromium}=require('playwright-core');
const base='.cache/qa/movement-feedback-2026-11-02/live22';
const original=base+'/dsh-t1',root=base+'/dsh-t1-review';
if(fs.existsSync(root))throw Error('Preserve prior terminal review');fs.mkdirSync(root);
const before=JSON.parse(fs.readFileSync(original+'/before.json','utf8'));
const after=JSON.parse(fs.readFileSync(original+'/after.json','utf8'));
const response=JSON.parse(fs.readFileSync(original+'/response.json','utf8'));
const failure=JSON.parse(fs.readFileSync(original+'/result.json','utf8'));
if(response.status!==200||after.turn_count!==before.turn_count+1)throw Error('Original UI advance was not successful');
const sid=failure.session_id;
const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[],posts=[];
page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST')posts.push(r.url());});
await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19227'});
try{
 const current=await(await page.request.get('http://127.0.0.1:19227/api/sessions/'+sid+'/export')).json();
 if(JSON.stringify(current.session.war_state)!==JSON.stringify(after.war_state))throw Error('World changed after original commit');
 await page.goto('http://127.0.0.1:19228');
 await page.getByRole('tab',{name:/已保存战局/}).click();
 await page.locator(`[data-session-id="${sid}"] .open-battle`).click();
 await page.getByTestId('map-workbench').waitFor({timeout:60000});
 if(await page.locator('.nato-marker').count()!==22)throw Error('Missing map actors');
 if(after.war_state.dsh_execution?.movement?.units.length!==22)throw Error('Incomplete movement receipt');
 await page.screenshot({path:root+'/after-1440.png'});await page.setViewportSize({width:900,height:1000});
 await page.screenshot({path:root+'/after-900.png'});
 if(await page.locator('.nato-marker').count()!==22||errors.length||posts.length)throw Error('Read-only UI regression');
 for(const name of ['before.json','after.json','response.json'])fs.copyFileSync(original+'/'+name,root+'/'+name);
 fs.writeFileSync(root+'/result.json',JSON.stringify({passed:true,session_id:sid,turn:after.turn_count,seconds:response.seconds,
  markers:22,native_proposals:after.trajectory.at(-1).decisions.filter(d=>d.source==='native_unit_agent').map(d=>d.proposal),
  motion_version:'movement-feedback-1',faults:errors,posts,original_browser_script_error:failure.error,
  original_evidence:original,scope:'Original real UI round committed; separate terminal read-only browser review, no repeated advance; not historical calibration'},null,2));
 console.log('PASS original UI commit and independent terminal22 browser review; original QA failure retained');
}catch(e){fs.writeFileSync(root+'/failure.json',JSON.stringify({passed:false,error:String(e),errors,posts},null,2));throw e;}
finally{await browser.close();}
