async page=>{
 const API='http://127.0.0.1:19108',checks=[],errors=[];
 const check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label);};
 const get=async path=>{const r=await page.request.get(API+'/api'+path);if(!r.ok())throw Error(await r.text());return r.json();};
 page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19108'});
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:19088');
 const sessions=(await get('/sessions')).sessions;
 const ui=sessions.find(s=>s.scenario==='多方向目标图前端验收（数值QA）');if(!ui)throw Error('UI QA missing');
 const show=async sid=>{await page.evaluate(id=>localStorage.setItem('gentactix-session',id),sid);await page.reload();
  await page.getByRole('button',{name:'返回当前战局',exact:true}).click();if(!await page.getByTestId('campaign-objectives').isVisible())await page.getByRole('button',{name:/目标与运行/}).click();
  await page.getByTestId('campaign-objectives').waitFor({state:'visible'});};
 await show(ui.session_id);
 check((await page.getByTestId('mission-objective-owner').innerText()).includes('双方按各自目标图'),'Header uses bilateral goals rather than fixed red-only condition');
 check((await page.getByTestId('afsim-status').innerText()).includes('会战目标由宿主读取物理结果评分'),'Execution evidence correctly separates AFSIM physics from host scoring');
 await page.locator('[data-goal-id=preserve]').scrollIntoViewIfNeeded();
 const rowBox=await page.locator('[data-goal-id=preserve]').boundingBox(),panelBox=await page.getByTestId('mission-panel').boundingBox();
 check(!!rowBox&&!!panelBox&&rowBox.y>=panelBox.y&&rowBox.y+rowBox.height<=panelBox.y+panelBox.height+1,'Dependent goal can be reached by normal panel scrolling');
 await page.screenshot({path:'.cache/qa/campaign-plan-2026-10-31/browser/reviewed-1440.png'});
 let blue=null;
 for(const s of sessions){if(!s.initialized)continue;const snap=await get('/sessions/'+s.session_id);if(snap.war_state?.mission?.winner==='blue'&&snap.war_state?.campaign_plan){blue=snap;break;}}
 if(!blue)throw Error('Run native blue goal test first');
 const original=JSON.stringify(blue.war_state);await show(blue.session_id);
 const goals=page.getByTestId('campaign-objectives');
 check((await goals.innerText()).includes('蓝方连续达标 1 / 1'),'Blue program win displays its own progress despite legacy red progress zero');
 await goals.getByLabel('目标阵营',{exact:true}).selectOption('blue');
 check((await goals.locator('[data-goal-id=blue_exit]').innerText()).includes('已达成'),'Actual native blue exit displayed as achieved');
 await page.setViewportSize({width:900,height:1000});await goals.locator('[data-goal-id=blue_exit]').scrollIntoViewIfNeeded();
 const box=await page.getByTestId('mission-panel').boundingBox();check(!!box&&box.x>=0&&box.x+box.width<=900,'Goal panel stays inside narrow viewport');
 await page.screenshot({path:'.cache/qa/campaign-plan-2026-10-31/browser/reviewed-blue-900.png'});
 check(JSON.stringify((await get('/sessions/'+blue.session_id)).war_state)===original,'Read-only visual review does not alter settled world');
 check(errors.length===0,'No browser page errors');
 return {passed:true,checks,actual_api:true,actual_afsim_input:true,api_mocks:false,blue_session:blue.session_id};
}
