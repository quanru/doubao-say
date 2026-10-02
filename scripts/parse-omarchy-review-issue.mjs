import { appendFileSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const labels = [
  'Plugin repository URL',
  'Exact commit SHA',
  'Plugin ID',
  'Open IPC method',
  'Expected visible result',
];

export function parseReviewIssue(body) {
  const fields = new Map();
  let heading;
  for (const line of body.split(/\r?\n/)) {
    const nextHeading = /^### (.+)$/.exec(line);
    if (nextHeading) {
      heading = nextHeading[1];
      if (fields.has(heading)) throw new Error(`Duplicate issue field: ${heading}`);
      fields.set(heading, []);
    } else if (heading) {
      fields.get(heading).push(line);
    }
  }
  const value = (label) => {
    if (!fields.has(label)) throw new Error(`Missing issue field: ${label}`);
    const result = fields.get(label).join(' ').replace(/\s+/g, ' ').trim();
    if (!result || result === '_No response_') throw new Error(`Empty issue field: ${label}`);
    return result;
  };
  const url = new URL(value(labels[0]));
  if (url.protocol !== 'https:' || url.hostname !== 'github.com' || url.username || url.password || url.search || url.hash) {
    throw new Error('Plugin repository must be a public GitHub HTTPS root URL');
  }
  const path = url.pathname.replace(/\/$/, '').replace(/\.git$/, '').replace(/^\//, '');
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(path)) {
    throw new Error('Plugin repository URL must identify one owner/repository');
  }
  const sha = value(labels[1]);
  const id = value(labels[2]);
  const openMethod = value(labels[3]);
  const visibleAssertion = value(labels[4]);
  if (!/^[a-fA-F0-9]{40}$/.test(sha)) throw new Error('Exact commit SHA must contain 40 hex characters');
  if (!/^[a-z0-9][a-z0-9._-]{2,127}$/.test(id)) throw new Error('Invalid plugin ID');
  if (!/^[A-Za-z][A-Za-z0-9_]*$/.test(openMethod)) throw new Error('Invalid open IPC method');
  if (visibleAssertion.length > 500) throw new Error('Visible assertion exceeds 500 characters');
  return { repository: path, sha, id, openMethod, visibleAssertion };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const event = JSON.parse(readFileSync(process.env.GITHUB_EVENT_PATH, 'utf8'));
  if (event.action !== 'labeled' || event.label?.name !== 'midscene-review' ||
      !event.issue?.title?.startsWith('[Omarchy review] ')) {
    throw new Error('Expected a labeled Omarchy review Issue');
  }
  const request = parseReviewIssue(event.issue.body || '');
  const environment = {
    REVIEW_PLUGIN_REPOSITORY: request.repository,
    REVIEW_PLUGIN_SHA: request.sha,
    REVIEW_PLUGIN_ID: request.id,
    REVIEW_PLUGIN_OPEN_METHOD: request.openMethod,
    REVIEW_VISIBLE_ASSERTION: request.visibleAssertion,
  };
  appendFileSync(process.env.GITHUB_ENV, Object.entries(environment).map(([key, value]) => `${key}=${value}\n`).join(''));
  console.log(`Validated Omarchy plugin review: ${request.repository}@${request.sha}`);
}
