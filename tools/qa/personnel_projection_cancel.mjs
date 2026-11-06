/** Stop only the owned full22 QA round after its existing one-hour test deadline. */
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(fs.realpathSync(process.argv[2]));
const {chromium}=require('playwright-core');
const base='.cache/qa/personnel-projection-2026-11-02';
const root=base+'/deadline-cancel';
if(fs.existsSync(root))throw Error('Preserve prior cancellation evidence');
const samples=fs.readFileSync(base+'/real-ui-t2/progress.jsonl','utf8').trim().split('\n').map(JSON.parse);
if(samples.at(-1).seconds<3580)throw Error('Do not stop the real round before its existing one-hour QA deadline');
const sid=JSON.parse(fs.readFileSync(base+'/case.json','utf8')).session_id;
const before=JSON.parse(fs.readFileSync(base+'/branch-pre-advance.json','utf8'));
const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const api='http://127.0.0.1:19227/api/sessions/'+sid;
const get=async path=>{const r=await page.request.get(api+path);if(!r.ok())throw Error('HTTP '+r.status());return r.json();};
const errors=[],posts=[];
page.on('pageerror',e=>errors.push(e.message));
page.on('request',r=>{if(r.method()==='POST')posts.push(r.url());});
fs.mkdirSync(root);
await page.addInitScript(id=>{window.gentactix={backendUrl:'http://127.0.0.1:19227'};localStorage.setItem('gentactix-session',id);},sid);
try{
 const progress=await get('/progress');
 if(!progress.active){
  fs.writeFileSync(root+'/result.json',JSON.stringify({cancelled:false,already_terminal:true,progress},null,2));
  console.log('Already terminal; no cancellation or repeated advance');
 }else{
  const start=(await get('/export')).session;
  if(start.turn_count!==1||JSON.stringify(start.war_state)!==JSON.stringify(before.war_state))throw Error('Owned T1 checkpoint changed; refuse cancellation');
  await page.goto('http://127.0.0.1:19238');
  await page.getByTestId('map-workbench').waitFor({timeout:60000});
  await page.screenshot({path:root+'/before.png'});
  const pending=page.waitForResponse(r=>r.url()===api+'/cancel'&&r.request().method()==='POST');
  const began=Date.now();await page.getByRole('button',{name:'取消',exact:true}).click();
  const response=await pending,body=await response.json();
  fs.writeFileSync(root+'/response.json',JSON.stringify({status:response.status(),body},null,2));
  if(!response.ok()||!body.runtime?.some(r=>r.ok))throw Error('Native cancellation was not acknowledged');
  let current;
  // The failure artifact is persisted after the active observer is cleared.
  // Wait for this operation's terminal record, not just an inactive flag.
  do{current=await get('/progress');if(!current.active&&current.failed_operation?.operation_id===progress.operation_id)break;await page.waitForTimeout(300);}while(Date.now()-began<60000);
  if(current.active||current.failed_operation?.operation_id!==progress.operation_id)throw Error('Operation or its failure audit did not terminate after cancellation');
  const after=(await get('/export')).session;
  fs.writeFileSync(root+'/after.json',JSON.stringify(after,null,2));
  const unchanged=Object.fromEntries(['war_state','command_state','turn_count','history','trajectory'].map(k=>[k,JSON.stringify(after[k])===JSON.stringify(before[k])]));
  if(!Object.values(unchanged).every(Boolean))throw Error('Cancellation changed committed state '+JSON.stringify(unchanged));
  const failure=after.failed_operations.at(-1);
  if(!failure?.cancelled||failure.operation_id!==progress.operation_id)throw Error('Actual operation failure evidence missing');
  if(posts.length!==1||posts[0]!==api+'/cancel'||errors.length)throw Error('Unexpected write or page error');
  await page.screenshot({path:root+'/after.png'});
  fs.writeFileSync(root+'/result.json',JSON.stringify({passed:true,cancelled:true,session_id:sid,
   operation_id:progress.operation_id,seconds:(Date.now()-began)/1000,unchanged,posts,errors,
   full_T2_passed:false,scope:'Actual UI cancellation after the owned one-hour QA deadline; not a completed T2 or historical acceptance'},null,2));
  console.log('PASS actual Native cancellation and full committed-state preservation; full T2 FAILED deadline');
 }
}catch(e){fs.writeFileSync(root+'/failure.json',JSON.stringify({passed:false,error:String(e),errors,posts},null,2));throw e;}
finally{await browser.close();}
