/** The same domain shape is read by the host; runtime owns request assembly. */
import { readFileSync } from 'node:fs';
export const effectSchema = JSON.parse(readFileSync(new URL('./effect-schema.json', import.meta.url), 'utf8'));
