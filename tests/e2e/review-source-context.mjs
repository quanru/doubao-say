import { lstatSync, readFileSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';

const skippedDirectories = new Set(['.git', '.venv', 'node_modules', 'dist', 'build', 'artifacts', '__pycache__']);
const sourceFile = (name) => /\.(?:py|js|mjs|cjs|ts|tsx|jsx|qml|sh|json|toml|yaml|yml|html|css)$/i.test(name)
  || /^(?:manifest\.json|install\.sh|start\.sh|setup-omarchy\.sh)$/i.test(name);
const safePath = (name) => /^[A-Za-z0-9._/-]{1,240}$/.test(name || '')
  && !name.startsWith('/') && !name.split('/').includes('..');

function readSource(root, name) {
  if (!safePath(name)) return null;
  const path = resolve(root, name);
  if (!path.startsWith(`${resolve(root)}/`)) return null;
  let stat;
  try { stat = lstatSync(path); } catch { return null; }
  if (!stat.isFile() || stat.size > 128_000) return null;
  const content = readFileSync(path, 'utf8');
  return content.includes('\0') ? null : content;
}

function repositoryFiles(root) {
  const found = [];
  const walk = (directory, prefix = '') => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      if (found.length >= 2_000) return;
      const relative = prefix ? `${prefix}/${entry.name}` : entry.name;
      if (entry.isDirectory()) {
        if (!skippedDirectories.has(entry.name) && !entry.name.startsWith('.')) walk(join(directory, entry.name), relative);
      } else if (entry.isFile() && sourceFile(relative)) found.push(relative);
    }
  };
  walk(root);
  return found;
}

function changedExcerpt(content, file) {
  const lines = content.split('\n');
  const indices = new Set(lines.slice(0, 35).map((_, index) => index));
  for (const match of String(file.patch || '').matchAll(/^@@[^\n]*\+(\d+)(?:,(\d+))?[^\n]*@@/gm)) {
    const start = Number(match[1]) - 1;
    const count = Number(match[2] || 1);
    for (let index = Math.max(0, start - 25); index < Math.min(lines.length, start + count + 25); index++) {
      indices.add(index);
    }
  }
  return [...indices].sort((a, b) => a - b).map((index) => `${index + 1}: ${lines[index]}`).join('\n');
}

function relatedExcerpt(content, changedFiles) {
  const lines = content.split('\n');
  const indices = new Set(lines.slice(0, 30).map((_, index) => index));
  const literals = changedFiles.flatMap((file) => [...String(file.patch || '').matchAll(/["']([^"'\n]{8,100})["']/g)]
    .map((match) => match[1]));
  for (let index = 0; index < lines.length; index++) {
    if (!literals.some((literal) => lines[index].includes(literal))) continue;
    for (let nearby = Math.max(0, index - 8); nearby < Math.min(lines.length, index + 9); nearby++) {
      indices.add(nearby);
    }
  }
  return [...indices].sort((a, b) => a - b).map((index) => `${index + 1}: ${lines[index]}`).join('\n');
}

export function buildSourceContext(root, changedFiles, redact) {
  if (!root) throw new Error('Review source checkout is required');
  const files = repositoryFiles(root);
  const available = new Set(files);
  const changed = changedFiles.filter((file) => readSource(root, file.filename) !== null);

  const related = new Set(['manifest.json', 'install.sh', 'start.sh', 'setup-omarchy.sh']
    .filter((name) => available.has(name) && !changed.some((file) => file.filename === name)));
  const changedStems = changed.map((file) => file.filename.split('/').at(-1).replace(/\.[^.]+$/, ''));
  const changedSource = changed.map((file) => readSource(root, file.filename) || '');
  const candidates = [];
  for (const name of files) {
    if (changed.some((file) => file.filename === name) || related.has(name)) continue;
    const content = readSource(root, name);
    if (!content) continue;
    const stem = name.split('/').at(-1).replace(/\.[^.]+$/, '');
    const imported = stem.length >= 5 && changedSource.some((source) =>
      source.split('\n').some((line) => /^\s*(?:from|import)\s/.test(line) && line.includes(stem)));
    const mentioned = stem.length >= 5 && changedSource.some((source) => source.includes(stem));
    const reverseReference = changedStems.some((changedStem) => changedStem.length >= 5 && content.includes(changedStem));
    const score = (imported ? 10 : 0) + (mentioned ? 4 : 0) + (reverseReference ? 2 : 0);
    if (score) candidates.push({ name, score });
  }
  candidates.sort((a, b) => b.score - a.score || a.name.localeCompare(b.name));
  for (const candidate of candidates) {
    if (related.size >= 10) break;
    related.add(candidate.name);
  }

  const selected = [...changed.map((file) => file.filename), ...related];
  const context = [];
  let remaining = 48_000;
  for (const name of selected) {
    const content = readSource(root, name);
    if (content === null) continue;
    const changedFile = changed.find((file) => file.filename === name);
    const body = changedFile ? changedExcerpt(content, changedFile) :
      relatedExcerpt(content, changed);
    const limit = changedFile ? 12_000 : 3_000;
    const excerpt = redact(body.slice(0, Math.min(limit, remaining)));
    context.push({ file: name, kind: changedFile ? 'changed source' : 'related source',
      content: excerpt, truncated: body.length > limit || body.length > remaining });
    remaining -= excerpt.length;
    if (remaining <= 0) break;
  }
  return { context, readChanged: (name) => readSource(root, name) };
}

export function changedHunks(file) {
  const patch = file.patch;
  if (typeof patch !== 'string' || !patch.includes('@@')) return null;
  return patch.split(/(?=^@@[^\n]*@@)/m).filter((part) => part.startsWith('@@'));
}
