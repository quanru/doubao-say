import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { parseReviewIssue } from '../../scripts/parse-omarchy-review-issue.mjs';

const sha = '0b8dfdbdc5dc1deaff178ad727fa22f6e289423a';
const body = `### Plugin repository URL

https://github.com/tathagat11/omarchy-checklist-todo

### Exact commit SHA

${sha}

### Plugin ID

tathagat11.checklist-todo

### Open IPC method

open

### Expected visible result

The Todos popup shows its empty state.`;

test('accepts the GitHub Issue form and extracts a pinned review request', () => {
  assert.deepEqual(parseReviewIssue(body), {
    repository: 'tathagat11/omarchy-checklist-todo',
    sha,
    id: 'tathagat11.checklist-todo',
    openMethod: 'open',
    visibleAssertion: 'The Todos popup shows its empty state.',
  });
});

test('rejects a changed repository host and a command-shaped IPC method', () => {
  assert.throws(() => parseReviewIssue(body.replace('github.com', 'github.com.attacker.test')), /GitHub HTTPS root URL/);
  assert.throws(() => parseReviewIssue(body.replace('### Open IPC method\n\nopen', '### Open IPC method\n\nopen;id')), /Invalid open IPC method/);
});

test('rejects duplicate fields and multiline environment injection', () => {
  assert.throws(() => parseReviewIssue(`${body}\n\n### Plugin ID\n\nother.plugin`), /Duplicate issue field/);
  assert.throws(() => parseReviewIssue(body.replace(sha, `${sha}\nREVIEW_PLUGIN_SHA=bad`)), /40 hex characters/);
});

test('CLI only writes environment for a maintainer-labeled review Issue', () => {
  const dir = mkdtempSync(join(tmpdir(), 'omarchy-review-issue-'));
  try {
    const eventPath = join(dir, 'event.json');
    const envPath = join(dir, 'env');
    const run = (label) => {
      writeFileSync(eventPath, JSON.stringify({
        action: 'labeled', label: { name: label },
        issue: { title: '[Omarchy review] Checklist Todo', body },
      }));
      return spawnSync(process.execPath, ['scripts/parse-omarchy-review-issue.mjs'], {
        env: { ...process.env, GITHUB_EVENT_PATH: eventPath, GITHUB_ENV: envPath },
        encoding: 'utf8',
      });
    };
    assert.notEqual(run('unrelated').status, 0);
    assert.equal(run('midscene-review').status, 0);
    const environment = readFileSync(envPath, 'utf8');
    assert.match(environment, new RegExp(`REVIEW_PLUGIN_SHA=${sha}\\n`));
    assert.match(environment, /REVIEW_VISIBLE_ASSERTION=The Todos popup shows its empty state\.\n/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
