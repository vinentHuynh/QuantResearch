// Compatibility command and import surface for the maintained repository utility.
export * from "../tools/maintenance/check-repo-hygiene.mjs";

import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { main } from "../tools/maintenance/check-repo-hygiene.mjs";

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    process.exitCode = main();
  } catch (error) {
    console.error(`Repository hygiene check could not run: ${error.message}`);
    process.exitCode = 2;
  }
}
