import { readFileSync, appendFileSync } from 'node:fs';

export function resolveReview(manifest, requested = {}) {
  const id = manifest?.id;
  if (!/^[a-z0-9][a-z0-9._-]{2,127}$/.test(id || '')) throw new Error('Invalid manifest plugin ID');
  if (requested.id && requested.id !== 'auto' && requested.id !== id) {
    throw new Error(`Configured plugin ID ${requested.id} does not match manifest ID ${id}`);
  }
  const kinds = manifest.kinds;
  if (!Array.isArray(kinds) || !kinds.every((kind) => typeof kind === 'string')) {
    throw new Error('Manifest kinds are missing');
  }
  let method = requested.method || 'auto';
  if (method === 'auto') {
    if (kinds.some((kind) => ['panel', 'overlay', 'menu'].includes(kind))) method = 'summon';
    else if (kinds.some((kind) => ['bar-widget', 'bar'].includes(kind))) method = 'inspectBar';
    else throw new Error('This plugin has no generic visual entry point; configure an open method');
  }
  if (!/^[A-Za-z][A-Za-z0-9_]*$/.test(method)) throw new Error('Invalid plugin open method');
  const assertion = requested.assertion || (method === 'inspectBar'
    ? 'The Omarchy top bar is visible with the newly enabled plugin widget.'
    : `The ${manifest.name || id} plugin interface is visible on the Omarchy desktop.`);
  if (assertion.length > 500 || /[\r\n]/.test(assertion)) throw new Error('Invalid visible assertion');
  const section = manifest.barWidget?.defaultSection || 'right';
  if (!['left', 'center', 'right'].includes(section)) throw new Error('Invalid bar widget section');
  return { id, method, assertion, section };
}

if (process.argv[1] && import.meta.url === new URL(`file://${process.argv[1]}`).href) {
  const manifest = JSON.parse(readFileSync(process.env.REVIEW_MANIFEST_PATH, 'utf8'));
  const resolved = resolveReview(manifest, {
    id: process.env.REQUESTED_PLUGIN_ID,
    method: process.env.REQUESTED_PLUGIN_OPEN_METHOD,
    assertion: process.env.REQUESTED_VISIBLE_ASSERTION,
  });
  const env = process.env.GITHUB_ENV;
  if (!env) throw new Error('GITHUB_ENV is required');
  appendFileSync(env, Object.entries({
    REVIEW_PLUGIN_ID: resolved.id,
    REVIEW_PLUGIN_OPEN_METHOD: resolved.method,
    REVIEW_VISIBLE_ASSERTION: resolved.assertion,
    REVIEW_PLUGIN_SECTION: resolved.section,
  }).map(([key, value]) => `${key}=${value}\n`).join(''));
  console.log(`Resolved Omarchy plugin ${resolved.id}: ${resolved.method} (${resolved.section})`);
}
