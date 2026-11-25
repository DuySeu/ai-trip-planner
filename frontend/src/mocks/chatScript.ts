import {
  ACTIVE_STATUSES,
  type BookingKind,
  type ChatEvent,
  type Conversation,
  type FlightDates,
  type HotelDates,
  type MessageIntent,
  type MessageMetadata,
  type RequestDraft,
  type Trip,
} from "../api/api.types.ts";
import { addDays, todayInVietnam } from "../format/dates.ts";
import { FLIGHT_CARDS, HOTEL_CARDS, SUGGESTION_CARDS } from "./fixtures.ts";
import { mockDb } from "./mockDb.ts";

const CREATE_TRIP = /plan trip|plan a|tạo plan|lên lịch trình/i;
const DISCOVER = /where|ideas|gợi ý|đi đâu/i;
const HOTEL = /hotel|khách sạn/i;
const FLIGHT = /flight|máy bay/i;
const EDIT = /change|switch|cheaper|đổi|thay/i;
const REPLAN = /date|ngày|people|người/i;
const VIETNAMESE = /[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]/i;

// A message sent from a card skips the rules: suggest from a questionnaire, or search with the picked dates
export type ScriptFollowUp = { kind: "discover" } | { kind: BookingKind; query: string; dates: HotelDates | FlightDates };

interface Input {
  content: string;
  trip: Trip | null;
  conversation: Conversation;
  followUp?: ScriptFollowUp | null;
  // The visitor's current city, or Hà Nội; tickets start there when nothing else names an origin
  defaultOrigin: string;
}

interface Reply {
  events: ChatEvent[];
  updatedTrip: Trip | null;
  intent: MessageIntent;
}

// The canned reply to a chat message; the first matching rule wins
export function scriptReply({ content, trip, conversation, followUp = null, defaultOrigin }: Input): Reply {
  const isVi = VIETNAMESE.test(content);
  const say = (en: string, vi: string): ChatEvent[] =>
    (isVi ? vi : en).split(/(?<= )/).map((text) => ({ type: "token", data: { text } }));
  const done: ChatEvent = { type: "done", data: {} };
  const meta = (metadata: MessageMetadata, messageId: string | null = null): ChatEvent => ({
    type: "metadata",
    data: { message_id: messageId, metadata },
  });
  const suggestions: Reply = {
    intent: "discover",
    updatedTrip: null,
    events: [
      ...say(
        "Here are three places that fit what you told me. Costs are rough estimates per person.",
        "Đây là ba nơi hợp với những gì bạn kể. Chi phí là ước tính cho mỗi người.",
      ),
      meta({ kind: "suggestions", cards: SUGGESTION_CARDS }),
      done,
    ],
  };
  const results = (kind: BookingKind, query: string, dates: HotelDates | FlightDates): Reply => ({
    intent: "booking_search",
    updatedTrip: null,
    events: [
      ...say(
        "Prices are a guide from booking sites and change with your dates. Check the page before you book.",
        "Giá tham khảo từ các trang đặt chỗ và thay đổi theo ngày. Bạn xem trang gốc trước khi đặt nhé.",
      ),
      meta(
        kind === "hotel"
          ? { kind, status: "results", query, dates: dates as HotelDates, cards: HOTEL_CARDS }
          : { kind, status: "results", query, dates: dates as FlightDates, cards: FLIGHT_CARDS },
      ),
      done,
    ],
  });

  if (followUp?.kind === "discover") return suggestions;
  if (followUp) return results(followUp.kind, followUp.query, followUp.dates);

  // A trip form prefilled from the chat when no trip is open; the handler saves the message
  if (trip === null && CREATE_TRIP.test(content)) {
    const draft: RequestDraft = {
      destination: { name: "Hải Phòng", country_code: "VN", lat: 20.86, lon: 106.68 },
      origin: defaultOrigin,
      start_date: addDays(todayInVietnam(mockDb.now()), 30),
      length_days: 3,
      travelers: 2,
      travel_styles: ["food"],
      budget_amount: "3000000",
      budget_scope: "per_person",
      ...conversation.request_draft,
    };
    return {
      intent: "create_trip",
      updatedTrip: null,
      events: [
        { type: "metadata", data: { message_id: crypto.randomUUID(), metadata: { status: "open", draft, trip_id: null } } },
        done,
      ],
    };
  }

  // Hotels or tickets: search with the trip's or the draft's dates, else a card that asks for them
  const kind: BookingKind | null = HOTEL.test(content) ? "hotel" : FLIGHT.test(content) ? "flight" : null;
  if (kind && !EDIT.test(content)) {
    const draft = conversation.request_draft ?? {};
    const start = trip?.start_date ?? draft.start_date ?? null;
    const end = trip?.end_date ?? draft.end_date ?? null;
    if (kind === "hotel" && start && end) return results(kind, content, { check_in: start, check_out: end });
    if (kind === "flight" && start) return results(kind, content, { depart: start, return: end });
    return {
      intent: "booking_search",
      updatedTrip: null,
      events: [
        ...(kind === "hotel"
          ? say("Which dates do you want to stay?", "Bạn định nhận phòng và trả phòng ngày nào?")
          : say("When do you want to travel?", "Bạn định đi ngày nào?")),
        meta({ kind, status: "need_dates", query: content }, crypto.randomUUID()),
        done,
      ],
    };
  }

  // Destination ideas when no trip is open: a questionnaire card while the draft misses an answer
  if (trip === null && DISCOVER.test(content)) {
    const missing = firstMissingStep(conversation.request_draft ?? {});
    const open = mockDb.messages.find(
      (m) => m.conversation_id === conversation.id && m.metadata && "kind" in m.metadata && m.metadata.kind === "questionnaire" && m.metadata.status === "open",
    );
    if (open?.metadata && "kind" in open.metadata && open.metadata.kind === "questionnaire") {
      open.metadata = { ...open.metadata, status: "done" };
    } else if (missing !== null) {
      const answers = conversation.request_draft ?? {};
      return {
        intent: "discover",
        updatedTrip: null,
        events: [meta({ kind: "questionnaire", status: "open", step: missing - 1, answers, choices: {} }, crypto.randomUUID()), done],
      };
    }
    return suggestions;
  }

  // Edits wait while a re-plan runs
  const isActive = trip !== null && (ACTIVE_STATUSES as readonly string[]).includes(trip.status);
  if (trip?.plan && isActive && EDIT.test(content)) {
    return {
      intent: "edit_plan",
      updatedTrip: null,
      events: [{ type: "error", data: { code: "conflict", message: "The plan is being regenerated." } }, done],
    };
  }

  // Swap the chosen outbound option and the day-1 item linked to it
  if (trip?.plan && EDIT.test(content)) {
    const outbound = trip.plan.transport_options.filter((o) => o.leg === "outbound");
    const current = outbound.find((o) => o.chosen);
    const next = outbound.find((o) => !o.chosen);
    if (current && next) {
      const revision = trip.plan_revision + 1;
      const plan = {
        ...trip.plan,
        transport_options: trip.plan.transport_options.map((o) => (o.leg === "outbound" ? { ...o, chosen: o.id === next.id } : o)),
        days: trip.plan.days.map((day) => ({
          ...day,
          items: day.items.map((item) =>
            item.option_id === current.id
              ? {
                  ...item,
                  title: next.summary,
                  transport_mode: next.mode,
                  price_per_person: next.price_per_person,
                  price_currency: next.price_currency,
                  price_basis: next.price_basis,
                  source_id: next.source_id,
                  option_id: next.id,
                }
              : item,
          ),
        })),
      };
      return {
        intent: "edit_plan",
        updatedTrip: { ...trip, plan, plan_revision: revision },
        events: [
          { type: "plan", data: { plan_revision: revision } },
          ...say(`Done. Changed: the way there is now ${next.summary}.`, `Xong. Đã đổi: chiều đi giờ là ${next.summary}.`),
          done,
        ],
      };
    }
  }

  // Dates or group size: re-plan in the background, the current plan stays
  if (trip?.plan && REPLAN.test(content)) {
    return {
      intent: "edit_plan",
      updatedTrip: { ...trip, status: "researching", stage: "researching" },
      events: [
        ...say(
          "Re-planning started. The current plan stays here until the new one is ready.",
          "Đã bắt đầu lập lại kế hoạch. Kế hoạch hiện tại vẫn ở đây cho tới khi bản mới xong.",
        ),
        done,
      ],
    };
  }

  // Anything else: a short answer in the language of the message
  return {
    intent: "advice",
    updatedTrip: null,
    events: [
      ...say(
        "Good question. The weather looks dry for most of the trip, so outdoor plans should hold. Bring a light jacket for the evenings.",
        "Câu hỏi hay. Thời tiết khá khô trong phần lớn chuyến đi nên các hoạt động ngoài trời vẫn ổn. Nhớ mang áo khoác mỏng cho buổi tối.",
      ),
      done,
    ],
  };
}

// The first of the six questions (1-6) the draft does not answer; null when it answers all
function firstMissingStep(d: RequestDraft): number | null {
  const answered = [
    Boolean(d.travel_styles?.length),
    d.travelers != null,
    d.budget_amount != null,
    Boolean(d.origin),
    Boolean(d.month || d.start_date),
    Boolean(d.length_days || (d.start_date && d.end_date)),
  ];
  const index = answered.indexOf(false);
  return index === -1 ? null : index + 1;
}
