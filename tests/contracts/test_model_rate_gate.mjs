import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import http from 'node:http';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { once } from 'node:events';
import test from 'node:test';

const listen = (server) => new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const close = (server) => new Promise((resolve) => server.close(resolve));
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function withGate(handler, env, run) {
  const upstream = http.createServer(handler);
  await listen(upstream);
  const probe = http.createServer();
  await listen(probe);
  const port = probe.address().port;
  await close(probe);
  const directory = await mkdtemp(path.join(tmpdir(), 'model-gate-'));
  const stateFile = path.join(directory, 'count.json');
  const gate = spawn(process.execPath, ['tests/e2e/model-rate-gate.mjs'], {
    env: {
      ...process.env,
      MIDSCENE_RATE_GATE_UPSTREAM: `http://127.0.0.1:${upstream.address().port}/api/v3`,
      MIDSCENE_RATE_GATE_PORT: String(port),
      MIDSCENE_RATE_GATE_INTERVAL_MS: '0',
      MIDSCENE_RATE_GATE_STATE_FILE: stateFile,
      ...env,
    },
    stdio: 'ignore',
  });
  const exited = once(gate, 'exit');
  const base = `http://127.0.0.1:${port}`;
  try {
    let ready = false;
    for (let attempt = 0; attempt < 100 && gate.exitCode === null; attempt++) {
      try { ready = (await fetch(`${base}/healthz`)).ok; } catch { /* startup */ }
      if (ready) break;
      await pause(20);
    }
    assert.equal(ready, true, 'rate gate starts');
    await run({
      send: (body = '{"prompt":"private-test-prompt"}') => fetch(`${base}/chat/completions`, {
        method: 'POST',
        headers: { authorization: 'Bearer private-test-key', 'content-type': 'application/json' }, body,
      }),
      health: () => fetch(`${base}/healthz`), stateFile, directory,
    });
  } finally {
    gate.kill();
    await exited;
    upstream.closeAllConnections();
    await close(upstream);
    await rm(directory, { recursive: true, force: true });
  }
}

test('forwards model requests and spaces starts without changing payloads', async () => {
  const received = [];
  await withGate(async (request, response) => {
    let body = '';
    for await (const chunk of request) body += chunk;
    received.push({ at: Date.now(), path: request.url, authorization: request.headers.authorization, body });
    response.writeHead(200, { 'content-type': 'application/json' }).end('{"ok":true}');
  }, { MIDSCENE_RATE_GATE_INTERVAL_MS: '100' }, async ({ send }) => {
    const responses = await Promise.all([send('{"call":1}'), send('{"call":2}')]);
    assert.deepEqual(await Promise.all(responses.map(response => response.json())), [{ ok: true }, { ok: true }]);
    assert.deepEqual(received.map(({ path }) => path), ['/api/v3/chat/completions', '/api/v3/chat/completions']);
    assert.deepEqual(received.map(({ authorization }) => authorization), ['Bearer private-test-key', 'Bearer private-test-key']);
    assert.deepEqual(received.map(({ body }) => body).sort(), ['{"call":1}', '{"call":2}']);
    assert.ok(received[1].at - received[0].at >= 70);
  });
});

test('concurrent requests cannot exceed 32; health checks are free and telemetry is sanitized', async () => {
  let received = 0;
  await withGate((_request, response) => {
    received++;
    response.end('ok');
  }, { MIDSCENE_RATE_GATE_MAX_REQUESTS: '32', MIDSCENE_RATE_GATE_INTERVAL_MS: '5' }, async ({ send, health, stateFile }) => {
    for (let index = 0; index < 5; index++) assert.equal((await health()).status, 200);
    const responses = await Promise.all(Array.from({ length: 48 }, () => send()));
    await Promise.all(responses.map(response => response.text()));
    assert.equal(responses.filter(response => response.status === 200).length, 32);
    assert.equal(responses.filter(response => response.status === 429).length, 16);
    assert.equal(received, 32);
    assert.equal((await health()).status, 200);
    const raw = await readFile(stateFile, 'utf8');
    assert.equal(raw.includes('private-test'), false);
    assert.deepEqual(JSON.parse(raw), {
      version: 1, maxRequests: 32, reservedRequests: 32, forwardedRequests: 32,
      rejectedRequests: 16, upstreamFailures: 0, upstreamRejections: 0,
    });
  });
});

test('upstream rate limits and connection failures consume the request budget', async () => {
  let received = 0;
  await withGate((request, response) => {
    if (++received === 1) response.writeHead(429).end('upstream limit');
    else request.socket.destroy();
  }, { MIDSCENE_RATE_GATE_MAX_REQUESTS: '2' }, async ({ send, stateFile }) => {
    assert.equal((await send()).status, 429);
    assert.equal((await send()).status, 502);
    assert.equal((await send()).status, 429);
    assert.equal(received, 2);
    const state = JSON.parse(await readFile(stateFile, 'utf8'));
    assert.equal(state.reservedRequests, 2);
    assert.equal(state.upstreamRejections, 1);
    assert.equal(state.upstreamFailures, 1);
  });
});

test('unwritable budget telemetry fails closed without contacting upstream', async () => {
  let received = 0;
  await withGate((_request, response) => { received++; response.end('ok'); },
    { MIDSCENE_RATE_GATE_MAX_REQUESTS: '32' }, async ({ send, health, directory }) => {
      await rm(directory, { recursive: true });
      assert.equal((await send()).status, 503);
      assert.equal((await send()).status, 503);
      assert.equal((await health()).status, 503);
      assert.equal(received, 0);
    });
});

test('invalid request caps fail closed at startup', async () => {
  for (const value of ['', '0', '-1', 'NaN', '1.5', 'Infinity']) {
    const child = spawn(process.execPath, ['tests/e2e/model-rate-gate.mjs'], {
      env: { ...process.env, MIDSCENE_RATE_GATE_UPSTREAM: 'http://127.0.0.1:1', MIDSCENE_RATE_GATE_MAX_REQUESTS: value },
      stdio: 'ignore',
    });
    const [code] = await once(child, 'exit');
    assert.notEqual(code, 0, value);
  }
});
