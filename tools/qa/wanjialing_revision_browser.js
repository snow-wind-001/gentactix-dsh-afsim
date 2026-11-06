async page => {
 const API='http://127.0.0.1:19107',checks=[],errors=[];
 const check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label);};
 page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19107'});
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:19088');
 await page.getByRole('textbox',{name:'搜索战役',exact:true}).fill('万家岭');
 await page.locator('.battle-option').first().click();await page.getByRole('button',{name:/继续配置/}).click();
 await page.locator('#draft-mode').selectOption('analysis');
 const versions=page.getByLabel('回溯史料版本',{exact:true});
 await versions.locator('option[value="1.2.0"]').waitFor({state:'attached'});
 check(await versions.inputValue()==='1.0.0','New source does not replace default 1.0.0');
 await versions.selectOption('1.2.0');await page.locator('#draft-executor').selectOption('narrative');
 const wait=path=>page.waitForResponse(r=>r.url().endsWith(path)&&r.request().method()==='POST',{timeout:120000});
 let done=wait('/init');await page.getByRole('button',{name:'进入回溯分析',exact:true}).click();
 let response=await done,snap=await response.json();if(!response.ok())throw Error(JSON.stringify(snap));
 check(snap.war_state.historical_initial.version==='1.2.0','Exact corrected source reaches session');
 const units=snap.war_state.red_units.concat(snap.war_state.blue_units);
 check(units.length===32,'All 32 reference identities remain visible as source identities');
 check(units.some(u=>u.name==='炮兵第1团第6连')&&!units.some(u=>u.name==='炮兵第4团第6连'),'Corrected artillery name replaces mistranscription only in new source');
 const sid=snap.session_id,total=snap.war_state.history_replay.total;
 check(total===19,'Nineteen source frames available');
 await page.getByTestId('analysis-tab-history').click();
 let linked=0;const seen=[];
 for(let cursor=1;cursor<total;cursor++){
  done=wait('/next');await page.getByRole('button',{name:'推进下一史料事件',exact:true}).click();
  response=await done;snap=await response.json();if(!response.ok())throw Error(JSON.stringify(snap));
  check(snap.turn_count===cursor,'Source cursor '+cursor+' commits once');
  const world=snap.war_state,record=world.history_replay,op=record.source_operation;
  check(world.red_units.concat(world.blue_units).every(u=>u.lat===null&&u.personnel.current===null),'Frame '+cursor+' preserves unknown deployment and strength');
  if(op){
   linked++;seen.push(op.id);const card=page.getByTestId('history-operation-binding');await card.waitFor();
   check((await card.innerText()).includes(op.description),'Current source binding displayed '+op.id);
   if(op.id==='WJL-Oct8-142-departure'){
    check((await card.innerText()).includes('首次接敌'),'Departure does not claim known contact time');
    await page.screenshot({path:'.cache/qa/wanjialing-continuous-2026-10-31/browser/departure-1440.png'});
   }
   if(op.id==='WJL-Oct10-residual'){
    check((await card.innerText()).includes('不等于全役结束'),'Last source frame does not claim historical campaign finished');
    await page.screenshot({path:'.cache/qa/wanjialing-continuous-2026-10-31/browser/residual-1440.png'});
    await page.setViewportSize({width:900,height:1000});await page.screenshot({path:'.cache/qa/wanjialing-continuous-2026-10-31/browser/residual-900.png'});
   }
  }
 }
 check(linked===17&&new Set(seen).size===17,'All seventeen source-unit-place bindings visited without duplication');
 check(await page.getByRole('button',{name:'推进下一史料事件',exact:true}).isDisabled(),'Stops at end of prepared evidence');
 await page.reload();await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
 const restored=await page.request.get(API+'/api/sessions/'+sid),data=await restored.json();
 check(data.turn_count===18&&data.war_state.historical_initial.version==='1.2.0','Reload retains exact source and final cursor');
 check(errors.length===0,'No browser page errors');
 return {passed:true,checks,session_id:sid,frames:total,linked_frames:linked,actual_dsh:true,api_mocks:false,
  scope:'Sourced replay with model commentary; no physical multi-day battle or historical casualty calibration claim'};
}
