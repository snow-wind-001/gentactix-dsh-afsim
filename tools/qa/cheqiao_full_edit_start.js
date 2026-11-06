async page=>{
 const checks=[];const check=(v,s)=>{if(!v)throw Error(s);checks.push(s)};
 const c=page.getByTestId('historical-setup');
 const actor=c.locator('[data-campaign-actor="ww2.jp.huaian_relief"]');
 await actor.locator('summary').click();
 const times=['1944-03-05T15:15','1944-03-05T16:00','1944-03-05T17:30','1944-03-06T02:30'];
 const notes=['首批约15:15采用所选公开报道钟点，战区入口仍为估计位置。','第二批16:00为本次显式时段离散化假设，不称精确史实命令。','第三批17:30采用所选公开报道钟点，不能把分队标签当成实际时钟。','第四批次日02:30为本次显式时段离散化假设；不混合其他结束日期的统计。'];
 for(let i=0;i<4;i++){
  const part=actor.locator('.part').nth(i);
  await part.getByRole('button',{name:/^为.*单独设置入场$/}).click();
  await part.locator('input[type=datetime-local]').fill(times[i]);
  await part.locator('textarea').fill(notes[i]);
 }
 check(await c.getByTestId('validate-historical-scenario').isEnabled(),'explicit arrival edits invalidate the previous load and allow revalidation');
 const response=page.waitForResponse(r=>r.url().endsWith('/api/historical-scenarios/validate')&&r.request().method()==='POST',{timeout:120000});
 await c.getByTestId('validate-historical-scenario').click();
 const raw=await response,draft=await raw.json();check(raw.ok(),JSON.stringify(draft.detail??'edited draft actually loaded'));
 const arrivals=draft.parameters.campaign.arrivals['ww2.jp.huaian_relief'].parts;
 check(Object.values(arrivals).map(x=>x.not_before).sort().join('|')===times.join('|'),'four explicit times survive API validation and native load');
 check(draft.afsim.returncode===0&&draft.afsim.entity_count===19,'edited nineteen-entity native load succeeds');
 await page.setViewportSize({width:900,height:1000});
 check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'full process editor fits 900px viewport');
 await actor.scrollIntoViewIfNeeded();await page.screenshot({path:'.cache/qa/cheqiao-complete/full/arrivals-edited-900.png'});
 await page.setViewportSize({width:1440,height:1000});
 await page.getByTestId('launch-start').click();
 await page.getByTestId('map-workbench').waitFor({timeout:120000});
 await page.waitForFunction(()=>!document.querySelector('.desktop-root.operation-running'));
 check(await page.locator('.nato-marker').count()===19,'normal launch renders nineteen historical calculation entities');
 const sid=await page.evaluate(()=>localStorage.getItem('gentactix-session'));
 await page.screenshot({path:'.cache/qa/cheqiao-complete/full/initial-map-1440.png'});
 return {passed:true,checks,session_id:sid,draft_id:draft.id,parent_draft_id:draft.parent_id,
  explicit_operator_edits:['four relief arrival times and their assumptions'],route_mocks:false};
}
