export const TIME_STEPS = ['5分钟', '15分钟', '30分钟', '1小时', '6小时', '12小时', '1天', '1周', '1个月'];
export function normalizeStep(value: string) { return value.trim().replace(/^(\d+)日$/, '$1天'); }
export function stepOptions(value: string) { const normalized = normalizeStep(value); return TIME_STEPS.includes(normalized) || !normalized ? TIME_STEPS : [...TIME_STEPS, normalized]; }

// Display-side feasibility only. The backend owns the simulation clock.
export function stepDurationSeconds(value: string): number | null {
 const match=value.match(/^\s*(\d+(?:\.\d+)?)\s*(分钟|分|小时|钟头|天|日|星期|周|个月|月)\s*$/);
 if(!match)return null;
 const scales:Record<string,number>={分钟:60,分:60,小时:3600,钟头:3600,天:86400,日:86400,星期:604800,周:604800,个月:2592000,月:2592000};
 const seconds=Number(match[1])*scales[match[2]!]!;
 return Number.isInteger(seconds)&&seconds>0&&seconds<=315360000?seconds:null;
}

// Display rounding only; exact minutes remain in the host world and receipts.
export function formatObservationAge(minutes: unknown): string {
 if(typeof minutes!=='number'||!Number.isFinite(minutes)||minutes<0)return '未知';
 if(minutes>0&&minutes<0.01)return '<0.01分钟';
 const rounded=Number(minutes.toFixed(2));
 return `${rounded===minutes?'':'约'}${rounded}分钟`;
}
