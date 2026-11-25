import { delay, HttpResponse, http } from "msw";
import { IP_LOCATION_URL } from "../api/location.ts";
import { server } from "../mocks/server.ts";

// A position in Hồ Chí Minh City, as the IP lookup reports it
const HCMC = { success: true, latitude: 10.776889, longitude: 106.700806 };

// Make the IP lookup answer with the HCMC position, or fail; delayMs stands for a slow lookup.
// Without this the default mock handler fails the lookup, as a private test IP would. Returns
// how many lookups were made so far.
export function fakeIpLocation(answer: "allow" | "deny", delayMs = 0): () => number {
  let calls = 0;
  server.use(
    http.get(IP_LOCATION_URL, async () => {
      calls += 1;
      if (delayMs > 0) await delay(delayMs);
      return answer === "allow" ? HttpResponse.json(HCMC) : HttpResponse.json({ success: false, message: "Reserved range" });
    }),
  );
  return () => calls;
}
