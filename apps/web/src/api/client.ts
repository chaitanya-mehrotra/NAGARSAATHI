import type { components } from "@nagarsaathi/contracts";

export type PublicConfig = components["schemas"]["PublicConfig"];
export type HealthResponse = components["schemas"]["HealthResponse"];
export type Actor = components["schemas"]["Actor"];
export type ReportDetail = components["schemas"]["ReportDetail"];
export type ReportPage = components["schemas"]["ReportPage"];
export type UploadReceipt = components["schemas"]["UploadReceipt"];
export type IssueSummary = components["schemas"]["IssueSummary"];
export type IssueDetail = components["schemas"]["IssueDetail"];
export type DuplicateReview = components["schemas"]["DuplicateReview"];
export type PriorityView = components["schemas"]["PriorityView"];
export type Policy = components["schemas"]["Policy"];

export async function api<T>(
  path: string,
  token: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...init.headers,
      Authorization: `Bearer ${token}`,
    },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.message || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export async function getJson<T>(
  path: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(path, { signal });
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json() as Promise<T>;
}
