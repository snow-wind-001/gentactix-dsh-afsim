/** Select linked public Native tool evidence, excluding chat and reasoning. */
const tools = new Set(['preview_turn_effects', 'amend_turn_effects']);
function records(events) {
  const calls = new Map();
  const values = [];
  for (let index = 0; index < events.length; index++) {
    const event = events[index];
    if (event.type === 'tool/call' && tools.has(event.data?.name))
      calls.set(event.data.callId, { call: event, callIndex: index });
    if (event.type !== 'tool/result') continue;
    const message = event.data?.message;
    const source = calls.get(message?.toolCallId);
    if (!source || event.data?.isError || message?.isError) continue;
    const text = (message?.content ?? []).filter(b => b.type === 'text').map(b => b.text ?? '').join('\n');
    let reply, args;
    try {
      reply = JSON.parse(text);
      args = source.call.data.arguments;
      if (typeof args === 'string') args = JSON.parse(args);
    } catch { continue; }
    if (reply?.readonly !== true || reply.version !== 'turn-effects-preview-1') continue;
    values.push({ ...source, result: event, resultIndex: index, reply, args });
  }
  return values;
}

function chain(values, record) {
  const selected = [], seen = new Set();
  while (record) {
    const ref = record.reply.candidate_ref;
    if (seen.has(ref)) return [];
    seen.add(ref); selected.unshift(record);
    if (record.call.data.name === 'preview_turn_effects')
      return structuredClone(selected.flatMap(r => [r.call, r.result]));
    const base = record.args?.base_ref;
    record = values.findLast(r => r.resultIndex < record.callIndex && r.reply.candidate_ref === base);
  }
  return [];
}

export function candidateEvidence(events, ref) {
  if (typeof ref !== 'string' || !/^[a-f0-9]{64}$/.test(ref)) return [];
  const values = records(events);
  const record = values.findLast(r => r.reply.candidate_ref === ref);
  return record ? chain(values, record) : [];
}

export function previewEvidence(events, digest) {
  const values = records(events);
  const record = values.findLast(r => r.reply.ok === true && r.reply.digest === digest);
  return record ? chain(values, record) : [];
}
