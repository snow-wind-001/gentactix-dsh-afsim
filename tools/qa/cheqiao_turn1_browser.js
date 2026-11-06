async page => {
  const checks = [];
  const check = (ok, text) => { if (!ok) throw Error(text); checks.push(text); };
  check(await page.locator('.nato-marker').count() === 19, 'nineteen military markers rendered');
  check(await page.locator('.nato-marker.campaign-staging').count() === 5, 'five waiting entities visibly distinguished');
  await page.locator('.nato-marker[title="红方 新四军第1师炮兵大队"]').click();
  const panel = page.getByTestId('command-panel');
  await panel.waitFor({state: 'visible'});
  check(await panel.getByLabel('单位名单（含无坐标单位）').locator('option:checked').innerText() ===
    '红 · 新四军第1师炮兵大队', 'map click selects the correct artillery entity');
  const actions = await panel.getByTestId('unit-action').locator('option').evaluateAll(nodes => nodes.map(n => n.value));
  check(actions.includes('move') && actions.includes('bombard'), 'selected artillery exposes movement and bombardment');
  await panel.getByTestId('unit-action').selectOption('move');
  await panel.getByRole('button', {name: '地图选目的地', exact: true}).click();
  check(await page.getByRole('button', {name: '取消选点 (Esc)', exact: true}).isVisible(), 'map destination picking opens');
  await page.keyboard.press('Escape');
  check(await panel.isVisible(), 'escape returns to unit controls without enqueuing an order');
  await panel.getByRole('button', {name: '本单位决策／执行回执', exact: true}).click();
  await panel.getByRole('region', {name: '单位决策记录'}).waitFor();
  check(await panel.getByRole('region', {name: '单位决策记录'}).getByText('T+1 · 批量模型规划 · 完成', {exact: true}).count() === 1,
    'artillery decision and execution receipt visible');
  const response = page.waitForResponse(r => r.url().endsWith('/commands/compare') && r.request().method() === 'POST', {timeout: 120000});
  await panel.getByRole('button', {name: '只读对照：上轮本单位待命', exact: true}).click();
  const raw = await response, result = await raw.json();
  check(raw.ok(), 'actual native read-only artillery hold comparison succeeds');
  await panel.getByTestId('unit-comparison').waitFor();
  await page.screenshot({path: '.cache/qa/cheqiao-complete/full/turn1-command-comparison.png'});
  await panel.getByRole('button', {name: '收起指挥面板', exact: true}).click();
  return {checks, comparison: {
    mode: result.mode, read_only: result.read_only, metrics: result.metrics,
    artifact_id: result.artifact_id, source_trace_id: result.source_trace_id,
    native: result.alternative?.afsim && {
      status: result.alternative.afsim.status,
      returncode: result.alternative.afsim.returncode,
      entity_count: result.alternative.afsim.entity_count,
      artifact: result.alternative.afsim.artifact,
    },
  }, mocks: false};
}
