import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { mockDb } from "../mocks/mockDb.ts";
import { renderApp } from "../test/renderApp.tsx";

const composer = () => screen.getByRole("textbox", { name: "Message" });

describe("ChatPage", () => {
  it("chat_route_without_id_shows_the_discovery_prompt", () => {
    renderApp("/chat");
    expect(screen.getByRole("heading", { level: 1, name: "Get ideas" })).toBeInTheDocument();
    expect(screen.getByText("Tell me roughly when, with whom and your budget")).toBeInTheDocument();
  });

  it("chat_route_without_id_creates_conversation_on_first_send_and_updates_url", async () => {
    const { user } = renderApp("/chat");
    await user.type(composer(), "Where should 4 friends go in December?{Enter}");
    await waitFor(() => expect(mockDb.conversations).toHaveLength(2));
    // The page now shows the saved conversation, which only happens at /chat/<id>
    expect(await screen.findByRole("heading", { level: 1, name: "Where should 4 friends go in December?" })).toBeInTheDocument();
    expect(screen.getAllByText("Where should 4 friends go in December?", { selector: "li" })).toHaveLength(1);
  });

  it("discovery_suggest_now_on_the_questionnaire_shows_three_suggestion_cards", async () => {
    const { user } = renderApp("/chat");
    await user.type(composer(), "Give me ideas for December{Enter}");
    await user.click(await screen.findByRole("button", { name: "Suggest now" }));
    expect(await screen.findAllByRole("button", { name: "Plan this trip" })).toHaveLength(3);
    expect(screen.getByRole("heading", { name: "Chiang Mai" })).toBeInTheDocument();
    expect(screen.getAllByText("Estimate").length).toBeGreaterThanOrEqual(3);
  });

  it("has_no_new_chat_button", async () => {
    renderApp(`/chat/${mockDb.conversations[0]?.id}`);
    await screen.findByText(/three places that fit a cool/);
    expect(screen.queryByRole("button", { name: "New chat" })).toBeNull();
  });

  it("get_ideas_link_empties_the_thread", async () => {
    const { user } = renderApp(`/chat/${mockDb.conversations[0]?.id}`);
    await screen.findByText(/three places that fit a cool/);
    await user.click(screen.getByRole("link", { name: "Get ideas" }));
    expect(screen.getByText("Tell me roughly when, with whom and your budget")).toBeInTheDocument();
    expect(screen.queryByText(/three places that fit a cool/)).toBeNull();
  });
});
