#!/usr/bin/env node

import {
  copyFile,
  mkdir,
  readFile,
  readdir,
  writeFile,
} from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import {
  extractShellEvidence,
  findHtmlFiles,
  reportDumps,
} from './omarchy-shell-evidence.mjs';

const MANIFEST_VERSION = 1;

function parseArguments(argv) {
  const options = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith('--') || value === undefined) {
      throw new Error(`Invalid argument near ${key ?? '<end>'}`);
    }
    options[key.slice(2)] = value;
  }
  return options;
}

function required(options, name) {
  const value = options[name];
  if (!value) {
    throw new Error(`Missing --${name}`);
  }
  return value;
}

function validateRunId(value) {
  if (!/^\d+$/.test(value)) {
    throw new Error('Run ID must contain digits only');
  }
  return value;
}

function validateRetention(value) {
  const retention = Number(value);
  if (!Number.isInteger(retention) || retention < 1 || retention > 50) {
    throw new Error('Report retention must be an integer from 1 to 50');
  }
  return retention;
}

function normalizeBaseUrl(value) {
  const url = new URL(value);
  if (url.protocol !== 'https:' && url.protocol !== 'http:') {
    throw new Error('Pages URL must use HTTP or HTTPS');
  }
  if (!url.pathname.endsWith('/')) {
    url.pathname += '/';
  }
  return url;
}

function collectModelUsage(reportHtml) {
  const calls = new Map();

  function visit(value) {
    if (Array.isArray(value)) {
      value.forEach(visit);
      return;
    }
    if (!value || typeof value !== 'object') {
      return;
    }
    const usage = value.usage;
    if (usage && typeof usage === 'object') {
      const callId = usage._midscene_call_id;
      if (typeof callId === 'string' && !calls.has(callId)) {
        calls.set(callId, {
          durationMs: Number.isFinite(usage.time_cost) ? usage.time_cost : null,
          tokens: Number.isFinite(usage.total_tokens)
            ? usage.total_tokens
            : null,
        });
      }
    }
    Object.values(value).forEach(visit);
  }

  for (const dump of reportDumps(reportHtml)) visit(dump);

  const durations = [...calls.values()]
    .map((call) => call.durationMs)
    .filter((duration) => duration !== null);
  const tokens = [...calls.values()]
    .map((call) => call.tokens)
    .filter((tokenCount) => tokenCount !== null);
  return {
    modelCallCount: calls.size,
    averageDurationMs: durations.length
      ? Math.round(
          durations.reduce((sum, duration) => sum + duration, 0) /
            durations.length,
        )
      : null,
    tokenUsage: tokens.length
      ? tokens.reduce((sum, tokenCount) => sum + tokenCount, 0)
      : null,
  };
}

function validateHistoryManifest(manifest) {
  if (
    !manifest ||
    manifest.version !== MANIFEST_VERSION ||
    !Array.isArray(manifest.reports)
  ) {
    throw new Error('Existing Pages manifest has an unsupported shape');
  }
  for (const report of manifest.reports) {
    if (
      typeof report.runId !== 'string' ||
      !/^\d+$/.test(report.runId) ||
      report.reportPath !== `reports/${report.runId}/index.html` ||
      typeof report.workflowUrl !== 'string' ||
      (report.files !== undefined &&
        (!Array.isArray(report.files) ||
          report.files.some(
            (file) =>
              typeof file !== 'string' ||
              !/^reports\/\d+\/[a-z0-9.-]+$/.test(file) ||
              !file.startsWith(`reports/${report.runId}/`),
          )))
    ) {
      throw new Error(
        'Existing Pages manifest contains an invalid report entry',
      );
    }
  }
  return manifest;
}

async function fetchHistory(baseUrl) {
  const manifestUrl = new URL('reports/manifest.json', baseUrl);
  const response = await fetch(manifestUrl, { redirect: 'follow' });
  if (response.status === 404) {
    return [];
  }
  if (!response.ok) {
    throw new Error(
      `Cannot download existing manifest: HTTP ${response.status}`,
    );
  }
  let manifest;
  try {
    manifest = await response.json();
  } catch (error) {
    throw new Error(`Cannot parse existing manifest: ${error.message}`);
  }
  return validateHistoryManifest(manifest).reports;
}

async function restoreReport(baseUrl, siteDirectory, report) {
  for (const file of report.files ?? [report.reportPath]) {
    const response = await fetch(new URL(file, baseUrl), {
      redirect: 'follow',
    });
    if (!response.ok) {
      throw new Error(
        `Cannot restore report for run ${report.runId}: HTTP ${response.status}`,
      );
    }
    const contentType = response.headers.get('content-type') ?? '';
    if (
      file.endsWith('.html') &&
      !contentType.toLowerCase().includes('text/html')
    ) {
      throw new Error(
        `Cannot restore report for run ${report.runId}: expected text/html, got ${contentType || 'no Content-Type'}`,
      );
    }
    const destination = path.join(siteDirectory, file);
    await mkdir(path.dirname(destination), { recursive: true });
    await writeFile(destination, Buffer.from(await response.arrayBuffer()));
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function formatDuration(durationMs) {
  if (durationMs === null) return 'Unavailable';
  return `${(durationMs / 1000).toFixed(2)} s`;
}

function buildOmarchyShowcase(checks, workflowUrl) {
  const rows = checks
    .map(
      (check) => `
    <div class="check"><span class="check-mark">✓</span><span>${escapeHtml(check.label)}</span><strong>PASS</strong></div>`,
    )
    .join('');
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Omarchy × Midscene — Visual acceptance</title>
  <style>
    :root { font-family: Inter, ui-sans-serif, system-ui, sans-serif; color: #eef2ff; background: #080b16; }
    * { box-sizing: border-box; } body { margin: 0; } a { color: inherit; }
    main { max-width: 1360px; padding: 44px 28px 100px; margin: auto; }
    .eyebrow { color: #a6a9ff; letter-spacing: .18em; font-size: 12px; font-weight: 800; text-transform: uppercase; }
    h1 { font-size: clamp(42px, 6vw, 84px); letter-spacing: -.065em; line-height: 1.02; margin: 18px 0; }
    h1 em { color: #a7f3d0; font-style: normal; } .lead { color: #a9b3c9; font-size: 20px; max-width: 760px; line-height: 1.6; }
    .hero { display: grid; grid-template-columns: 1fr auto; align-items: end; gap: 40px; margin-bottom: 34px; }
    .score { padding: 24px 32px; background: #152b29; border: 1px solid #3b8a72; border-radius: 20px; min-width: 210px; }
    .score b { display: block; font-size: 58px; letter-spacing: -.06em; color: #a7f3d0; line-height: 1; }
    .score span { color: #c5ded3; font-size: 13px; text-transform: uppercase; letter-spacing: .08em; }
    .pipeline { display: flex; flex-wrap: wrap; gap: 8px; margin: 34px 0; }
    .pipeline span { padding: 10px 14px; border-radius: 999px; background: #151b2c; border: 1px solid #343c54; color: #c8d0e2; font-size: 13px; }
    .grid { display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(290px, 1fr); gap: 18px; }
    .panel { overflow: hidden; border: 1px solid #303953; background: #111727; border-radius: 20px; }
    .panel img { width: 100%; display: block; object-fit: contain; background: #080b16; }
    .panel .caption { padding: 18px 20px; color: #b8c4d9; } .caption b { color: white; display: block; margin-bottom: 4px; }
    .checks { margin-top: 18px; padding: 20px 24px; } .check { display: flex; gap: 14px; align-items: center; padding: 14px 0; border-bottom: 1px solid #293248; }
    .check:last-child { border: 0; }.check-mark { color: #a7f3d0; font-size: 22px; }.check strong { margin-left: auto; color: #a7f3d0; font-size: 12px; letter-spacing: .12em; }
    h2 { margin: 70px 0 16px; font-size: 30px; letter-spacing: -.035em; } .muted { color: #a9b3c9; line-height: 1.6; }
    .button { display: inline-block; text-decoration: none; background: #b4a7ff; color: #0b0c18; border-radius: 10px; padding: 12px 18px; font-weight: 800; margin: 12px 12px 16px 0; }
    .button.secondary { background: #25304a; color: #e5e9ff; }
    iframe { width: 100%; height: 820px; border: 1px solid #3f4960; border-radius: 16px; background: white; }
    @media (max-width: 800px) { .hero, .grid { grid-template-columns: 1fr; } main { padding: 26px 16px 70px; } }
  </style>
</head>
<body><main>
  <div class="eyebrow">Real desktop · Visual acceptance · Omarchy 4.0.3</div>
  <div class="hero"><div><h1>Omarchy <em>×</em> Midscene</h1>
    <p class="lead">Midscene judged the pixels of a real Hyprland desktop: readable menu text, clean focus styling, and a correctly placed vertical bar.</p></div>
    <div class="score"><b>3 / 3</b><span>visual assertions passed</span></div></div>
  <div class="pipeline"><span>Official Omarchy ISO</span><span>→ KVM guest</span><span>→ Hyprland / Wayland</span><span>→ VNC bridge</span><span>→ Midscene VLM</span><span>→ HTML replay</span></div>
  <div class="grid">
    <div class="panel"><img src="menu.jpg" alt="Real Omarchy system menu with Shutdown visible and one focused row"><div class="caption"><b>System menu · real VM screenshot</b>Shutdown is legible; one menu row has a visible focus highlight.</div></div>
    <div><div class="panel"><img src="bar.jpg" alt="Omarchy bar docked vertically on the left edge"><div class="caption"><b>Bar position · real VM screenshot</b>The bar is vertical and docked to the left edge.</div></div>
      <div class="panel checks">${rows}</div></div>
  </div>
  <h2>Watch the actual Midscene replay</h2>
  <p class="muted">The embedded report below includes each screenshot, the assertion prompt, the model result, and the execution timeline. The onboarding run is available separately.</p>
  <a class="button" href="shell-report.html" target="_blank" rel="noopener">Open full shell report ↗</a>
  <a class="button secondary" href="onboarding-report.html" target="_blank" rel="noopener">Open onboarding report ↗</a>
  <a class="button secondary" href="${escapeHtml(workflowUrl)}">View CI run ↗</a>
  <iframe src="shell-report.html" title="Interactive Midscene shell report" loading="lazy"></iframe>
</main></body></html>`;
}

function buildIndex(reports) {
  const rows = reports
    .map(
      (report) => `
          <tr>
            <td><a href="${escapeHtml(report.workflowUrl)}">${escapeHtml(report.runId)}</a></td>
            <td>${escapeHtml(report.label ?? 'Midscene E2E')}</td>
            <td>${escapeHtml(report.generatedAt)}</td>
            <td>${escapeHtml(report.successRate.toFixed(1))}%</td>
            <td>${escapeHtml(formatDuration(report.averageDurationMs))}</td>
            <td>${escapeHtml(report.modelCallCount)}</td>
            <td>${report.tokenUsage === null ? 'Unavailable' : escapeHtml(report.tokenUsage.toLocaleString('en-US'))}</td>
            <td><a href="${escapeHtml(report.workflowUrl)}">Actions run</a></td>
            <td><a href="${escapeHtml(report.reportPath)}">HTML report</a></td>
          </tr>`,
    )
    .join('');

  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Doubao Say test report history</title>
    <style>
      :root { color-scheme: light dark; font-family: ui-sans-serif, system-ui, sans-serif; }
      body { margin: 0 auto; max-width: 1180px; padding: 2rem 1rem; }
      h1 { margin-bottom: .4rem; }
      p { color: #777; margin-top: 0; }
      .table-wrap { overflow-x: auto; }
      table { border-collapse: collapse; width: 100%; }
      th, td { border-bottom: 1px solid #8885; padding: .75rem; text-align: left; white-space: nowrap; }
      th { font-size: .82rem; text-transform: uppercase; }
      a { color: #2878d0; }
    </style>
  </head>
  <body>
    <main>
      <h1>Doubao Say test report history</h1>
      <p>Successful Midscene CI reports, newest first.</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Run ID</th><th>Distribution</th><th>Generated (UTC)</th><th>Success rate</th><th>Avg. model call</th><th>Model calls</th><th>Tokens</th><th>Workflow</th><th>Report</th></tr></thead>
          <tbody>${rows}
          </tbody>
        </table>
      </div>
    </main>
  </body>
</html>
`;
}

export async function buildPagesReport(options) {
  const reportDirectory = path.resolve(required(options, 'report-dir'));
  const siteDirectory = path.resolve(required(options, 'site-dir'));
  const runId = validateRunId(required(options, 'run-id'));
  const workflowUrl = required(options, 'workflow-url');
  const generatedAt = new Date(required(options, 'generated-at')).toISOString();
  const retention = validateRetention(required(options, 'retention'));
  const baseUrl = normalizeBaseUrl(required(options, 'pages-url'));
  const label = options.label || 'Midscene E2E';

  const existingItems = await readdir(siteDirectory).catch((error) => {
    if (error.code === 'ENOENT') return null;
    throw error;
  });
  if (existingItems?.length) {
    throw new Error('Site output directory must be empty');
  }

  const htmlFiles = await findHtmlFiles(reportDirectory);
  if (htmlFiles.length < 1 || htmlFiles.length > 2) {
    throw new Error(
      `Expected one or two report HTML files, found ${htmlFiles.length}`,
    );
  }
  const htmlReports = await Promise.all(
    htmlFiles.map(async (file) => ({
      file,
      html: await readFile(file, 'utf8'),
    })),
  );
  const shellReport = htmlReports.find((report) =>
    report.html.includes('The Omarchy system menu is open'),
  );
  if (htmlFiles.length === 2 && !shellReport) {
    throw new Error(
      'Two reports were found but the Omarchy shell report is missing',
    );
  }
  const checks =
    shellReport && htmlFiles.length === 2
      ? extractShellEvidence(shellReport.html)
      : null;
  if (checks?.some((check) => !check.passed)) {
    throw new Error(
      'Cannot publish a passing showcase with failed visual assertions',
    );
  }
  const usage = collectModelUsage(
    htmlReports.map((report) => report.html).join('\n'),
  );
  const reportPrefix = `reports/${runId}`;
  const files = checks
    ? [
        'index.html',
        'shell-report.html',
        'onboarding-report.html',
        'menu.jpg',
        'bar.jpg',
      ].map((name) => `${reportPrefix}/${name}`)
    : [`${reportPrefix}/index.html`];
  const current = {
    runId,
    generatedAt,
    label,
    successRate: 100,
    testCount: checks ? 3 : 1,
    ...usage,
    workflowUrl,
    reportPath: `reports/${runId}/index.html`,
    files,
  };

  const history = (await fetchHistory(baseUrl))
    .filter((report) => report.runId !== runId)
    .slice(0, retention - 1);

  await mkdir(siteDirectory, { recursive: true });
  for (const report of history) {
    await restoreReport(baseUrl, siteDirectory, report);
  }

  const currentDirectory = path.join(siteDirectory, reportPrefix);
  await mkdir(currentDirectory, { recursive: true });
  if (checks) {
    const onboardingReport = htmlReports.find(
      (report) => report !== shellReport,
    );
    await copyFile(
      shellReport.file,
      path.join(currentDirectory, 'shell-report.html'),
    );
    await copyFile(
      onboardingReport.file,
      path.join(currentDirectory, 'onboarding-report.html'),
    );
    await writeFile(
      path.join(currentDirectory, 'menu.jpg'),
      checks[1].screenshot.bytes,
    );
    await writeFile(
      path.join(currentDirectory, 'bar.jpg'),
      checks[2].screenshot.bytes,
    );
    await writeFile(
      path.join(currentDirectory, 'index.html'),
      buildOmarchyShowcase(checks, workflowUrl),
    );
  } else {
    await copyFile(htmlFiles[0], path.join(currentDirectory, 'index.html'));
  }

  const reports = [current, ...history];
  const manifest = {
    version: MANIFEST_VERSION,
    generatedAt,
    retention,
    reports,
  };
  await mkdir(path.join(siteDirectory, 'reports'), { recursive: true });
  await writeFile(
    path.join(siteDirectory, 'reports', 'manifest.json'),
    `${JSON.stringify(manifest, null, 2)}\n`,
  );
  await writeFile(path.join(siteDirectory, 'index.html'), buildIndex(reports));
  return manifest;
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  const manifest = await buildPagesReport(options);
  process.stdout.write(
    `Prepared ${manifest.reports.length} report(s); newest run is ${manifest.reports[0].runId}.\n`,
  );
}

if (import.meta.url === new URL(process.argv[1], 'file:').href) {
  main().catch((error) => {
    process.stderr.write(`${error.stack ?? error.message}\n`);
    process.exitCode = 1;
  });
}
