import { readFile, readdir } from 'node:fs/promises';
import path from 'node:path';

export const SHELL_CHECKS = [
  {
    key: 'shutdown',
    label: 'Shutdown is readable',
    marker: 'The Omarchy system menu is open',
  },
  {
    key: 'focus',
    label: 'Menu focus highlight is clean',
    marker: 'Exactly one row in the open system menu',
  },
  {
    key: 'bar',
    label: 'Bar is vertical on the left',
    marker: 'The Omarchy bar is visible',
  },
];

export async function findHtmlFiles(directory) {
  const results = [];
  async function visit(current) {
    for (const entry of await readdir(current, { withFileTypes: true })) {
      const item = path.join(current, entry.name);
      if (entry.isDirectory()) await visit(item);
      else if (entry.isFile() && entry.name.endsWith('.html'))
        results.push(item);
    }
  }
  await visit(directory);
  const testRunReports = results.filter((file) =>
    path.basename(file).startsWith('test-run-') ||
    path.basename(path.dirname(file)).startsWith('test-run-'),
  );
  return (testRunReports.length ? testRunReports : results).sort();
}

// Some report versions put raw control characters inside JSON strings.
export function normalizeJsonControlCharacters(source) {
  let normalized = '';
  let insideString = false;
  let escaped = false;
  for (const character of source) {
    if (!insideString) {
      normalized += character;
      if (character === '"') insideString = true;
      continue;
    }
    if (escaped) {
      normalized += character;
      escaped = false;
    } else if (character === '\\') {
      normalized += character;
      escaped = true;
    } else if (character === '"') {
      normalized += character;
      insideString = false;
    } else if (character.charCodeAt(0) <= 0x1f) {
      normalized += `\\u${character.charCodeAt(0).toString(16).padStart(4, '0')}`;
    } else {
      normalized += character;
    }
  }
  return normalized;
}

export function reportDumps(html) {
  return [
    ...html.matchAll(
      /<script\s+type=["']midscene_web_dump["'][^>]*>\s*(\{[\s\S]*?)<\/script>/g,
    ),
  ].map((match) => JSON.parse(normalizeJsonControlCharacters(match[1])));
}

export function testRunDump(html) {
  const match = html.match(
    /<script\s+type=["']midscene_test_run_dump["'][^>]*>\s*(\{[\s\S]*?)<\/script>/,
  );
  return match
    ? JSON.parse(normalizeJsonControlCharacters(match[1]))
    : null;
}

export async function findLatestTestReport(directory) {
  const reports = await Promise.all(
    (await findHtmlFiles(directory)).map(async (file) => {
      const html = await readFile(file, 'utf8');
      const run = testRunDump(html);
      return {
        file,
        html,
        run,
        startedAt: Date.parse(run?.startedAt ?? '') || 0,
      };
    }),
  );
  const latest = reports.sort((left, right) => left.startedAt - right.startedAt).at(-1);
  if (!latest) throw new Error('No Midscene Test HTML report found');
  return latest;
}

export function extractShellEvidence(html, { allowIncomplete = false } = {}) {
  const images = new Map();
  for (const match of html.matchAll(
    /<script\s+type=["']midscene-image["']\s+data-id=["']([^"']+)["'][^>]*>\s*data:image\/(png|jpeg);base64,([A-Za-z0-9+/=]+)\s*<\/script>/g,
  )) {
    images.set(match[1], {
      extension: match[2] === 'jpeg' ? 'jpg' : 'png',
      bytes: Buffer.from(match[3], 'base64'),
    });
  }

  const finished = new Map();
  for (const dump of reportDumps(html)) {
    for (const execution of dump.executions ?? []) {
      for (const task of execution.tasks ?? []) {
        if (task.status !== 'finished' || task.subType !== 'Assert') continue;
        const demand = task.param?.dataDemand;
        if (typeof demand === 'string') finished.set(demand, task);
      }
    }
  }

  return SHELL_CHECKS.map((check) => {
    const entry = [...finished.entries()].find(([demand]) =>
      demand.startsWith(check.marker),
    );
    if (!entry) {
      if (allowIncomplete)
        return { ...check, passed: false, screenshot: null, missing: true };
      throw new Error(`Missing finished Omarchy assertion: ${check.label}`);
    }
    const task = entry[1];
    const screenshot = images.get(task.uiContext?.screenshot?.id);
    if (!screenshot) {
      if (allowIncomplete)
        return { ...check, passed: false, screenshot: null, missing: true };
      throw new Error(`Missing Omarchy screenshot: ${check.label}`);
    }
    return { ...check, passed: task.output === true, screenshot };
  });
}

export async function findShellReport(directory) {
  for (const file of await findHtmlFiles(directory)) {
    const html = await readFile(file, 'utf8');
    if (
      html.includes(SHELL_CHECKS[0].marker) &&
      html.includes(SHELL_CHECKS[2].marker)
    ) {
      return { file, html, checks: extractShellEvidence(html) };
    }
  }
  throw new Error('No Omarchy shell Midscene HTML report found');
}
