async page=>{
 const checks=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
 const check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label);};
 await page.addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:19101'};});
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:19088');
 await page.getByRole('textbox',{name:'搜索战役',exact:true}).fill('万家岭');await page.locator('.battle-option').first().click();
 await page.getByRole('button',{name:/继续配置/}).click();await page.locator('#draft-mode').selectOption('analysis');
 const versions=page.getByLabel('回溯史料版本',{exact:true});await versions.locator('option[value="1.1.0"]').waitFor({state:'attached'});await versions.selectOption('1.1.0');
 await page.locator('#draft-executor').selectOption('narrative');
 const initialized=page.waitForResponse(r=>r.url().endsWith('/init')&&r.request().method()==='POST',{timeout:180000});
 await page.getByRole('button',{name:'进入回溯分析',exact:true}).click();let response=await initialized,snap=await response.json();if(!response.ok())throw Error(JSON.stringify(snap));
 const id=snap.session_id,frames=snap.war_state.history_replay.total;
 const verify=s=>{
  if(s.afsim||s.war_state.afsim)throw Error('DSH-only source step unexpectedly executed AFSIM');
  if(!s.history[0].includes('【DSH节点分析】'))throw Error('Missing actual model commentary');
  if(s.war_state.red_units.concat(s.war_state.blue_units).some(u=>u.lat!==null||u.personnel.current!==null))throw Error('Narration rewrote unknown source state');
 };
 verify(snap);check(snap.war_state.historical_initial.version==='1.1.0','Real DSH narration initializes selected frozen version');
 for(let cursor=1;cursor<frames;cursor++){
  const finished=page.waitForResponse(r=>r.url().endsWith('/next')&&r.request().method()==='POST',{timeout:180000});
  await page.getByRole('button',{name:'推进下一史料事件',exact:true}).click();response=await finished;snap=await response.json();if(!response.ok())throw Error(JSON.stringify(snap));
  verify(snap);check(snap.turn_count===cursor,'Real DSH source commentary '+cursor+' commits once');
 }
 check(await page.getByRole('button',{name:'推进下一史料事件',exact:true}).isDisabled(),'Last source frame stops normally');
 const counts=await page.request.get('http://127.0.0.1:19101/qa/afsim-counters'),value=await counts.json();
 check(Object.values(value).every(n=>n===0),'No AFSIM activation or execution throughout independent narration');
 await page.screenshot({path:'.cache/qa/initial-command-2026-10-31/browser/prose-final-1440.png'});
 check(errors.length===0,'No browser page errors');return {passed:true,checks,session_id:id,frames,afsim_calls:value,actual_dsh:true,api_mocks:false};
}
