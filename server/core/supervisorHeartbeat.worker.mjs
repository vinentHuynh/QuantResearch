import { writeFileSync } from "node:fs";
import { parentPort, workerData } from "node:worker_threads";

if (!parentPort) throw new Error("Supervisor heartbeat requires a worker thread");

const { file, token, pid, intervalMs } = workerData;
const payload = JSON.stringify({ token, pid });
const writeHeartbeat = () => writeFileSync(file, payload);

writeHeartbeat();
parentPort.postMessage("ready");
setInterval(writeHeartbeat, intervalMs);
