import http from 'node:http';
import https from 'node:https';

// Each GitHub matrix job has one independent VM and one Midscene worker. Pace
// requests per worker so five concurrent jobs stay below the Ark endpoint RPM.
const upstream = new URL(process.env.MIDSCENE_RATE_GATE_UPSTREAM);
const intervalMs = Number(process.env.MIDSCENE_RATE_GATE_INTERVAL_MS ?? 20000);
const port = Number(process.env.MIDSCENE_RATE_GATE_PORT ?? 18783);
if (!['http:', 'https:'].includes(upstream.protocol) || !Number.isFinite(intervalMs) || intervalMs < 0) {
  throw new Error('Invalid model rate gate configuration');
}

let nextStart = 0;
const server = http.createServer(async (request, response) => {
  if (request.url === '/healthz') {
    response.writeHead(200).end('ready');
    return;
  }

  const path = request.url?.replace(/^\/+/, '') ?? '';
  const target = new URL(`${upstream.pathname.replace(/\/$/, '')}/${path}`, upstream.origin);
  const scheduled = Math.max(Date.now(), nextStart);
  nextStart = scheduled + intervalMs;
  await new Promise((resolve) => setTimeout(resolve, scheduled - Date.now()));

  const transport = target.protocol === 'https:' ? https : http;
  const headers = { ...request.headers, host: target.host };
  const forwarded = transport.request(target, {
    method: request.method,
    headers,
    timeout: 180000,
  }, (upstreamResponse) => {
    response.writeHead(upstreamResponse.statusCode ?? 502, upstreamResponse.headers);
    upstreamResponse.pipe(response);
  });
  forwarded.on('timeout', () => forwarded.destroy(new Error('Model upstream timed out')));
  forwarded.on('error', () => {
    if (!response.headersSent) response.writeHead(502);
    response.end('Model upstream unavailable');
  });
  request.pipe(forwarded);
});

server.listen(port, '127.0.0.1');
