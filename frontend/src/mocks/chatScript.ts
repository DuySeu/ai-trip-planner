import {
  ACTIVE_STATUSES,
  type ChatEvent,
  type Conversation,
  type MessageIntent,
  type RequestDraft,
  type Trip,
} from "../api/api.types.ts";
import { addDays, todayInVietnam } from "../format/dates.ts";
import { HOTEL_CARDS, SUGGESTION_CARDS } from "./fixtures.ts";
import { mockDb } from "./mockDb.ts";

const CREATE_TRIP = /plan trip|tạo plan/i;
const DISCOVER = /where|ideas|gợi ý|đi đâu/i;
const HOTEL = /hotel|khách sạn/i;
const EDIT = /change|switch|cheaper|đổi|thay/i;
const REPLAN = /date|ngày|people|người/i;
const VIETNAMESE = /[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]/i;

interface Input {
  content: string;
  trip: Trip | null;
  conversation: Conversation;
}

interface Reply {
  events: ChatEvent[];
  updatedTrip: Trip | null;
  intent: MessageIntent;
}

// The canned reply to a chat message; the first matching rule wins
export function scriptReply({ content, trip, conversation }: Input): Reply {
  const isVi = VIETNAMESE.test(content);
  const say = (en: string, vi: string): ChatEvent[] =>
    (isVi ? vi : en).split(/(?<= )/).map((text) => ({ type: "token", data: { text } }));
  const done: ChatEvent = { type: "done", data: {} };

  // A trip form prefilled from the chat when no trip is open; the handler saves the message
  if (trip === null && CREATE_TRIP.test(content)) {
    const draft: RequestDraft = {
      destination: { name: "Hải Phòng", country_code: "VN", lat: 20.86, lon: 106.68 },
      origin: "Hà Nội",
      start_date: addDays(todayInVietnam(mockDb.now()), 30),
      length_days: 3,
      travelers: 2,
      travel_styles: ["food"],
      budget_amount: "3000000",
      budget_scope: "per_person",
      ...conversation.request_draft,
    };
    return {
      intent: "trip_form",
      updatedTrip: null,
      events: [{ type: "trip_form", data: { message_id: crypto.randomUUID(), draft } }, done],
    };
  }

  // Hotel options from booking sites; the handler saves the cards with the reply
  if (HOTEL.test(content) && !EDIT.test(content)) {
    return {
      intent: "hotel_options",
      updatedTrip: null,
      events: [
        ...say(
          "Prices are a guide from booking sites and change with your dates. Check the hotel's page before you book.",
          "Giá tham khảo từ các trang đặt phòng và thay đổi theo ngày. Bạn xem trang của khách sạn trước khi đặt nhé.",
        ),
        { type: "hotels", data: { cards: HOTEL_CARDS } },
        done,
      ],
    };
  }

  // Destination ideas when no trip is open
  if (trip === null && DISCOVER.test(content)) {
    return {
      intent: "suggest",
      updatedTrip: null,
      events: [
        ...say(
          "Here are three places that fit what you told me. Costs are rough estimates per person.",
          "Đây là ba nơi hợp với những gì bạn kể. Chi phí là ước tính cho mỗi người.",
        ),
        { type: "suggestions", data: { cards: SUGGESTION_CARDS } },
        done,
      ],
    };
  }

  // Edits wait while a re-plan runs
  const isActive = trip !== null && (ACTIVE_STATUSES as readonly string[]).includes(trip.status);
  if (trip?.plan && isActive && EDIT.test(content)) {
    return {
      intent: "plan_editor",
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
        intent: "plan_editor",
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
      intent: "plan_editor",
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
    intent: trip ? "plan_answer" : "travel_advice",
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
