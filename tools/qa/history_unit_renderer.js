async page => {
  // Response-only fixtures against copies; no API write or historical assertion.
  const api='http://127.0.0.1:18988', ui='http://127.0.0.1:18981/';
  const id='ab37bbbcf93c', result=[];
  await page.context().addInitScript(() => {
    window.gentactix={backendUrl:'http://127.0.0.1:18988'};
  });
  const response=await page.request.get(`${api}/api/sessions/${id}`);
  if(!response.ok())throw new Error(await response.text());
  const original=await response.json(), fixture=JSON.parse(JSON.stringify(original));
  fixture.war_state.red_units=[
    {name:'QA红方坐标探针（非历史部署）',type:'步兵',lat:34.20442,lng:117.28386},
    {name:'QA待定位单位（非历史编制）',type:'步兵',lat:null,lng:null},
  ];
  fixture.war_state.blue_units=[
    {name:'QA蓝方坐标探针（非历史部署）',type:'步兵',lat:34.55,lng:117.73},
  ];
  let useFixture=false;
  const path=`${api}/api/sessions/${id}`;
  await page.route(path, route=>route.fulfill({json:useFixture?fixture:original}));
  try {
    await page.goto(ui);
    await page.evaluate(id=>localStorage.setItem('gentactix-session',id),id);
    for(const width of [1440,900]){
      await page.setViewportSize({width,height:1000});
      for(const mode of ['empty','fixture']){
        useFixture=mode==='fixture';
        await page.reload();
        await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
        await page.getByTestId('map-workbench').waitFor();
        await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
        const drawn=await page.locator('.nato-marker').count(), expected=useFixture?2:0;
        const misplacedUnknown=await page.locator('.nato-marker[title*="待定位"]').count();
        result.push({width,mode,input_units:useFixture?3:0,drawn,expected,misplacedUnknown,
          passed:drawn===expected&&misplacedUnknown===0});
      }
    }
    await page.screenshot({path:'.cache/qa/historical-baseline/renderer.png'});
  } finally {
    await page.unroute(path);
  }
  return {fixture_only:true,user_files_modified:false,passed:result.every(r=>r.passed),results:result};
}
