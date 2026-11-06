async page=>{
 const sid='67fcfbc193d8';await page.context().addInitScript(sid=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.setItem('gentactix-session',sid);},sid);
 const checks=[];
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:18981/?qa=positive-delivery');
  await page.getByRole('button',{name:'返回当前战局',exact:true}).click();await page.getByTestId('map-workbench').waitFor();await page.getByTestId('analysis-tab-combined').click();
  const panel=page.getByTestId('combined-arms'),blue=panel.getByTestId('dsh-resource-ledger').nth(1);
  if(!(await blue.innerText()).includes('毛到货 2')||!(await blue.innerText()).includes('粮食消耗 2'))throw new Error('Positive gross receipts do not match the committed sixth turn');
  await blue.scrollIntoViewIfNeeded();await page.waitForFunction(()=>[...document.querySelectorAll('.leaflet-tile-pane img')].every(i=>i.complete),{},{timeout:10000});
  await page.screenshot({path:'.cache/qa/dsh-resources/positive-'+width+'.png'});checks.push(width+' real positive blue delivery visible separately from spending');
 }
 return {passed:true,checks,route_mocks:false};
}
