#!/usr/bin/env node

import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const values = Object.fromEntries(
  process.argv.slice(2).reduce((pairs, value, index, args) => {
    if (index % 2 === 0) pairs.push([value.replace(/^--/, ''), args[index + 1]]);
    return pairs;
  }, []),
);
for (const key of ['output', 'project', 'test-outcome', 'capture-outcome']) {
  if (!values[key]) throw new Error(`Missing --${key}`);
}

const testOutcome = values['test-outcome'];
const captureOutcome = values['capture-outcome'];
const stage =
  testOutcome === 'failure' || testOutcome === 'cancelled'
    ? 'Midscene test execution'
    : testOutcome === 'skipped'
      ? 'workflow setup before test execution'
      : captureOutcome === 'failure' || captureOutcome === 'cancelled'
        ? 'report evidence capture'
        : 'completed workflow';
const result =
  [testOutcome, captureOutcome].includes('failure')
    ? 'failure'
    : [testOutcome, captureOutcome].includes('cancelled')
      ? 'cancelled'
      : testOutcome === 'success' && captureOutcome === 'success'
        ? 'success'
        : 'skipped';

const output = path.resolve(values.output);
await mkdir(path.dirname(output), { recursive: true });
await writeFile(
  output,
  `${JSON.stringify(
    {
      project: values.project,
      result,
      stage,
      testOutcome,
      captureOutcome,
    },
    null,
    2,
  )}\n`,
);
