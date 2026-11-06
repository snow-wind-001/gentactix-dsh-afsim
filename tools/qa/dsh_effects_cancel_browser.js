async page=>{
 const checks=[],check=(v,s)=>{if(!v)throw new Error(s);checks.push(s);};
 const sid='247d1dcbe874',base='http://127.0.0.1:18998/api/sessions/'+sid;
 const before=await(await page.request.get(base)).json();
 await page.context().addInitScript(sid=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.setItem('gentactix-session',sid);},sid);
 await page.goto('http://127.0.0.1:18981/?qa=restored-cancel');
 await page.getByTestId('map-workbench').waitFor();
 const cancel=page.getByRole('button',{name:'取消',exact:true});await cancel.waitFor();
 let state;
 for(let i=0;i<80;i++){
  state=await(await page.request.get(base+'/progress')).json();
  if(state.active&&state.progress.steps>=1)break;
  if(!state.active)throw new Error('Task ended before cancellation test');
  await page.waitForTimeout(100);
 }
 check(state.active&&state.progress.steps>=1,'confirmed live native model operation after page restoration');
 check(await page.getByRole('button',{name:'推进一轮',exact:true}).isDisabled(),'restored active operation disables duplicate advancement');
 check(await cancel.isVisible(),'restored native cancellation is visible');
 await page.screenshot({path:'.cache/qa/dsh-effects/active-after.png'});
 const pending=page.waitForResponse(r=>r.url().endsWith('/cancel')&&r.request().method()==='POST');
 await cancel.click();const response=await pending,answer=await response.json();
 check(response.status()===200&&answer.runtime.some(r=>r.ok),'actual runtime acknowledges cancellation');
 await page.waitForFunction(()=>!document.querySelector('.desktop-root.operation-running'),{},{timeout:60000});
 const after=await(await page.request.get(base)).json(),progress=await(await page.request.get(base+'/progress')).json();
 check(!progress.active&&progress.failed_operation.operation_id===state.operation_id&&progress.failed_operation.cancelled,'server reports matching cancelled operation');
 check(JSON.stringify(after.war_state)===JSON.stringify(before.war_state),'native cancellation preserves the exact committed world and clock');
 check(await page.getByRole('button',{name:'推进一轮',exact:true}).isEnabled(),'terminal cancellation restores controls');
 check((await page.locator('body').innerText()).includes('取消'),'cancel outcome remains visible rather than a false success');
 await page.screenshot({path:'.cache/qa/dsh-effects/cancel-complete.png'});
 return {passed:true,checks,operation_id:state.operation_id,runtime:answer.runtime,route_mocks:false};
}
