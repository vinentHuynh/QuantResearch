import { connect } from 'node:net';
import { resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';

function isListening(port, timeoutMs) {
  return new Promise((resolveReady) => {
    const socket = connect({ host: '127.0.0.1', port });
    const finish = (ready) => {
      socket.destroy();
      resolveReady(ready);
    };
    socket.once('connect', () => finish(true));
    socket.once('error', () => finish(false));
    socket.setTimeout(timeoutMs, () => finish(false));
  });
}

// The API only starts listening after its initial catalog refresh completes.
export async function waitForApi({
  port = Number(process.env.WORKBENCH_PORT || 8001),
  timeoutMs = 60_000,
  retryMs = 250,
} = {}) {
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error('WORKBENCH_PORT must be an integer between 1 and 65535.');
  }
  const deadline = performance.now() + timeoutMs;
  while (performance.now() < deadline) {
    const remaining = Math.max(1, deadline - performance.now());
    if (await isListening(port, Math.min(1000, remaining))) return;
    await delay(Math.max(0, Math.min(retryMs, deadline - performance.now())));
  }
  throw new Error(`API did not start listening at http://127.0.0.1:${port} within ${timeoutMs / 1000}s. Check the API output above.`);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  console.log('Waiting for the Workbench API before starting Vite...');
  try {
    await waitForApi();
    console.log('Workbench API is ready. Starting Vite.');
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
