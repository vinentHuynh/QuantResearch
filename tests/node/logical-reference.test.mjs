import assert from "node:assert/strict";
import { test } from "node:test";

import { logicalReference } from "../../server/core/validation.ts";

test("protocol-v2 logical references use canonical forward-slash paths", () => {
  assert.equal(
    logicalReference("datasets/fixture.parquet", "Dataset path"),
    "datasets/fixture.parquet",
  );
  for (const value of [
    "datasets//fixture.parquet",
    "datasets/./fixture.parquet",
    "datasets/../fixture.parquet",
    "C:fixture.parquet",
    "C:/fixture.parquet",
    "/datasets/fixture.parquet",
    "datasets\\fixture.parquet",
  ])
    assert.throws(
      () => logicalReference(value, "Dataset path"),
      /canonical logical reference/,
      value,
    );
});
