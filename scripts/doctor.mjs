// Compatibility command and import surface for the maintained environment utility.
export * from "../tools/maintenance/doctor.mjs";

import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { main } from "../tools/maintenance/doctor.mjs";

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    process.exitCode = main();
  } catch (error) {
    console.error(`Environment doctor could not run: ${error.message}`);
    process.exitCode = 2;
  }
}
