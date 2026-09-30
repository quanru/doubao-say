import http from 'node:http';
import https from 'node:https';
import { existsSync, readFileSync, renameSync, statSync, writeFileSync } from 'node:fs';

// One gate owns a worker's budget. Reserve synchronously, before any scheduling
// await, so concurrent requests and upstream errors cannot overspend the cap.
const upstream = new URL(process.env.MIDSCENE_RATE_GATE_UPSTREAM);
const intervalMs = Number(process.env.MIDSCENE_RATE_GATE_INTERVAL_MS ?? 20000);
const port = Number(process.env.MIDSCENE_RATE_GATE_PORT ?? 18783);
const maxRequests = process.env.MIDSCENE_RATE_GATE_MAX_REQUESTS === undefined
  ? null : Number(process.env.MIDSCENE_RATE_GATE_MAX_REQUESTS);
const stateFile = process.env.MIDSCENE_RATE_GATE_STATE_FILE;
if (!['http:', 'https:'].includes(upstream.protocol) || !Number.isFinite(intervalMs) || intervalMs < 0 ||
    (maxRequests !== null && (!Number.isSafeInteger(maxRequests) || maxRequests < 1)) ||
    (process.env.MIDSCENE_RATE_GATE_REQUIRE_STATE === 'true' && (!stateFile || !existsSync(stateFile)))) {
  throw new Error('Invalid model rate gate configuration or missing required budget state');
}

// This allowlisted telemetry contains no URLs, headers, keys or request bodies.
const counters = ['reservedRequests', 'forwardedRequests', 'rejectedRequests', 'upstreamFailures', 'upstreamRejections'];
let state = { version: 1, maxRequests, ...Object.fromEntries(counters.map(key => [key, 0])) };
if (stateFile && existsSync(stateFile)) {
  try {
    if (statSync(stateFile).size > 4096) throw new Error('Oversized state');
    const saved = JSON.parse(readFileSync(stateFile, 'utf8'));
    if (saved.version !== 1 || saved.maxRequests !== maxRequests ||
        Object.keys(saved).sort().join() !== Object.keys(state).sort().join() ||
        counters.some(key => !Number.isSafeInteger(saved[key]) || saved[key] < 0) ||
        (maxRequests !== null && saved.reservedRequests > maxRequests) ||
        saved.forwardedRequests > saved.reservedRequests ||
        saved.upstreamFailures > saved.forwardedRequests ||
        saved.upstreamRejections > saved.forwardedRequests) throw new Error('Invalid state');
    state = saved;
  } catch {
    throw new Error('Cannot safely restore model request budget');
  }
}
let healthy = true;
const persist = () => {
  if (!healthy) return false;
  if (!stateFile) return true;
  try {
    writeFileSync(`${stateFile}.tmp`, `${JSON.stringify(state)}\n`, { mode: 0o600 });
    renameSync(`${stateFile}.tmp`, stateFile);
    return true;
  } catch {
    // A lost counter must never silently reset or allow unrecorded spending.
    healthy = false;
    return false;
  }
};
if (!persist()) throw new Error('Cannot persist model request budget');

let nextStart = 0;
const server = http.createServer(async (request, response) => {
  if (request.url === '/healthz') {
    response.writeHead(healthy ? 200 : 503).end(healthy ? 'ready' : 'Budget unavailable');
    return;
  }
  if (!healthy) {
    response.writeHead(503).end('Model request budget unavailable');
    return;
  }
  if (maxRequests !== null && state.reservedRequests >= maxRequests) {
    state.rejectedRequests++;
    const status = persist() ? 429 : 503;
    response.writeHead(status, { 'content-type': 'application/json' }).end(JSON.stringify({
      error: { message: 'Model request budget exhausted', type: 'request_budget_exhausted' },
    }));
    return;
  }
  state.reservedRequests++;
  if (!persist()) {
    response.writeHead(503).end('Model request budget unavailable');
    return;
  }
  const scheduled = Math.max(Date.now(), nextStart);
  nextStart = scheduled + intervalMs;
  await new Promise((resolve) => setTimeout(resolve, Math.max(0, scheduled - Date.now())));
  // Abandoned queued calls keep their reservation, conservatively fail-closed.
  if (request.aborted || response.destroyed) return;
  if (!healthy) {
    response.writeHead(503).end('Model request budget unavailable');
    return;
  }
  const path = request.url?.replace(/^\/+/, '') ?? '';
  const target = new URL(`${upstream.pathname.replace(/\/$/, '')}/${path}`, upstream.origin);
  const transport = target.protocol === 'https:' ? https : http;
  const headers = { ...request.headers, host: target.host };
  state.forwardedRequests++;
  if (!persist()) {
    response.writeHead(503).end('Model request budget unavailable');
    return;
  }
  const forwarded = transport.request(target, {
    method: request.method,
    headers,
    timeout: 180000,
  }, (upstreamResponse) => {
    if ((upstreamResponse.statusCode ?? 502) >= 400) {
      state.upstreamRejections++;
      persist();
    }
    response.writeHead(upstreamResponse.statusCode ?? 502, upstreamResponse.headers);
    upstreamResponse.pipe(response);
  });
  forwarded.on('timeout', () => forwarded.destroy(new Error('Model upstream timed out')));
  forwarded.on('error', () => {
    state.upstreamFailures++;
    persist();
    if (!response.headersSent) response.writeHead(502);
    response.end('Model upstream unavailable');
  });
  request.pipe(forwarded);
});

server.listen(port, '127.0.0.1');
