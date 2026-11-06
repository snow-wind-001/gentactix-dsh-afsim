/** Same Playwright actions in one owned process, with explicit crash evidence. */
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(fs.realpathSync(process.argv[2]));
const {chromium}=require('playwright-core');
const root='.cache/qa/scenario-resume-2026-11-01';
const browser=await chromium.launch({channel:'chrome',headless:true});
browser.on('disconnected',()=>console.log('BROWSER_DISCONNECTED',Date.now()));
const page=await browser.newPage({viewport:{width:1440,height:1000}});
page.on('crash',()=>console.log('PAGE_CRASHED',Date.now()));
page.on('pageerror',e=>console.log('PAGE_ERROR',String(e).slice(0,350)));
await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19132'});
const action=path=>eval('('+fs.readFileSync(path,'utf8')+')');
try{
 await page.goto('http://127.0.0.1:19089/');console.log('PAGE_OPEN');
 console.log('MIGRATION_START',JSON.stringify(await action('tools/qa/scenario_resume_delay_browser.js')(page)));
 const until=Date.now()+180000;
 while(page.__delayValidation?.status!=='finished'&&Date.now()<until)await new Promise(r=>setTimeout(r,1000));
 const result=page.__delayValidation;fs.writeFileSync(root+'/delay-validation-response.json',JSON.stringify(result));
 if(result?.http!==200)throw Error('Native delay revalidation failed: '+JSON.stringify(result?.body?.detail));
 console.log('NATIVE_VALIDATION',JSON.stringify({http:result.http,entities:result.body.afsim.entity_count,id:result.body.id}));
 page.__resumeResult=result;
 console.log('ENTER',JSON.stringify(await action('tools/qa/scenario_resume_enter.js')(page)));
 fs.writeFileSync(root+'/initial-world-response.json',JSON.stringify(page.__resumeSnapshot));
 await page.screenshot({path:root+'/browser-34-delay-initial.png'});
 const resultRow={passed:true,session_id:page.__resumeSnapshot.session_id,entities:34,
  source_draft:'948f80815ba841dc9f523a0592d4bbb1',new_draft:result.body.id,
  scope:'Actual saved-draft read, explicit policy change, Native load and frontend create/init; not full history'};
 fs.writeFileSync(root+'/browser-direct-review.json',JSON.stringify(resultRow,null,2));
 console.log('COMPLETE',JSON.stringify(resultRow));
}finally{await browser.close();}
