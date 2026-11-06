async page=>{
 const checks=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
 const check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label);};
 await page.addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:19097'};});
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:19086');
 await page.getByRole('textbox',{name:'搜索战役',exact:true}).fill('万家岭');
 await page.locator('.battle-option').first().click();await page.getByRole('button',{name:/继续配置/}).click();
 await page.locator('#draft-mode').selectOption('analysis');
 const versions=page.getByLabel('回溯史料版本',{exact:true});await versions.locator('option[value="1.1.0"]').waitFor({state:'attached'});
 check(await versions.inputValue()==='1.0.0','Replay default remains 1.0.0');
 await versions.selectOption('1.1.0');await page.locator('#draft-executor').selectOption('afsim');
 const initialized=page.waitForResponse(r=>r.url().endsWith('/init')&&r.request().method()==='POST',{timeout:120000});
 await page.getByRole('button',{name:'进入回溯分析',exact:true}).click();
 const response=await initialized;let snap=await response.json();if(!response.ok())throw Error(JSON.stringify(snap));
 check(snap.war_state.historical_initial.version==='1.1.0','Chosen source version reaches session');
 check(snap.war_state.red_units.length+snap.war_state.blue_units.length===31,'All 31 sourced identities retained as references');
 const sid=snap.session_id,total=snap.war_state.history_replay.total;let linked=0;
 await page.getByTestId('analysis-tab-history').click();
 for(let cursor=1;cursor<total;cursor++){
  const finished=page.waitForResponse(r=>r.url().endsWith('/next')&&r.request().method()==='POST',{timeout:120000});
  await page.getByRole('button',{name:'推进下一史料事件',exact:true}).click();
  const r=await finished;snap=await r.json();if(!r.ok())throw Error(JSON.stringify(snap));
  check(snap.turn_count===cursor,'Source cursor '+cursor+' commits once');
  const world=snap.war_state,record=world.history_replay;
  if(world.red_units.concat(world.blue_units).some(u=>u.lat!==null||u.personnel.current!==null))throw Error('Invented tactical state');
  if(record.source_operation){
   linked++;const card=page.getByTestId('history-operation-binding');await card.waitFor();
   if(!(await card.innerText()).includes(record.source_operation.description))throw Error('Binding not rendered');
   if(record.source_operation.id==='WJL-Oct8-zhanggu'){
    check((await card.innerText()).includes('反攻夺回'),'UI preserves recapture instead of permanent Chinese control');
    await page.screenshot({path:'.cache/qa/wanjialing-sources-2026-10-31/browser/linked-1440.png'});
    await page.setViewportSize({width:900,height:1000});await page.screenshot({path:'.cache/qa/wanjialing-sources-2026-10-31/browser/linked-900.png'});
    await page.setViewportSize({width:1440,height:1000});
   }
  }
 }
 check(linked===7,'Seven event-unit-place bindings rendered');
 check(await page.getByRole('button',{name:'推进下一史料事件',exact:true}).isDisabled(),'Replay ends at last source event');
 await page.reload();await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
 const restored=await page.request.get('http://127.0.0.1:19097/api/sessions/'+sid);const data=await restored.json();
 check(data.turn_count===total-1&&data.war_state.historical_initial.version==='1.1.0','Reload retains source version and cursor');
 check(errors.length===0,'No browser page errors');
 return {passed:true,checks,session_id:sid,frames:total,linked_frames:linked,actual_afsim:true,api_mocks:false};
}
