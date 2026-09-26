import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const assertion = process.env.REVIEW_VISIBLE_ASSERTION;
if (!assertion || assertion.length > 500) {
  throw new Error('REVIEW_VISIBLE_ASSERTION must be 1–500 characters');
}

const casePath = fileURLToPath(new URL('./cases/omarchy-plugin-smoke.yaml', import.meta.url));
const source = readFileSync(casePath, 'utf8');
const placeholder = '__REVIEW_VISIBLE_ASSERTION__';
if (source.split(placeholder).length !== 2) {
  throw new Error('Plugin smoke case must contain one assertion placeholder');
}
writeFileSync(casePath, source.replace(placeholder, JSON.stringify(assertion)));
