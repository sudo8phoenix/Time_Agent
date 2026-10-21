/** Evidence is served by the authenticated original-report endpoint. */
export function originalEvidenceUrl(value: unknown): string | undefined {
  return typeof value === "string" && /^\/api\/v1\/projects\/[A-Za-z0-9_-]+\/reports\/[A-Za-z0-9_-]+\/original$/.test(value)
    ? value : undefined;
}
