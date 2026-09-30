import { spawnSync } from "node:child_process";

const commands = [
  "test:state-warmup",
  "test:library-browser",
  "test:pine-browser",
  "test:research-api",
  "test:research-browser",
  "test:browser",
];

if (process.env.WORKBENCH_REAL_DATA !== "1") {
  console.error(
    "Real-data validations are opt-in because they use the running workbench and may create durable runs.\n" +
      "Start an idle workbench, set WORKBENCH_REAL_DATA=1, then run npm run test:real-data.\n" +
      `Suites: ${commands.join(", ")}`,
  );
  process.exit(2);
}

const npmCli = process.env.npm_execpath;
const npm = npmCli ? process.execPath : process.platform === "win32" ? "npm.cmd" : "npm";
for (const command of commands) {
  console.log(`\nReal-data validation: npm run ${command}`);
  const result = spawnSync(npm, npmCli ? [npmCli, "run", command] : ["run", command], {
    env: process.env,
    stdio: "inherit",
    windowsHide: true,
  });
  if (result.error) {
    console.error(result.error.message);
    process.exit(1);
  }
  if (result.status !== 0) process.exit(result.status ?? 1);
}
