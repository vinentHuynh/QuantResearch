import assert from 'node:assert/strict';
import { once } from 'node:events';
import { createServer } from 'node:net';
import { setTimeout as delay } from 'node:timers/promises';
import test from 'node:test';
import { waitForApi } from '../../scripts/wait-for-api.mjs';

async function listen(server, port = 0) {
  server.listen(port, '127.0.0.1');
  await once(server, 'listening');
  return server.address().port;
}

async function close(server) {
  if (server.listening) await new Promise((resolve) => server.close(resolve));
}

test('readiness waits for a slow API to open its port', async (t) => {
  const server = createServer((socket) => socket.end());
  t.after(() => close(server));
  const port = await listen(server);
  await close(server);

  let ready = false;
  const waiting = waitForApi({ port, timeoutMs: 3000, retryMs: 10 })
    .then(() => { ready = true; });
  await delay(80);
  assert.equal(ready, false, 'Vite must not start before the API listens');
  await listen(server, port);
  await waiting;
  assert.equal(ready, true);
});

test('readiness accepts an API that is already listening', async (t) => {
  const server = createServer((socket) => socket.end());
  t.after(() => close(server));
  const port = await listen(server);
  await waitForApi({ port, timeoutMs: 3000 });
});

test('readiness fails with a useful error when the API never listens', async () => {
  const server = createServer();
  const port = await listen(server);
  await close(server);
  await assert.rejects(
    waitForApi({ port, timeoutMs: 80, retryMs: 10 }),
    /API did not start listening.*Check the API output/,
  );
});

test('readiness rejects invalid API ports immediately', async () => {
  for (const port of [0, -1, 65536, NaN, 8001.5]) {
    await assert.rejects(waitForApi({ port }), /WORKBENCH_PORT must be an integer/);
  }
});
