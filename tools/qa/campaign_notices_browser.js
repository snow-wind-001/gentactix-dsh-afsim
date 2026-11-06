async page => {
 const snap=page.__campaignSnap;
 if(!snap?.session_id)throw Error('Need the retained actual campaign initialization');
 const fixture=JSON.parse(JSON.stringify(snap));
 fixture.notices.push({level:'warning',message:'QA：重要警告须直接可见'});
 const url='http://127.0.0.1:19129/api/sessions/'+snap.session_id;
 await page.route(url,route=>route.fulfill({json:fixture}));
 try{
  await page.reload();
  await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
  await page.getByTestId('map-workbench').waitFor();
  const cards=page.locator('.workspace-status-message:visible');
  if(await cards.count()>3)throw Error('Accumulated progress notices obscure the map');
  await page.getByText('QA：重要警告须直接可见',{exact:true}).waitFor();
  const details=page.getByTestId('routine-notices');
  if(await details.getAttribute('open')!==null)throw Error('Routine history expanded automatically');
  await details.locator('summary').click();
  const messages=details.locator('.workspace-status-message');
  const expected=fixture.notices.filter(n=>n.level!=='warning'&&n.level!=='error').length;
  if(await messages.count()!==expected)throw Error('Recorded information was lost');
  const bounds=await details.locator('.workspace-notice-log').boundingBox();
  if(!bounds||bounds.height>400)throw Error('Expanded log is not bounded');
  await details.locator('summary').click();
  page.__campaignSnap=snap;
  return {passed:true,scope:'UI replay of actual initialization notices plus one warning; no world changes',recorded:expected,warnings_visible:true,default_collapsed:true,expandable:true};
 }finally{page.__campaignSnap=snap;await page.unroute(url);}
}
