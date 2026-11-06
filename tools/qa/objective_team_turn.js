async page=>{
 const sid=page.__objectiveSession;
 const initial=await(await page.request.get('http://127.0.0.1:18998/api/sessions/'+sid)).json();
 if(initial.turn_count!==0||initial.war_state.mission.definition.objective_team!=='blue')throw new Error('Cold restart changed the initialized goal');
 await page.getByTestId('top-controls').click();
 await page.locator('#turn-instruction').fill('这是开放推演的明确人为决策，非历史命令重现：先实际调用get_afsim_observation读取当前目标方与双方真实ID，并用retrieve_history核对阶段边界。双方两个单位均明确下达move。红方571团从现有第一线向北后撤约800米，保存兵力并退出目标圈；蓝方3RAR移动至本局已配置的目标中心。双方不开火，不编造伤亡；遵守速度、燃油与30分钟时钟，胜负交由AFSIM的蓝方连续控制规则计算。');
 page.on('response',async r=>{
  if(/\/api\/sessions\/[^/]+\/next$/.test(r.url())&&r.request().method()==='POST')
   page.__objectiveTurnResponse={status:r.status(),body:await r.json()};
 });
 const pending=page.waitForRequest(r=>r.url().endsWith('/next')&&r.method()==='POST');
 await page.getByRole('button',{name:'⏩ 下一轮推演',exact:true}).click();const request=(await pending).postDataJSON();
 await page.screenshot({path:'.cache/qa/objective-team/turn-running.png'});
 return {started:true,session_id:sid,batch_id:request.batch_id,route_mocks:false};
}
