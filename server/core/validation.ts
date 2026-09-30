import type { RecordValue, Strategy } from "./contracts.ts";

export function logicalReference(value: unknown, label: string) {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.startsWith("/") ||
    /^[A-Za-z]:/.test(value) ||
    value.includes("\\") ||
    value
      .split("/")
      .some((part) => part === "" || part === "." || part === "..")
  )
    throw new Error(`${label}: expected a canonical logical reference`);
  return value;
}

export function date(value: unknown, label: string) {
  if (
    typeof value !== "string" ||
    !/^\d{4}-\d{2}-\d{2}$/.test(value) ||
    !Number.isFinite(Date.parse(value)) ||
    new Date(value).toISOString().slice(0, 10) !== value
  )
    throw new Error(`${label}: expected valid YYYY-MM-DD`);
  return value;
}

export function numeric(
  value: unknown,
  label: string,
  minimum: number,
  maximum: number,
  integer = false,
) {
  if (
    typeof value !== "number" ||
    !Number.isFinite(value) ||
    value < minimum ||
    value > maximum ||
    (integer && !Number.isInteger(value))
  )
    throw new Error(
      `${label}: expected ${integer ? "integer" : "number"} from ${minimum} to ${maximum}`,
    );
  return value;
}

export function parameters(strategy: Strategy, supplied: RecordValue) {
  if (!supplied || typeof supplied !== "object" || Array.isArray(supplied))
    throw new Error("Parameters must be an object");
  for (const key of Object.keys(supplied))
    if (!(key in strategy.parameters))
      throw new Error(`Unknown parameter: ${key}`);
  const resolved: RecordValue = {};
  for (const [key, field] of Object.entries(strategy.parameters)) {
    const value = supplied[key] ?? field.default;
    if (["integer", "number"].includes(field.type))
      numeric(
        value,
        key,
        field.minimum ?? -1e10,
        field.maximum ?? 1e10,
        field.type === "integer",
      );
    else if (field.type === "boolean" && typeof value !== "boolean")
      throw new Error(`${key}: expected boolean`);
    else if (
      ["string", "enum"].includes(field.type) &&
      (typeof value !== "string" || value.length > 2000)
    )
      throw new Error(`${key}: expected string`);
    if (field.type === "enum" && !field.choices?.includes(String(value)))
      throw new Error(`${key}: unsupported choice`);
    resolved[key] = value;
  }
  for (const [key, field] of Object.entries(strategy.parameters))
    if (
      field.required_when &&
      Object.entries(field.required_when).every(
        ([conditionKey, expected]) => resolved[conditionKey] === expected,
      ) &&
      resolved[key] === ""
    )
      throw new Error(`${key}: required for this configuration`);
  return resolved;
}
