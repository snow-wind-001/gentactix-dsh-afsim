async page => {
 page.removeAllListeners('request');page.removeAllListeners('response');
 page.__resumeResult={status:'pending'};page.__resumeRequest=null;
 page.on('request',r=>{if(r.url().endsWith('/api/historical-scenarios/resume')&&r.method()==='POST')page.__resumeRequest=r.postDataJSON();});
 page.on('response',async r=>{if(r.url().endsWith('/api/historical-scenarios/resume')&&r.request().method()==='POST')page.__resumeResult={status:'finished',http:r.status(),request:r.request().postDataJSON(),body:await r.json()};});
 const row=page.locator('[data-assembly-id="07030fdcace342beb7f58d9d26a6406b"]');
 if(!(await row.innerText()).includes('20 / 34'))throw Error('Expected original validated prefix');
 await page.screenshot({path:'.cache/qa/scenario-resume-2026-11-01/browser-explicit-rebuild.png'});
 await row.getByRole('button',{name:'重建失败分片会话并继续',exact:true}).click();
 await page.getByTestId('historical-build-progress').waitFor();
 if(page.__resumeRequest?.rebuild_failed_session!==true)throw Error('Must be explicitly requested, never silent');
 return {operation_id:page.__resumeRequest.operation_id,explicit_rebuild:true,retained_validated_actors:20,
  scope:'Real model remaining14units after QA revalidation import; not independent full34generation'};
}
