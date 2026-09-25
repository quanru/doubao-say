import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import http from 'node:http';
import test from 'node:test';

const listen = (server) => new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const close = (server) => new Promise((resolve) => server.close(resolve));

test('forwards model requests and spaces their starts without changing payloads', async () => {
  const received = [];
  const upstream = http.createServer(async (request, response) => {
    let body = '';
    for await (const chunk of request) body += chunk;
    received.push({ at: Date.now(), path: request.url, authorization: request.headers.authorization, body });
    response.writeHead(200, { 'content-type': 'application/json' }).end('{"ok":true}');
  });
  await listen(upstream);
  const gatePort = upstream.address().port + 1;
  const gate = spawn(process.execPath, ['tests/e2e/model-rate-gate.mjs'], {
    env: {
      ...process.env,
      MIDSCENE_RATE_GATE_UPSTREAM: `http://127.0.0.1:${upstream.address().port}/api/v3`,
      MIDSCENE_RATE_GATE_PORT: String(gatePort),
      MIDSCENE_RATE_GATE_INTERVAL_MS: '100',
    },
    stdio: 'ignore',
  });
  try {
    let ready = false;
    for (let attempt = 0; attempt < 50; attempt++) {
      try {
        ready = (await fetch(`http://127.0.0.1:${gatePort}/healthz`)).ok;
        if (ready) break;
      } catch { /* startup */ }
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
    assert.equal(ready, true);
    const send = (body) => fetch(`http://127.0.0.1:${gatePort}/chat/completions`, {
      method: 'POST',
      headers: { authorization: 'Bearer test-key', 'content-type': 'application/json' },
      body,
    });
    const responses = await Promise.all([send('{"call":1}'), send('{"call":2}')]);
    assert.deepEqual(await Promise.all(responses.map((response) => response.json())), [{ ok: true }, { ok: true }]);
    assert.deepEqual(received.map(({ path }) => path), ['/api/v3/chat/completions', '/api/v3/chat/completions']);
    assert.deepEqual(received.map(({ authorization }) => authorization), ['Bearer test-key', 'Bearer test-key']);
    assert.deepEqual(received.map(({ body }) => body).sort(), ['{"call":1}', '{"call":2}']);
    assert.ok(received[1].at - received[0].at >= 70);
  } finally {
    gate.kill();
    await close(upstream);
  }
});
