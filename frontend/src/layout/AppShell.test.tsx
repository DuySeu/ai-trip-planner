import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SEED_CONVERSATION_ID } from "../mocks/fixtures.ts";
import { mockDb } from "../mocks/mockDb.ts";
import { renderApp } from "../test/renderApp.tsx";

describe("AppShell", () => {
  it("language_toggle_switches_nav_labels_to_vietnamese", async () => {
    const { user } = renderApp("/nowhere");
    await user.click(screen.getByRole("button", { name: "Settings" }));
    await user.click(screen.getByRole("button", { name: "Tiếng Việt" }));
    const nav = screen.getByRole("navigation", { name: "Chính" });
    expect(
      within(nav).getByRole("link", { name: "Chuyến đi của tôi" }),
    ).toBeInTheDocument();
    expect(localStorage.getItem("tripPlanner.lang")).toBe("vi");
  });

  it("sidebar_lists_conversations_with_links", async () => {
    renderApp("/");
    const list = screen.getByRole("region", { name: "Conversations" });
    expect(
      await within(list).findByRole("link", {
        name: /where should we go in december/i,
      }),
    ).toHaveAttribute("href", `/chat/${SEED_CONVERSATION_ID}`);
  });

  it("sidebar_conversation_menu_shows_update_time_as_hour_minute_day_month_year", async () => {
    const { user } = renderApp("/");
    const list = screen.getByRole("region", { name: "Conversations" });
    const link = await within(list).findByRole("link", {
      name: /where should we go in december/i,
    });
    expect(link).toHaveTextContent(/^Where should we go in December\?$/);
    await user.click(
      within(list).getByRole("button", {
        name: "Actions for Where should we go in December?",
      }),
    );
    expect(
      screen.getByText(/^\d{2}:\d{2} \d{2}\/\d{2}\/\d{4}$/),
    ).toBeInTheDocument();
  });

  it("sidebar_conversation_menu_renames_it_in_a_dialog", async () => {
    const { user } = renderApp("/");
    const list = screen.getByRole("region", { name: "Conversations" });
    await user.click(
      await within(list).findByRole("button", {
        name: "Actions for Where should we go in December?",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Rename" }));
    const dialog = screen.getByRole("dialog", { name: "Rename conversation" });
    const input = within(dialog).getByRole("textbox", {
      name: "Conversation name",
    });
    expect(input).toHaveValue("Where should we go in December?");
    await user.clear(input);
    expect(
      within(dialog).getByRole("button", { name: "Save name" }),
    ).toBeDisabled();
    await user.type(input, "Đà Lạt ideas{Enter}");
    expect(
      await within(list).findByRole("link", { name: /Đà Lạt ideas/ }),
    ).toBeInTheDocument();
    expect(mockDb.conversations[0]?.title).toBe("Đà Lạt ideas");
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Rename conversation" }),
      ).not.toBeInTheDocument(),
    );
  });

  it("sidebar_conversation_rename_cancel_keeps_old_title", async () => {
    const { user } = renderApp("/");
    const list = screen.getByRole("region", { name: "Conversations" });
    await user.click(
      await within(list).findByRole("button", {
        name: "Actions for Where should we go in December?",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Rename" }));
    const dialog = screen.getByRole("dialog", { name: "Rename conversation" });
    await user.type(
      within(dialog).getByRole("textbox", { name: "Conversation name" }),
      " changed",
    );
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(
      within(list).getByRole("link", {
        name: /where should we go in december\?/i,
      }),
    ).toBeInTheDocument();
    expect(mockDb.conversations[0]?.title).toBe(
      "Where should we go in December?",
    );
  });

  it("sidebar_conversation_delete_leaves_the_open_chat", async () => {
    const { user } = renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    const list = screen.getByRole("region", { name: "Conversations" });
    await user.click(
      await within(list).findByRole("button", {
        name: "Actions for Where should we go in December?",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(
      screen.getByRole("button", { name: "Delete conversation" }),
    );
    expect(
      await within(list).findByText(
        "No conversations yet. Ask for ideas when you are not sure where to go.",
      ),
    ).toBeInTheDocument();
    expect(mockDb.conversations).toHaveLength(0);
    expect(mockDb.messages).toHaveLength(0);
    expect(
      await screen.findByRole("heading", { level: 1, name: "Get ideas" }),
    ).toBeInTheDocument();
  });

  it("sidebar_main_action_opens_get_ideas", () => {
    renderApp("/");
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(
      within(nav).getByRole("link", { name: "Get ideas" }),
    ).toHaveAttribute("href", "/chat");
    expect(within(nav).queryByRole("link", { name: "New trip" })).toBeNull();
  });

  it("sidebar_footer_settings_menu_lists_dashboard_first_then_language_theme_and_switch_name", async () => {
    const { user } = renderApp("/");
    expect(screen.getByText("Using the name Minh")).toBeInTheDocument();
    const settings = screen.getByRole("button", { name: "Settings" });
    expect(settings).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: "Switch name" })).toBeNull();
    await user.click(settings);
    expect(settings).toHaveAttribute("aria-expanded", "true");
    const items = [
      screen.getByRole("link", { name: "Dashboard" }),
      ...["Tiếng Việt", "Dark", "Switch name"].map((name) =>
        screen.getByRole("button", { name }),
      ),
    ];
    // Dashboard comes first
    expect(
      (items[0] as HTMLElement).compareDocumentPosition(
        items[1] as HTMLElement,
      ) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("button", { name: "Switch name" })).toBeNull();
  });

  it("theme_toggle_adds_dark_class_to_html", async () => {
    const { user } = renderApp("/nowhere");
    await user.click(screen.getByRole("button", { name: "Settings" }));
    await user.click(screen.getByRole("button", { name: "Dark" }));
    expect(document.documentElement).toHaveClass("dark");
    expect(localStorage.getItem("tripPlanner.theme")).toBe("dark");
    // The menu stays open and now offers the way back
    expect(screen.getByRole("button", { name: "Light" })).toBeInTheDocument();
  });

  it("switch_name_clears_the_session_and_opens_start", async () => {
    const { user } = renderApp("/nowhere");
    await user.click(screen.getByRole("button", { name: "Settings" }));
    await user.click(screen.getByRole("button", { name: "Switch name" }));
    expect(
      await screen.findByRole("heading", { name: /what should we call you/i }),
    ).toBeInTheDocument();
    expect(localStorage.getItem("tripPlanner.session")).toBeNull();
  });
});
