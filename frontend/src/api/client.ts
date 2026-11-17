import type { ApiResponse, PageMeta } from "./api.types.ts";

const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const NETWORK_ERROR = "network_error";

// An error the API returned, or a failure to reach it (status 0, code network_error)
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly blockedUntil: string | null;

  constructor(status: number, code: string, message: string, blockedUntil: string | null, options?: ErrorOptions) {
    super(message, options);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.blockedUntil = blockedUntil;
  }
}

// Absolute URL of an API path
export function apiUrl(path: string): string {
  return `${BASE_URL}${path}`;
}

// Send a JSON request and unwrap the response envelope
export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<{ data: T; meta: PageMeta | null }> {
  const response = await send(path, init);

  // 204 has no body
  if (response.status === 204) return { data: null as T, meta: null };

  return readEnvelope<T>(response);
}

// fetch with JSON headers; a network failure becomes ApiError, an abort passes through
export async function send(path: string, init: RequestInit = {}): Promise<Response> {
  try {
    return await fetch(apiUrl(path), {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init.body === undefined ? {} : { "Content-Type": "application/json" }),
        ...init.headers,
      },
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, NETWORK_ERROR, "Cannot reach the server", null, { cause: err });
  }
}

// Read a response as the envelope; throw its error, or network_error when it is not the envelope
export async function readEnvelope<T>(response: Response): Promise<{ data: T; meta: PageMeta | null }> {
  // Anything that is not the JSON envelope (an HTML 502 from a proxy) counts as unreachable
  let body: ApiResponse<T>;
  try {
    body = (await response.json()) as ApiResponse<T>;
  } catch (err) {
    throw new ApiError(0, NETWORK_ERROR, `Unexpected response (${response.status})`, null, { cause: err });
  }
  if (typeof body !== "object" || body === null || typeof body.success !== "boolean") {
    throw new ApiError(0, NETWORK_ERROR, `Unexpected response (${response.status})`, null);
  }

  if (!response.ok || !body.success) {
    throw new ApiError(
      response.status,
      body.error?.code ?? "internal_error",
      body.error?.message ?? response.statusText,
      body.error?.blocked_until ?? null,
    );
  }
  return { data: body.data as T, meta: body.meta };
}
