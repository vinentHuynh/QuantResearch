import { Worker } from "node:worker_threads";

export type SupervisorHeartbeat = {
  stop: () => Promise<void>;
};

export async function startSupervisorHeartbeat(
  file: string,
  token: string,
  pid: number,
  onFailure: (error: Error) => void,
): Promise<SupervisorHeartbeat> {
  const worker = new Worker(new URL("./supervisorHeartbeat.worker.mjs", import.meta.url), {
    workerData: { file, token, pid, intervalMs: 2000 },
  });
  let ready = false;
  let stopping = false;
  let failed = false;

  await new Promise<void>((resolve, reject) => {
    const fail = (error: Error) => {
      if (!ready) reject(error);
      else if (!stopping && !failed) {
        failed = true;
        onFailure(error);
      }
    };
    worker.on("message", (message: unknown) => {
      if (message !== "ready" || ready) return;
      ready = true;
      resolve();
    });
    worker.on("error", fail);
    worker.on("exit", code => fail(new Error(`Supervisor heartbeat worker exited ${code}`)));
  });
  worker.unref();
  return {
    stop: async () => {
      stopping = true;
      await worker.terminate();
    },
  };
}
