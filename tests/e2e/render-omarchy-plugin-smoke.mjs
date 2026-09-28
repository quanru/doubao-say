import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const assertion = process.env.REVIEW_VISIBLE_ASSERTION;
if (!assertion || assertion.length > 500) {
  throw new Error('REVIEW_VISIBLE_ASSERTION must be 1–500 characters');
}

const casePath = fileURLToPath(new URL('./cases/omarchy-plugin-smoke.yaml', import.meta.url));
const planPath = fileURLToPath(new URL('./review-plan.json', import.meta.url));
const plan = process.env.REVIEW_BASE_REPOSITORY
  ? JSON.parse(readFileSync(planPath, 'utf8')) : { scenarios: [] };
if (!Array.isArray(plan.scenarios)) throw new Error('Review plan has no scenarios array');
const yaml = ['cases:', '  - name: Review the PR on the real Omarchy desktop',
  '    steps:', '      - review.openConfigured: {}', `      - aiAssert: ${JSON.stringify(assertion)}`];
for (const scenario of plan.scenarios) {
  if (scenario.action) yaml.push(`      - aiAct: ${JSON.stringify(scenario.action)}`);
  yaml.push(`      - aiAssert: ${JSON.stringify(scenario.assertion)}`);
}
writeFileSync(casePath, `${yaml.join('\n')}\n`);
