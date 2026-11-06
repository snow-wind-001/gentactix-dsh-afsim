async page => {
 page.removeAllListeners('request');page.removeAllListeners('response');
 const checks=[];const check=(v,label)=>{if(!v)throw Error(label);checks.push(label);};
 page.__resumeBases=[];page.__resumeResult={status:'pending'};page.__resumeRequest=null;
 page.on('response',async r=>{
  if(r.url().includes('/api/historical-scenarios/basis?')&&r.ok())page.__resumeBases.push(await r.json());
  if(r.url().endsWith('/api/historical-scenarios/resume')&&r.request().method()==='POST')page.__resumeResult={status:'finished',http:r.status(),request:r.request().postDataJSON(),body:await r.json()};
 });
 page.on('request',r=>{if(r.url().endsWith('/api/historical-scenarios/resume')&&r.method()==='POST')page.__resumeRequest=r.postDataJSON();});
 await page.getByRole('textbox',{name:'搜索战役',exact:true}).fill('冀中');
 await page.locator('.battle-option').filter({hasText:'冀中五一反扫荡'}).click();
 await page.getByRole('button',{name:/继续配置/}).click();
 await page.locator('#draft-mode').selectOption('historical');await page.locator('#draft-executor').selectOption('afsim');
 await page.locator('[data-admission-choice="1.0.0:campaign"]').click();
 const pending=page.getByTestId('pending-historical-assemblies');await pending.waitFor();await pending.locator('summary').click();
 check((await pending.innerText()).includes('20 / 34'),'cold-reloaded-basis-shows20of34hostvalidated');
 check(await page.getByTestId('historical-validation').count()===0,'partial-has-no-validated-or-runnable-world');
 const row=pending.locator('[data-assembly-id="07030fdcace342beb7f58d9d26a6406b"]');
 const button=row.getByRole('button',{name:'继续已保存的分片配置',exact:true});
 check(await button.isDisabled(),'saved-time-step-mismatch-blocks-resume');
 await page.locator('#draft-step').selectOption('6小时');
 check(await button.isEnabled(),'saved-engine-step-endmode-and-models-match');
 check((await pending.innerText()).includes('后来改动的输入'),'resume-copy-explains-saved-input-ownership');
 await page.setViewportSize({width:1440,height:1000});await page.screenshot({path:'.cache/qa/scenario-resume-2026-11-01/browser-before-resume.png'});
 page.__resumeUi={checks,scope:'Actual frontend; QA-only revalidated old prefix, real remaining Native generation follows'};
 await button.click();
 await page.getByTestId('historical-build-progress').waitFor();
 check(page.__resumeRequest?.assembly_id==='07030fdcace342beb7f58d9d26a6406b','resume-post-uses-original-assembly');
 check(Object.keys(page.__resumeRequest).sort().join(',')==='assembly_id,operation_id','resume-does-not-resubmit-ui-parameters');
 return {...page.__resumeUi,started:true,operation_id:page.__resumeRequest.operation_id};
}
