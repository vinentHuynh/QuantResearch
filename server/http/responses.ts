import type { IncomingMessage, ServerResponse } from "node:http";

export async function readJsonBody(
  request: IncomingMessage,
  maximumBytes = 1_000_000,
): Promise<Record<string, unknown>> {
  let raw = "";
  for await (const chunk of request) {
    raw += chunk;
    if (raw.length > maximumBytes) throw new Error("Request too large");
  }
  if (!raw) return {};
  const value: unknown = JSON.parse(raw);
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Request body must be a JSON object");
  return value as Record<string, unknown>;
}

export function sendJson(
  response: ServerResponse,
  data: unknown,
  status = 200,
) {
  response.writeHead(status, { "Content-Type": "application/json" });
  response.end(JSON.stringify(data));
}
