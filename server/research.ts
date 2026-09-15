import { randomUUID } from "node:crypto";
import { spawn, type ChildProcess } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { Input, Run } from "./workbench.ts";

type Body = Record<string, unknown>;
type Candidate = Omit<
  Input,
  "id" | "experiment_id" | "source_dir" | "source_hash" | "configuration_id"
>;
type Dependencies = {
  all: <T>(kind: string) => T[];
  get: <T>(kind: string, id: string) => T;
  put: (kind: string, id: string, value: unknown) => void;
  buildInputs: (body: Body) => Candidate[];
  snapshot: () => { folder: string; digest: string };
  enqueue: (input: Input) => Run;
  cancel: (id: string) => Run;
  pump: () => void;
  state: string;
  python: string;
  cleanEnvironment: () => NodeJS.ProcessEnv;
  stopProcess: (process: ChildProcess) => void;
  runDir: (id: string) => string;
  hash: (value: string | Buffer) => string;
};
type Fold = {
  index: number;
  train_start: string;
  train_end: string;
  test_start: string;
  test_end: string;
  training: string[];
  tests: string[];
  selection?: {
    run_id: string;
    candidate: number;
    score: number;
    selected_at: string;
    permitted_through: string;
    ranked: {
      run_id: string;
      candidate: number;
      score: number | null;
      eligible: boolean;
    }[];
  };
};
type Plan = {
  scenarios?: string[];
  name: string;
  candidates: Candidate[];
  folds: Fold[];
  jobs: number;
  metric: string;
  min_trades: number;
  min_return: number;
  max_drawdown: number;
  min_test_trades: number;
  stress_multiple: number;
  delay_bars: number;
  hypothesis: string;
};
export type Evaluation = Plan & {
  id: string;
  status: string;
  created_at: string;
  source_dir: string;
  source_hash: string;
  error?: string;
  note?: string;
  ended_at?: string;
  outcome?: string;
  inspected_overlap: string[];
  result?: Body;
};
type Regime = {
  id: string;
  evaluation_id: string;
  status: string;
  created_at: string;
  feature: string;
  window: number;
  quantile: number;
  seed: number;
  error?: string;
  result?: Body;
};
const stamp = () => new Date().toISOString();
const plus = (date: string, days: number) =>
  new Date(Date.parse(date) + days * 86400000).toISOString().slice(0, 10);
function number(
  value: unknown,
  label: string,
  low: number,
  high: number,
  integer = false,
) {
  if (
    typeof value !== "number" ||
    !Number.isFinite(value) ||
    value < low ||
    value > high ||
    (integer && !Number.isInteger(value))
  )
    throw new Error(
      `${label}: expected ${integer ? "integer" : "number"} from ${low} to ${high}`,
    );
  return value;
}

export function createResearch(d: Dependencies) {
  const processors = new Map<string, ChildProcess>();
  for (const record of d.all<Evaluation>("evaluation"))
    if (record.status === "Summarizing") {
      record.status = "Running";
      d.put("evaluation", record.id, record);
    }
  for (const record of d.all<Regime>("regime"))
    if (record.status === "Running") {
      record.status = "Interrupted";
      record.error =
        "Analysis supervisor restarted; create a new investigation.";
      d.put("regime", record.id, record);
    }

  function preview(body: Body): Plan {
    const trainDays = number(
      body.train_days ?? 60,
      "Training days",
      7,
      2000,
      true,
    );
    const testDays = number(body.test_days ?? 30, "Test days", 7, 365, true);
    const count = number(body.folds ?? 3, "Fold count", 1, 12, true);
    const metric = String(body.metric ?? "net_pnl");
    if (!["net_pnl", "sharpe"].includes(metric))
      throw new Error("Selection metric must be net_pnl or sharpe");
    const base = body.base as Body;
    if (!base || typeof base !== "object")
      throw new Error("A base run configuration is required");
    const candidates = d.buildInputs({
      ...base,
      stage: "Exploratory",
      development_end: "",
      criteria: "",
      sweep: body.sweep || {},
      dataset_ids: [base.dataset_id],
      timeframes: [base.timeframe],
    });
    if (candidates.length > 12)
      throw new Error("At most 12 parameter candidates per fold");
    const eventModel = candidates.some(
      (c) => c.strategy.execution_model === "event-v1",
    );
    const delay = number(
      body.delay_bars ?? (eventModel ? 0 : 1),
      "Additional delay bars",
      0,
      20,
      true,
    );
    if (eventModel && delay > 0)
      throw new Error(
        "Walk-forward delay stress is not implemented for Pine event orders. Set additional delay to zero for baseline and higher-cost evaluation and regime analysis.",
      );
    const scenarios = [
      "Baseline",
      "Higher costs",
      ...(delay > 0 ? ["Delayed execution"] : []),
    ];
    const jobs = count * (candidates.length + scenarios.length);
    if (jobs > 100) throw new Error("Evaluation exceeds the 100-job limit");
    if ((candidates[0].delay_bars || 0) + delay > 20)
      throw new Error("Combined execution delay exceeds 20 bars");
    const start = candidates[0].start;
    const folds = Array.from({ length: count }, (_, index) => {
      const train_start = plus(start, index * testDays),
        train_end = plus(train_start, trainDays - 1);
      const test_start = plus(train_end, 1),
        test_end = plus(test_start, testDays - 1);
      if (test_end > candidates[0].end)
        throw new Error(
          `Fold ${index + 1} ends ${test_end}, beyond the selected end date. Extend the interval or reduce fold sizes.`,
        );
      return {
        index,
        train_start,
        train_end,
        test_start,
        test_end,
        training: [],
        tests: [],
      };
    });
    return {
      name: String(body.name || "Walk-forward experiment").slice(0, 120),
      candidates,
      folds,
      jobs,
      scenarios,
      metric,
      min_trades: number(
        body.min_trades ?? 1,
        "Minimum training trades",
        0,
        100000,
        true,
      ),
      min_return: number(body.min_return ?? 0, "Minimum test return", -1, 100),
      max_drawdown: number(
        body.max_drawdown ?? 0.2,
        "Maximum test drawdown",
        0,
        1,
      ),
      min_test_trades: number(
        body.min_test_trades ?? 10,
        "Minimum total test trades",
        1,
        100000,
        true,
      ),
      stress_multiple: number(
        body.stress_multiple ?? 2,
        "Cost multiplier",
        1,
        10,
      ),
      delay_bars: delay,
      hypothesis: String(body.hypothesis || "").slice(0, 2000),
    };
  }

  function launch(body: Body) {
    const plan = preview(body),
      source = d.snapshot(),
      id = randomUUID();
    for (const c of plan.candidates)
      if (
        d.hash(readFileSync(join(source.folder, c.strategy.file))) !==
        c.strategy.file_hash
      )
        throw new Error("Strategy changed; refresh and preview again");
    const overlap = d
      .all<Run>("run")
      .filter(
        (r) =>
          r.status === "Succeeded" &&
          r.input.dataset.symbol === plan.candidates[0].dataset.symbol &&
          r.input.end >= plan.folds[0].test_start &&
          r.input.start <= plan.folds.at(-1)!.test_end,
      )
      .map((r) => r.id);
    const record: Evaluation = {
      ...plan,
      id,
      created_at: stamp(),
      status: "Running",
      source_dir: source.folder,
      source_hash: source.digest,
      inspected_overlap: overlap,
    };
    d.put("evaluation", id, record);
    advance();
    return d.get<Evaluation>("evaluation", id);
  }

  function makeInput(
    record: Evaluation,
    fold: Fold,
    candidate: number,
    role: string,
    scenario: string,
  ): Input {
    const c = record.candidates[candidate];
    const cost = scenario === "Higher costs" ? record.stress_multiple : 1;
    const input: Input = {
      ...c,
      id: "",
      experiment_id: record.id,
      source_dir: record.source_dir,
      source_hash: record.source_hash,
      start: role === "Training" ? fold.train_start : fold.test_start,
      end: role === "Training" ? fold.train_end : fold.test_end,
      stage: role === "Training" ? "Exploratory" : "Evaluation",
      development_end: role === "Training" ? "" : fold.train_end,
      selection_time: fold.selection?.selected_at || record.created_at,
      fee: c.fee * cost,
      slippage: c.slippage * cost,
      delay_bars:
        (c.delay_bars || 0) +
        (scenario === "Delayed execution" ? record.delay_bars : 0),
      criteria: `Net return >= ${record.min_return}; drawdown <= ${record.max_drawdown}; trades >= ${record.min_test_trades} across test folds`,
      hypothesis: record.hypothesis,
      configuration_id: "",
      research: {
        evaluation_id: record.id,
        fold: fold.index,
        role,
        candidate,
        scenario,
      },
    };
    if (input.delay_bars! > 20)
      throw new Error("Combined execution delay exceeds 20 bars");
    input.configuration_id = d.hash(
      JSON.stringify({
        source: input.source_hash,
        parameters: input.parameters,
        symbol: input.dataset.symbol,
        timeframe: input.timeframe,
        session: input.session,
        capital: input.capital,
        fee: input.fee,
        slippage: input.slippage,
        delay: input.delay_bars,
      }),
    );
    return input;
  }

  function fail(record: Evaluation, message: string) {
    record.status = "Failed";
    record.error = message;
    record.ended_at = stamp();
    d.put("evaluation", record.id, record);
  }
  function enqueueOnce(input: Input): string {
    const tag = input.research!;
    const existing = d.all<Run>("run").find((r) => {
      const other = r.input.research;
      return (
        other &&
        other.evaluation_id === tag.evaluation_id &&
        other.fold === tag.fold &&
        other.role === tag.role &&
        other.candidate === tag.candidate &&
        other.scenario === tag.scenario &&
        !r.input.retry_of
      );
    });
    return existing?.id || d.enqueue(input).id;
  }
  function advance() {
    for (const record of d
      .all<Evaluation>("evaluation")
      .filter((r) => r.status === "Running")) {
      try {
        let complete = true;
        for (const fold of record.folds) {
          if (!fold.training.length) {
            fold.training = record.candidates.map((_, i) =>
              enqueueOnce(makeInput(record, fold, i, "Training", "Training")),
            );
            d.put("evaluation", record.id, record);
            complete = false;
            break;
          }
          const training = fold.training.map((id) => d.get<Run>("run", id));
          if (
            training.some((r) =>
              ["Failed", "Canceled", "Interrupted"].includes(r.status),
            )
          ) {
            fail(
              record,
              `Fold ${fold.index + 1}: a training candidate did not succeed. All attempts are retained; no selection was made from an incomplete grid.`,
            );
            complete = false;
            break;
          }
          if (training.some((r) => r.status !== "Succeeded")) {
            complete = false;
            break;
          }
          if (!fold.selection) {
            const ranked = training.map((run, candidate) => {
              const m = run.result?.metrics as Record<string, number | null>;
              const score = m[record.metric];
              return {
                run_id: run.id,
                candidate,
                score,
                eligible:
                  typeof score === "number" &&
                  Number.isFinite(score) &&
                  (m.trades || 0) >= record.min_trades,
              };
            });
            const winner = ranked
              .filter((r) => r.eligible)
              .sort(
                (a, b) => b.score! - a.score! || a.candidate - b.candidate,
              )[0];
            if (!winner) {
              record.status = "Succeeded";
              record.outcome = "Inconclusive";
              record.note = `Fold ${fold.index + 1}: no candidate meets the predeclared selection rule (finite ${record.metric}, minimum trades). The protocol stopped without further test jobs.`;
              record.ended_at = stamp();
              d.put("evaluation", record.id, record);
              complete = false;
              break;
            }
            fold.selection = {
              run_id: winner.run_id,
              candidate: winner.candidate,
              score: winner.score!,
              selected_at: stamp(),
              permitted_through: fold.train_end,
              ranked,
            };
            d.put("evaluation", record.id, record); // Selection is durable BEFORE test jobs exist.
          }
          if (!fold.tests.length) {
            fold.tests = (
              record.scenarios || [
                "Baseline",
                "Higher costs",
                "Delayed execution",
              ]
            ).map((scenario) =>
              enqueueOnce(
                makeInput(
                  record,
                  fold,
                  fold.selection!.candidate,
                  "Test",
                  scenario,
                ),
              ),
            );
            d.put("evaluation", record.id, record);
            complete = false;
            break;
          }
          const tests = fold.tests.map((id) => d.get<Run>("run", id));
          if (
            tests.some((r) =>
              ["Failed", "Canceled", "Interrupted"].includes(r.status),
            )
          ) {
            fail(
              record,
              `Fold ${fold.index + 1}: a test scenario did not succeed; no complete evaluation result is published.`,
            );
            complete = false;
            break;
          }
          if (tests.some((r) => r.status !== "Succeeded")) {
            complete = false;
            break;
          }
        }
        if (complete && !processors.size) summarize(record);
      } catch (e) {
        fail(record, String(e));
      }
    }
    if (!processors.size) {
      const task = d
        .all<Regime>("regime")
        .reverse()
        .find((r) => r.status === "Queued");
      if (task) investigate(task);
    }
    d.pump();
  }

  function pythonAnalysis(
    kind: string,
    id: string,
    source: string,
    payload: Body,
    finish: (error?: string, result?: Body) => void,
  ) {
    const folder = join(d.state, kind, id);
    mkdirSync(folder, { recursive: true });
    const path = join(folder, "request.json");
    writeFileSync(path, JSON.stringify(payload, null, 2));
    const child = spawn(d.python, ["-m", "workbench.research", kind, path], {
      cwd: source,
      env: { ...d.cleanEnvironment(), PYTHONPATH: source },
      windowsHide: true,
      detached: process.platform !== "win32",
    });
    processors.set(id, child);
    let log = "",
      error = "";
    const capture = (chunk: Buffer) => {
      log = (log + chunk.toString()).slice(-100000);
      writeFileSync(join(folder, "process.log"), log);
    };
    child.stdout?.on("data", capture);
    child.stderr?.on("data", capture);
    child.on("error", (e) => {
      error = e.message;
    });
    const timeout = setTimeout(() => {
      error = "Research analysis timed out after 180 seconds";
      d.stopProcess(child);
    }, 180000);
    child.on("close", (code) => {
      clearTimeout(timeout);
      processors.delete(id);
      try {
        if (code !== 0 || error)
          throw new Error(error || log || `Analysis exited ${code}`);
        const result = JSON.parse(
          readFileSync(join(folder, "result.json"), "utf8"),
        );
        finish(undefined, result);
      } catch (e) {
        finish(String(e));
      }
    });
  }

  function summarize(record: Evaluation) {
    record.status = "Summarizing";
    d.put("evaluation", record.id, record);
    pythonAnalysis(
      "evaluations",
      record.id,
      record.source_dir,
      {
        evaluation: record,
        runs: record.folds
          .flatMap((f) => f.tests)
          .map((id) => ({ ...d.get<Run>("run", id), folder: d.runDir(id) })),
      },
      (error, result) => {
        const current = d.get<Evaluation>("evaluation", record.id);
        if (current.status === "Canceled") return;
        if (error) return fail(current, error);
        current.result = result;
        current.status = "Succeeded";
        current.outcome = String(result!.outcome);
        current.ended_at = stamp();
        d.put("evaluation", current.id, current);
      },
    );
  }
  function abort(id: string) {
    const record = d.get<Evaluation>("evaluation", id);
    if (!["Running", "Summarizing"].includes(record.status))
      throw new Error("Evaluation is already terminal");
    record.status = "Canceled";
    record.ended_at = stamp();
    d.put("evaluation", id, record);
    for (const fold of record.folds)
      for (const runId of [...fold.training, ...fold.tests])
        if (["Queued", "Running"].includes(d.get<Run>("run", runId).status))
          d.cancel(runId);
    const child = processors.get(id);
    if (child) d.stopProcess(child);
    return record;
  }
  function regime(evaluationId: string, body: Body) {
    const record = d.get<Evaluation>("evaluation", evaluationId);
    if (record.status !== "Succeeded" || !record.result)
      throw new Error(
        "Regime investigation requires a complete walk-forward evaluation",
      );
    const feature = String(body.feature || "volatility");
    if (!["volatility", "trend"].includes(feature))
      throw new Error("Unknown state feature");
    const task: Regime = {
      id: randomUUID(),
      evaluation_id: evaluationId,
      created_at: stamp(),
      status: "Queued",
      feature,
      window: number(body.window ?? 20, "Feature lookback bars", 2, 500, true),
      quantile: number(body.quantile ?? 0.5, "Training quantile", 0.1, 0.9),
      seed: number(body.seed ?? 42, "Bootstrap seed", 0, 2147483647, true),
    };
    d.put("regime", task.id, task);
    return task;
  }
  function investigate(task: Regime) {
    const record = d.get<Evaluation>("evaluation", task.evaluation_id);
    task.status = "Running";
    d.put("regime", task.id, task);
    const runs = record.folds.map((f) => {
      const id = f.tests[0];
      return { ...d.get<Run>("run", id), folder: d.runDir(id) };
    });
    pythonAnalysis(
      "regimes",
      task.id,
      record.source_dir,
      { task, evaluation: record, runs },
      (error, result) => {
        task.status = error ? "Failed" : "Succeeded";
        task.error = error;
        task.result = result;
        d.put("regime", task.id, task);
      },
    );
  }
  function detail(id: string) {
    const record = d.get<Evaluation>("evaluation", id);
    return {
      ...record,
      runs: record.folds
        .flatMap((f) => [...f.training, ...f.tests])
        .map((id) => d.get<Run>("run", id)),
    };
  }
  function artifact(id: string, name: string, kind: string) {
    if (!["evaluations", "regimes"].includes(kind))
      throw new Error("Unknown artifact kind");
    d.get(kind === "evaluations" ? "evaluation" : "regime", id);
    if (
      ![
        "result.json",
        "equity.csv",
        "observations.csv",
        "request.json",
        "process.log",
      ].includes(name)
    )
      throw new Error("Unknown artifact");
    const path = join(d.state, kind, id, name);
    if (!existsSync(path)) throw new Error("Artifact not yet available");
    return path;
  }
  return {
    preview,
    launch,
    advance,
    abort,
    regime,
    detail,
    artifact,
    stop: () => {
      for (const child of processors.values()) d.stopProcess(child);
    },
  };
}
