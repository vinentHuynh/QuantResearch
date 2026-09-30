import { createHash, randomUUID } from "node:crypto";
import {
  mkdirSync,
  writeFileSync,
  readFileSync,
  existsSync,
  renameSync,
  realpathSync,
} from "node:fs";
import { join, resolve, sep } from "node:path";
import { isDeepStrictEqual } from "node:util";
import type { DatabaseSync } from "node:sqlite";
import type { Run } from "../../core/contracts.ts";

type RecordValue = { id: string; [key: string]: unknown };
type Dependencies = {
  db: DatabaseSync;
  state: string;
  all: <T>(kind: string) => T[];
  put: (kind: string, id: string, body: unknown) => void;
  raw: (kind: string, id: string) => string | undefined;
  active: (id: string) => boolean;
};
const ongoing = (status: unknown) =>
  ["Queued", "Running", "Summarizing"].includes(String(status));

export function createRunDeletion(d: Dependencies) {
  function plan(ids: unknown) {
    if (
      !Array.isArray(ids) ||
      !ids.length ||
      ids.some((id) => typeof id !== "string")
    )
      throw new Error("Select at least one run to delete");
    const runs = d.all<Run>("run");
    const chosen = new Set<string>(ids);
    if (ids.some((id) => !runs.some((run) => run.id === id)))
      throw new Error("A selected run no longer exists; refresh the ledger");
    const evaluations = d.all<RecordValue>("evaluation"),
      watches = d.all<RecordValue>("watch");
    const evaluationIds = new Set<string>(),
      watchIds = new Set<string>();
    let size = -1;
    while (size !== chosen.size + evaluationIds.size + watchIds.size) {
      size = chosen.size + evaluationIds.size + watchIds.size;
      for (const run of runs) {
        const evaluation = run.input.research?.evaluation_id;
        if (chosen.has(run.id) && evaluation) evaluationIds.add(evaluation);
        if (chosen.has(run.id) && run.watch_id) watchIds.add(run.watch_id);
        if (
          (evaluation && evaluationIds.has(evaluation)) ||
          (run.watch_id && watchIds.has(run.watch_id)) ||
          (run.input.retry_of && chosen.has(run.input.retry_of))
        )
          chosen.add(run.id);
      }
      for (const watch of watches)
        if (chosen.has(String(watch.run_id)) || watchIds.has(watch.id)) {
          watchIds.add(watch.id);
          if (runs.some((run) => run.id === watch.run_id))
            chosen.add(String(watch.run_id));
        }
    }
    const affected = runs.filter((run) => chosen.has(run.id));
    const groups = evaluations.filter((e) => evaluationIds.has(e.id));
    const regimes = d
      .all<RecordValue>("regime")
      .filter((r) => evaluationIds.has(String(r.evaluation_id)));
    if (
      affected.some((r) => ongoing(r.status) || d.active(r.id)) ||
      [...groups, ...regimes].some((r) => ongoing(r.status))
    )
      throw new Error(
        "Cancel active runs/research and wait for them to stop before deleting",
      );
    const experiments = d
      .all<RecordValue>("experiment")
      .filter((e) => affected.some((r) => r.input.experiment_id === e.id));
    const records = {
      run: affected,
      evaluation: groups,
      regime: regimes,
      watch: watches.filter((w) => watchIds.has(w.id)),
      experiment: experiments,
    };
    const token = createHash("sha256")
      .update(JSON.stringify(records))
      .digest("hex");
    return {
      ids: [...chosen].sort(),
      requested: [...new Set(ids)].sort(),
      token,
      records,
      counts: {
        runs: affected.length,
        evaluations: groups.length,
        regimes: regimes.length,
        watchlist: records.watch.length,
        experiments: experiments.length,
      },
    };
  }
  function preview(ids: unknown) {
    const p = plan(ids);
    return {
      ids: p.requested,
      affected_ids: p.ids,
      token: p.token,
      counts: p.counts,
      explanation:
        "Linked evaluation groups, watchlist histories, and retries are included to avoid broken research records. Files and records are retained in a local deletion backup; datasets, strategy source, presets, and saved views remain available.",
    };
  }
  function remove(ids: unknown, token: unknown) {
    const p = plan(ids);
    if (token !== p.token)
      throw new Error("Deletion scope changed; review a fresh preview");
    const id = randomUUID(),
      folder = join(d.state, "deleted", id);
    mkdirSync(folder, { recursive: true });
    const encoded_records = Object.fromEntries(
      Object.entries(p.records).map(([kind, records]) => [
        kind,
        records.map((record) => {
          const encoded = d.raw(kind, record.id);
          if (encoded === undefined)
            throw new Error(`Record disappeared during deletion: ${kind}/${record.id}`);
          return { id: record.id, body: encoded };
        }),
      ]),
    );
    const archive = {
      id,
      created_at: new Date().toISOString(),
      ...p,
      encoded_records,
    };
    writeFileSync(
      join(folder, "records.json"),
      JSON.stringify(archive, null, 2),
    );
    d.db.exec("BEGIN IMMEDIATE");
    try {
      for (const kind of ["run", "evaluation", "regime", "watch"] as const)
        for (const record of p.records[kind])
          d.db
            .prepare("DELETE FROM records WHERE kind=? AND id=?")
            .run(kind, record.id);
      for (const experiment of p.records.experiment) {
        const remaining = d
          .all<Run>("run")
          .filter((r) => r.input.experiment_id === experiment.id);
        if (!remaining.length)
          d.db
            .prepare("DELETE FROM records WHERE kind=? AND id=?")
            .run("experiment", experiment.id);
        else
          d.put("experiment", experiment.id, {
            ...experiment,
            run_ids: remaining.map((r) => r.id),
            deleted_variants:
              Number(experiment.deleted_variants || 0) +
              p.records.run.filter(
                (r) => r.input.experiment_id === experiment.id,
              ).length,
          });
      }
      d.put("deletion", id, {
        id,
        created_at: archive.created_at,
        counts: p.counts,
        folder,
      });
      d.db.exec("COMMIT");
    } catch (error) {
      d.db.exec("ROLLBACK");
      throw error;
    }
    const warnings: string[] = [];
    // Moving after the database commit avoids broken visible records if the
    // process stops during cleanup. records.json preserves original paths.
    for (const [kind, records] of [
      ["runs", p.records.run],
      ["evaluations", p.records.evaluation],
      ["regimes", p.records.regime],
    ] as const)
      for (const record of records) {
        try {
          if (!/^[a-f0-9-]{36}$/.test(record.id))
            throw new Error("Invalid artifact identifier");
          const base = resolve(d.state, kind),
            from = resolve(base, record.id),
            to = resolve(folder, kind, record.id);
          if (
            !from.startsWith(base + sep) ||
            !to.startsWith(resolve(folder) + sep)
          )
            throw new Error("Artifact path escaped workspace");
          if (!existsSync(from)) continue;
          if (!realpathSync(from).startsWith(realpathSync(base) + sep))
            throw new Error("Artifact link escaped workspace");
          mkdirSync(join(folder, kind), { recursive: true });
          renameSync(from, to);
        } catch (error) {
          warnings.push(
            `${kind}/${record.id}: ${String(error)}; files remain at their original location`,
          );
        }
      }
    return { id, counts: p.counts, backup: folder, warnings };
  }

  function restore(deletionId: unknown) {
    if (
      typeof deletionId !== "string" ||
      !/^[a-f0-9-]{36}$/.test(deletionId)
    )
      throw new Error("Invalid deletion recovery identifier");
    const deletedRoot = resolve(d.state, "deleted"),
      folder = resolve(deletedRoot, deletionId);
    if (!folder.startsWith(`${deletedRoot}${sep}`) || !existsSync(folder))
      throw new Error("Deletion recovery archive not found");
    if (!realpathSync(folder).startsWith(realpathSync(deletedRoot) + sep))
      throw new Error("Deletion recovery archive escaped WORKBENCH_HOME");
    const archive = JSON.parse(
      readFileSync(join(folder, "records.json"), "utf8"),
    ) as {
      id: string;
      counts: Record<string, number>;
      records: Record<string, RecordValue[]>;
      encoded_records?: Record<string, { id: string; body: string }[]>;
    };
    if (
      archive.id !== deletionId ||
      !archive.records ||
      typeof archive.records !== "object"
    )
      throw new Error("Invalid deletion recovery archive");
    const kinds = ["run", "evaluation", "regime", "watch", "experiment"] as const;
    const encoded = Object.fromEntries(
      kinds.map((kind) => {
        const records = Array.isArray(archive.records[kind])
          ? archive.records[kind]
          : [];
        const saved = archive.encoded_records?.[kind];
        const rows = saved ?? records.map((record) => ({
          id: record.id,
          body: JSON.stringify(record),
        }));
        if (
          rows.length !== records.length ||
          rows.some((row, index) =>
            row.id !== records[index].id ||
            typeof row.body !== "string" ||
            !row.id,
          )
        )
          throw new Error(`Invalid ${kind} records in deletion recovery archive`);
        for (const row of rows) {
          const value = JSON.parse(row.body);
          if (!value || typeof value !== "object" || Array.isArray(value))
            throw new Error(`Invalid ${kind} body in deletion recovery archive`);
        }
        return [kind, rows];
      }),
    ) as Record<(typeof kinds)[number], { id: string; body: string }[]>;

    for (const kind of ["run", "evaluation", "regime", "watch"] as const)
      for (const row of encoded[kind])
        if (d.raw(kind, row.id) !== undefined)
          throw new Error(`Cannot recover over existing record: ${kind}/${row.id}`);
    const existingRuns = d.all<Run>("run");
    const existingExperiments = d.all<RecordValue>("experiment");
    for (const original of archive.records.experiment || []) {
      const current = existingExperiments.find((record) => record.id === original.id);
      if (!current) continue;
      const remaining = existingRuns.filter(
        (run) => run.input.experiment_id === original.id,
      );
      const expected = {
        ...original,
        run_ids: remaining.map((run) => run.id),
        deleted_variants:
          Number(original.deleted_variants || 0) +
          (archive.records.run || []).filter(
            (run) =>
              (run as unknown as Run).input.experiment_id === original.id,
          ).length,
      };
      if (!isDeepStrictEqual(current, expected))
        throw new Error(
          `Experiment changed after deletion; recovery refused: ${original.id}`,
        );
    }

    const moves: { from: string; to: string }[] = [];
    for (const [kind, records] of [
      ["runs", archive.records.run || []],
      ["evaluations", archive.records.evaluation || []],
      ["regimes", archive.records.regime || []],
    ] as const)
      for (const record of records) {
        if (!/^[a-f0-9-]{36}$/.test(record.id))
          throw new Error("Invalid artifact identifier in recovery archive");
        const from = resolve(folder, kind, record.id),
          base = resolve(d.state, kind),
          to = resolve(base, record.id);
        if (
          !from.startsWith(`${folder}${sep}`) ||
          !to.startsWith(`${base}${sep}`)
        )
          throw new Error("Recovery artifact path escaped WORKBENCH_HOME");
        if (existsSync(from) && existsSync(to))
          throw new Error(`Cannot recover over existing artifacts: ${kind}/${record.id}`);
        if (existsSync(from)) moves.push({ from, to });
      }

    const completedMoves: { from: string; to: string }[] = [];
    try {
      for (const move of moves) {
        mkdirSync(resolve(move.to, ".."), { recursive: true });
        renameSync(move.from, move.to);
        completedMoves.push(move);
      }
      d.db.exec("BEGIN IMMEDIATE");
      try {
        for (const kind of kinds)
          for (const row of encoded[kind])
            d.db
              .prepare("INSERT OR REPLACE INTO records(kind,id,body) VALUES(?,?,?)")
              .run(kind, row.id, row.body);
        const deletionRecord = d
          .all<RecordValue>("deletion")
          .find((record) => record.id === deletionId);
        d.put("deletion", deletionId, {
          ...(deletionRecord || { id: deletionId, counts: archive.counts, folder }),
          restored_at: new Date().toISOString(),
        });
        d.db.exec("COMMIT");
      } catch (error) {
        d.db.exec("ROLLBACK");
        throw error;
      }
    } catch (error) {
      for (const move of completedMoves.reverse())
        if (existsSync(move.to) && !existsSync(move.from)) {
          mkdirSync(resolve(move.from, ".."), { recursive: true });
          renameSync(move.to, move.from);
        }
      throw error;
    }
    return {
      id: deletionId,
      counts: archive.counts,
      restored: true,
      warnings: archive.encoded_records
        ? []
        : ["Legacy recovery archive lacked byte-exact record bodies."],
    };
  }
  return { preview, remove, restore };
}
