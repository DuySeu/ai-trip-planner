import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "../mocks/server.ts";
import { ApiError, apiRequest, apiUrl } from "./client.ts";

describe("apiRequest", () => {
  it("api_request_unwraps_data_and_meta", async () => {
    const meta = { total: 1, limit: 50, offset: 0 };
    server.use(http.get(apiUrl("/things"), () => HttpResponse.json({ success: true, data: [1], error: null, meta })));
    await expect(apiRequest<number[]>("/things")).resolves.toEqual({ data: [1], meta });
  });

  it("api_request_throws_api_error_with_envelope_code", async () => {
    server.use(
      http.post(apiUrl("/trips"), () =>
        HttpResponse.json(
          { success: false, data: null, error: { code: "quota_exhausted", message: "x" }, meta: null },
          { status: 429 },
        ),
      ),
    );
    const request = apiRequest("/trips", { method: "POST", body: "{}" });
    await expect(request).rejects.toBeInstanceOf(ApiError);
    await expect(request).rejects.toMatchObject({ status: 429, code: "quota_exhausted" });
  });

  it("api_request_maps_html_502_to_network_error", async () => {
    server.use(http.get(apiUrl("/users/1"), () => HttpResponse.html("<h1>Bad gateway</h1>", { status: 502 })));
    await expect(apiRequest("/users/1")).rejects.toMatchObject({ status: 0, code: "network_error" });
  });

  it("api_request_maps_a_failed_fetch_to_network_error", async () => {
    server.use(http.get(apiUrl("/users/1"), () => HttpResponse.error()));
    await expect(apiRequest("/users/1")).rejects.toMatchObject({ status: 0, code: "network_error" });
  });

  it("api_request_resolves_null_on_204", async () => {
    server.use(http.delete(apiUrl("/trips/1"), () => new HttpResponse(null, { status: 204 })));
    await expect(apiRequest<null>("/trips/1", { method: "DELETE" })).resolves.toEqual({ data: null, meta: null });
  });
});
