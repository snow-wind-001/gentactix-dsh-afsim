async page=>{
 const listing=await(await page.request.get('http://127.0.0.1:18998/api/sessions')).json();
 const row=listing.sessions.find(s=>s.scenario==='命令效果控制QA-afsim');if(!row)throw new Error('Owned QA session missing');
 await page.context().addInitScript(sid=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.setItem('gentactix-session',sid);},row.session_id);
 await page.goto('http://127.0.0.1:18981/?qa=effect-busy');
 const resume=page.getByRole('button',{name:'返回当前战局',exact:true});if(await resume.isVisible())await resume.click();
 await page.getByTestId('map-workbench').waitFor();
 const state=await(await page.request.get('http://127.0.0.1:18998/api/sessions/'+row.session_id+'/progress')).json();
 const advance=page.getByRole('button',{name:'推进一轮',exact:true});
 const observed={server_active:state.active,operation_id:state.operation_id,advance_disabled:await advance.isDisabled(),cancel_visible:await page.getByRole('button',{name:'取消',exact:true}).count()>0};
 page.__effectBusyObserved=observed;await page.screenshot({path:'.cache/qa/dsh-effects/active-before.png'});
 if(!state.active)throw new Error('Operation is terminal; no active-state claim is possible');
 if(!observed.advance_disabled||!observed.cancel_visible)throw new Error('Active server operation was not restored: '+JSON.stringify(observed));
 return {passed:true,observed,route_mocks:false};
}
