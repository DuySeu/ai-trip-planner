import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, beforeEach } from "vitest";
import { mockDb } from "../mocks/mockDb.ts";
import { server } from "../mocks/server.ts";

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
beforeEach(() => {
  mockDb.reset();
  mockDb.tokenGapMs = 0;
  localStorage.clear();
  document.documentElement.className = "";
});
afterEach(() => {
  cleanup();
  server.resetHandlers();
});
afterAll(() => server.close());

// jsdom has no modal dialog support; give it the open/close behaviour the app relies on
if (!HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    if (!this.hasAttribute("open")) return;
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
}
