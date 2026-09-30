import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import {
  Ajv2020,
  type AnySchema,
  type ErrorObject,
  type ValidateFunction,
} from "ajv/dist/2020.js";
import formatsPlugin from "ajv-formats";

function explain(errors: ErrorObject[] | null | undefined) {
  return (errors || [])
    .slice(0, 8)
    .map((error) => `${error.instancePath || "/"} ${error.message}`)
    .join("; ");
}

export function createContractValidation(contractsRoot: string) {
  const ajv = new Ajv2020({
    allErrors: true,
    strict: false,
  });
  const addFormats = formatsPlugin as unknown as (instance: Ajv2020) => Ajv2020;
  addFormats(ajv);
  for (const name of readdirSync(contractsRoot)
    .filter((entry) => entry.endsWith(".schema.json"))
    .sort()) {
    const schema = JSON.parse(
      readFileSync(join(contractsRoot, name), "utf8"),
    ) as AnySchema;
    ajv.addSchema(schema);
  }
  const runInput = ajv.getSchema(
    "https://strategy-workbench.local/contracts/run-input.v2.schema.json",
  ) as ValidateFunction | undefined;
  if (!runInput) throw new Error("Protocol-v2 run input contract is unavailable");
  return {
    runInput(value: unknown) {
      if (!runInput(value))
        throw new Error(
          `Protocol-v2 run input failed contract validation: ${explain(runInput.errors)}`,
        );
    },
  };
}
