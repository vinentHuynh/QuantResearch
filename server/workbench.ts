/**
 * One-release compatibility launcher.
 *
 * The active application is composed in server/app; documented commands keep
 * using `node server/workbench.ts` while callers migrate to the new boundary.
 */
export type { Input, Run } from "./core/contracts.ts";
await import("./app/workbenchServer.ts");
