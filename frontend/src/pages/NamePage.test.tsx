import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { server } from "../mocks/server.ts";
import { renderApp } from "../test/renderApp.tsx";

describe("NamePage", () => {
  it("redirects_to_start_without_a_session", async () => {
    renderApp("/", { session: null });
    expect(await screen.findByRole("heading", { name: /what should we call you/i })).toBeInTheDocument();
  });

  it("claiming_a_name_saves_the_session_and_opens_home", async () => {
    const { user } = renderApp("/start", { session: null });
    await user.type(screen.getByLabelText("Your name"), "Lan");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("heading", { name: "My trips" })).toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem("tripPlanner.session") ?? "{}")).toMatchObject({ name: "Lan" });
  });

  it("blank_name_shows_inline_error_without_a_request", async () => {
    let requests = 0;
    server.events.on("request:start", () => {
      requests += 1;
    });
    const { user } = renderApp("/start", { session: null });
    await user.type(screen.getByLabelText("Your name"), "   ");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a name.");
    expect(requests).toBe(0);
    server.events.removeAllListeners();
  });

  it("name_over_50_chars_is_blocked", async () => {
    const { user } = renderApp("/start", { session: null });
    await user.type(screen.getByLabelText("Your name"), "a".repeat(51));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Use 50 characters or fewer.");
    expect(localStorage.getItem("tripPlanner.session")).toBeNull();
  });

  it("unknown_path_shows_not_found_with_link_home", async () => {
    renderApp("/nowhere");
    expect(screen.getByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to my trips" })).toHaveAttribute("href", "/");
  });
});
