import { ApiError } from "../api/client.ts";
import type { MessageKey } from "./LanguageProvider.tsx";

const KNOWN = [
  "invalid_request",
  "not_found",
  "conflict",
  "rate_limited",
  "quota_exhausted",
  "network_error",
  "internal_error",
  "payload_too_large",
];

// The message key that explains an error to the visitor
export function errorKey(error: unknown): MessageKey {
  return codeKey(error instanceof ApiError ? error.code : "internal_error");
}

// The message key for an API error code
export function codeKey(code: string): MessageKey {
  return (KNOWN.includes(code) ? `errors.${code}` : "errors.internal_error") as MessageKey;
}
