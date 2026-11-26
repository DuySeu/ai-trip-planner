import { describe, expect, it } from "vitest";
import { PLACES } from "../mocks/fixtures.ts";
import { fromDraft, type TripFormValues, toCreateTripBody, toDraft, validateTripForm } from "./validateTripForm.ts";

const TODAY = "2026-11-17";
const valid: TripFormValues = {
  destination: PLACES[3] ?? null,
  origin: " Hà Nội ",
  start_date: "2026-12-01",
  end_date: "2026-12-04",
  travelers: 2,
  travel_styles: ["nature"],
  budget_amount: "5000000",
  budget_scope: "per_person",
  budget_auto: false,
  notes: "  ",
};

describe("validateTripForm", () => {
  it("accepts_valid_values", () => {
    expect(validateTripForm(valid, TODAY)).toEqual({});
  });

  it("rejects_start_date_before_today_in_vietnam", () => {
    expect(validateTripForm({ ...valid, start_date: "2026-11-16" }, TODAY).start_date).toBe("form.errors.startInPast");
  });

  it("accepts_30_days_and_rejects_31", () => {
    expect(validateTripForm({ ...valid, end_date: "2026-12-30" }, TODAY).end_date).toBeUndefined();
    expect(validateTripForm({ ...valid, end_date: "2026-12-31" }, TODAY).end_date).toBe("form.errors.tooLong");
  });

  it("rejects_end_before_start", () => {
    expect(validateTripForm({ ...valid, end_date: "2026-11-30" }, TODAY).end_date).toBe("form.errors.endBeforeStart");
  });

  it("requires_a_destination_from_search_and_one_style", () => {
    const errors = validateTripForm({ ...valid, destination: null, travel_styles: [] }, TODAY);
    expect(errors).toMatchObject({ destination: "form.errors.destination", travel_styles: "form.errors.styles" });
  });

  it("rejects_zero_budget_and_51_travelers", () => {
    const errors = validateTripForm({ ...valid, budget_amount: "0", travelers: 51 }, TODAY);
    expect(errors).toMatchObject({ budget_amount: "form.errors.budget", travelers: "form.errors.travelers" });
  });

  it("ai_suggested_budget_needs_no_amount_and_sends_null_budget", () => {
    const values = { ...valid, budget_amount: "", budget_auto: true };
    expect(validateTripForm(values, TODAY)).toEqual({});
    const body = toCreateTripBody(values, "u1", "en");
    expect([body.budget_amount, body.budget_scope]).toEqual([null, null]);
    expect(toDraft(values)).not.toHaveProperty("budget_scope");
  });

  it("to_create_trip_body_sends_null_notes_and_no_removed_fields", () => {
    const body = toCreateTripBody(valid, "u1", "vi");
    expect(body).toMatchObject({ notes: null, origin: "Hà Nội", language: "vi" });
    expect(body).not.toHaveProperty("group_type");
    expect(body).not.toHaveProperty("transport_modes");
    expect(body).not.toHaveProperty("conversation_id");
    expect(body.destination).toEqual({ name: "Đà Lạt", country_code: "VN", lat: 11.9404, lon: 108.4583 });
  });

  it("to_draft_leaves_out_blank_notes_and_the_removed_fields", () => {
    const draft = toDraft(valid);
    expect(draft).toMatchObject({ origin: "Hà Nội", travelers: 2, travel_styles: ["nature"] });
    expect(draft).not.toHaveProperty("notes");
    expect(draft).not.toHaveProperty("group_type");
  });

  it("from_draft_fills_end_date_from_length_days", () => {
    const values = fromDraft({ start_date: "2026-12-10", length_days: 4, travelers: 4 }, null);
    expect(values).toMatchObject({ start_date: "2026-12-10", end_date: "2026-12-13", travelers: 4 });
  });

  it("from_draft_with_only_a_month_leaves_dates_empty", () => {
    expect(fromDraft({ month: "2026-12" }, null)).toMatchObject({ start_date: "", end_date: "" });
  });
});
