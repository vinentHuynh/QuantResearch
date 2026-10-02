import { createHash } from "node:crypto";
import { readdirSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";

import { loadWorkbenchLayout } from "../../layout.ts";

/**
 * Remember the source tree at the start of the last Python discovery attempt.
 * A source edit during discovery must still trigger the next periodic scan.
 */
export function createDiscoveryChangeGate(workspaceRoot: string) {
  const root = resolve(workspaceRoot);
  let scannedSnapshot: string | null = null;

  const paths = (folder: string, suffix: string, recursive: boolean): string[] => {
    let entries;
    try {
      entries = readdirSync(folder, { withFileTypes: true });
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
      throw error;
    }
    const found: string[] = [];
    for (const entry of entries) {
      const filename = join(folder, entry.name);
      if (recursive && entry.isDirectory()) {
        if (![".git", ".venv", "__pycache__", "node_modules", "dist"].includes(entry.name)) {
          found.push(...paths(filename, suffix, true));
        }
      } else if (entry.name.endsWith(suffix) && (entry.isFile() || entry.isSymbolicLink())) {
        found.push(filename);
      }
    }
    return found;
  };

  return {
    snapshot(): string {
      // Reload the layout so a changed discovery root takes effect without an API restart.
      const layout = loadWorkbenchLayout(root);
      const files = new Set<string>([layout.configPath]);
      for (const folder of layout.discoveryPaths.strategy_adapters) {
        for (const filename of paths(folder, ".py", false)) files.add(filename);
      }
      for (const folder of layout.discoveryPaths.python_library) {
        for (const filename of paths(folder, ".py", folder !== root)) files.add(filename);
      }
      for (const folder of layout.discoveryPaths.pine_library) {
        for (const filename of paths(folder, ".pine", folder !== root)) files.add(filename);
      }
      // Execution identities also include Python runtime and declared source
      // dependencies, which can live outside the discovery library folders.
      for (const folder of layout.sourceRoots) {
        for (const filename of paths(folder, ".py", true)) files.add(filename);
      }
      const hash = createHash("sha256");
      for (const filename of [...files].sort()) {
        let stats;
        try {
          stats = statSync(filename, { bigint: true });
        } catch (error) {
          if ((error as NodeJS.ErrnoException).code === "ENOENT") {
            // A rename during enumeration will be seen on the next snapshot.
            continue;
          }
          throw error;
        }
        hash.update(relative(root, filename).replaceAll("\\", "/"));
        hash.update("\0");
        hash.update(String(stats.size));
        hash.update("\0");
        hash.update(String(stats.mtimeNs));
        hash.update("\0");
      }
      return hash.digest("hex");
    },
    needsScan(snapshot: string): boolean {
      return snapshot !== scannedSnapshot;
    },
    markScanned(snapshot: string): void {
      scannedSnapshot = snapshot;
    },
  };
}
