import { spawn } from "node:child_process";
import type { Input } from "./workbench.ts";

export function previewWarmup(python: string, root: string, env: NodeJS.ProcessEnv, inputs: Input[]): Promise<unknown[]> {
  if (!inputs.some((input) => input.strategy.warmup_bars)) return Promise.resolve([]);
  return new Promise((resolve, reject) => {
    const child = spawn(python, ["-m", "workbench.warmup"], {
      cwd: root, env, windowsHide: true,
    });
    let output = "", error = "";
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("Warmup preview timed out. Reduce the grid and try again."));
    }, 120000);
    child.stdout.on("data", (chunk) => { output += chunk; });
    child.stderr.on("data", (chunk) => { error += chunk; });
    child.on("error", reject);
    child.stdin.on("error", reject);
    child.on("close", (code) => {
      clearTimeout(timer);
      try {
        if (code !== 0) throw new Error(error || "Warmup preview failed");
        resolve(JSON.parse(output));
      } catch (e) { reject(e); }
    });
    child.stdin.end(JSON.stringify(inputs));
  });
}
