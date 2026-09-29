import type { TestingIssue } from "./testingEvidence";

export const reviewPrefix = "Testing review: ";
export type TestingReview = {
  version: 1;
  sourceHash: string;
  reviewedAt: string;
  runIds: string[];
  issueKeys: string[];
  verdict: string;
  nextStep: string;
};

// A compact change detector, not a security or source-integrity checksum.
export function reviewIssueKey(issue: TestingIssue) {
  const text = JSON.stringify([issue.id, issue.title, issue.reason]);
  let hash = 2166136261;
  for (let i = 0; i < text.length; i++) hash = Math.imul(hash ^ text.charCodeAt(i), 16777619);
  return `${issue.id}:${(hash >>> 0).toString(16)}`;
}

export function readTestingReviews(notes = ""): TestingReview[] {
  return notes.split(/\r?\n/).flatMap(line => {
    if (!line.startsWith(reviewPrefix)) return [];
    try {
      const r = JSON.parse(line.slice(reviewPrefix.length));
      return r.version === 1 && typeof r.sourceHash === "string" && Number.isFinite(Date.parse(r.reviewedAt))
        && Array.isArray(r.runIds) && r.runIds.every((v: unknown) => typeof v === "string")
        && Array.isArray(r.issueKeys) && r.issueKeys.every((v: unknown) => typeof v === "string")
        && typeof r.verdict === "string" && typeof r.nextStep === "string" ? [r as TestingReview] : [];
    } catch { return []; }
  });
}
