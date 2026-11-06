async page => {
 const API='http://127.0.0.1:19119',checks=[],errors=[],samples=[];
 const check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label);};
 page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19119'});
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:19088');
 await page.getByRole('textbox',{name:'搜索战役',exact:true}).fill('万家岭');
 await page.locator('.battle-option').first().click();await page.getByRole('button',{name:/继续配置/}).click();
 await page.locator('#draft-mode').selectOption('analysis');
 const versions=page.getByLabel('回溯史料版本',{exact:true});
 await versions.locator('option[value="1.3.0"]').waitFor({state:'attached'});
 check(await versions.inputValue()==='1.0.0','The new source version does not replace the default');
 await versions.selectOption('1.3.0');await page.locator('#draft-executor').selectOption('afsim');
 const wait=path=>page.waitForResponse(r=>r.url().endsWith(path)&&r.request().method()==='POST',{timeout:180000});
 let done=wait('/init');await page.getByRole('button',{name:'进入回溯分析',exact:true}).click();
 let response=await done,snap=await response.json();if(!response.ok())throw Error(JSON.stringify(snap));
 check(snap.war_state.historical_initial.version==='1.3.0','Normal launch freezes the selected 1.3.0 source');
 check(snap.war_state.red_units.length+snap.war_state.blue_units.length===39,'All 39 references are retained without becoming deployed combat units');
 const sid=snap.session_id,total=snap.war_state.history_replay.total,seen=[];
 check(total===27,'The extended frozen replay includes all 27 context and source frames');
 await page.getByTestId('analysis-tab-history').click();
 for(let cursor=1;cursor<total;cursor++){
  done=wait('/next');await page.getByRole('button',{name:'推进下一史料事件',exact:true}).click();
  response=await done;snap=await response.json();if(!response.ok())throw Error(JSON.stringify(snap));
  const w=snap.war_state,record=w.history_replay,op=record.source_operation;
  check(snap.turn_count===cursor,'Source frame '+cursor+' commits exactly once');
  check(w.red_units.concat(w.blue_units).every(u=>u.lat===null&&u.personnel.current===null),'Frame '+cursor+' preserves unknown deployments and strengths');
  check(!!w.afsim,'Frame '+cursor+' retains external execution evidence');
  if(op){
   seen.push(op.id);const card=page.getByTestId('history-operation-binding');await card.waitFor();
   check((await card.innerText()).includes(op.description),'Current source operation is visible '+op.id);
   if(op.id==='WJL-Sep28-149-attachment'){
    check((await card.innerText()).includes('101师团'),'149 administrative parent remains distinct from temporary command');
    await page.screenshot({path:'.cache/qa/campaign-continuity-2026-11-01/attachment-1440.png'});
   }
   if(op.id==='WJL-Oct2-east-order')check((await card.innerText()).includes('到场'),'Orders do not imply all formations have arrived');
   if(op.id==='WJL-Oct16-retrograde')check((await card.innerText()).includes('61师'),'The recorded division61 is not silently merged with division60');
   if(op.id==='WJL-Oct17-withdrawal'){
    check((await card.innerText()).includes('不强制'),'Historical withdrawal is not an automatic open-mode ending');
    await page.screenshot({path:'.cache/qa/campaign-continuity-2026-11-01/withdrawal-1440.png'});
    await page.setViewportSize({width:900,height:1000});
    check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'The source panel fits a narrow viewport');
    await page.screenshot({path:'.cache/qa/campaign-continuity-2026-11-01/withdrawal-900.png'});
   }
  }
  samples.push({cursor,operation:op?.id||null,afsim:w.afsim});
 }
 check(seen.length===25&&new Set(seen).size===25,'All 25 operation links are accessible exactly once');
 check(await page.getByRole('button',{name:'推进下一史料事件',exact:true}).isDisabled(),'The prepared evidence ends without fabricating another event');
 const frozen=JSON.stringify(snap.war_state);
 await page.reload();await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
 const restored=await page.request.get(API+'/api/sessions/'+sid),data=await restored.json();
 check(data.turn_count===26&&JSON.stringify(data.war_state)===frozen,'Reload preserves the final frozen source frame');
 check(errors.length===0,'No page errors');
 return {passed:true,checks,samples,session_id:sid,frames:total,linked_frames:seen.length,
  actual_afsim:true,actual_model:false,api_mocks:false,
  scope:'Source replay, Native external receipts and source UI; not a physical campaign or historical efficacy test'};
}
