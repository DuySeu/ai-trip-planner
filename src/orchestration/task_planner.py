"""Decide what a chat turn runs: the agents the classifier may pick, its call, and the one task
taken from its decision."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agents.orchestrator_agent import OrchestratorAgent
from models.model_router import CallContext
from orchestration.routing_schema import AgentSpec, RoutingDecision
from orchestration.state_manager import ChatContext, ChatTurn, message_for_model

if TYPE_CHECKING:
    # Imported for annotations only: orchestrator imports this module
    from orchestration.orchestrator import ChatDeps

# The agents the classifier may route to, with the descriptions it sees
CATALOG: tuple[AgentSpec, ...] = (
    AgentSpec(
        name="advice",
        description="Answer a travel question from what is known: a question about the plan of "
        "the open trip, or general advice and tips (what to pack, which area to stay in, how to "
        "get around, is a month good for a place). Also questions asked while thinking about a "
        'trip, such as "I want 3 days in Hai Phong, which area is good?". No web search.',
    ),
    AgentSpec(
        name="web_lookup",
        description="A question that needs new, current facts from the web that general "
        'knowledge and the plan do not hold, such as "what festivals are on in Da Nang in '
        'July?" or visa rules this year. Not for hotels or flights (hotel_search and '
        "flight_search do those) and not for a question about the open plan. The step task is "
        "the web search query.",
    ),
    AgentSpec(
        name="discover",
        description="The visitor wants ideas for WHERE to go on a new trip, or says they want "
        'to travel but has no destination yet, such as "I want a beach trip" or "gợi ý chỗ đi '
        'chơi cuối tuần". Also "give me other ideas".',
    ),
    AgentSpec(
        name="hotel_search",
        description="Find hotels or places to stay in a named place, or what they cost per "
        'night, such as "4-star hotels in Hai Phong" or "khách sạn gần biển Đồ Sơn giá rẻ". '
        "The step task is a short web search query of keywords, not a sentence: the hotel or "
        'area name, the place, the stars or budget and the word price, such as "khách sạn Sun '
        'World Phú Quốc giá". No dates and no verb such as "find" or "tìm"; code adds the month.',
    ),
    AgentSpec(
        name="flight_search",
        description="Find flights, trains or buses between two places, or what a ticket costs, "
        'such as "vé máy bay Hà Nội đi Đà Nẵng" or "train from Hanoi to Hue". The step task '
        "is a short web search query of keywords, not a sentence: the origin, the destination, "
        'the mode and the word price, such as "vé máy bay Hà Nội Phú Quốc giá". No dates and no '
        'verb such as "find" or "tìm"; code adds the month.',
    ),
    AgentSpec(
        name="create_trip",
        description="Only when the visitor directly asks the app to make the day-by-day plan "
        'or itinerary of a new trip now, such as "make the plan for me" or "tạo plan trip cho '
        'tôi", or answers yes ("có", "ok", "yes") right after the assistant asked whether to '
        "make the plan. Asking a question while planning a trip is advice, not this. Not to "
        "change the open trip.",
    ),
    AgentSpec(
        name="edit_plan",
        description="Change the plan of the open trip: add, move, replace or remove things, "
        "or change its dates, number of travelers, origin or language.",
    ),
)
# The intent saved for each agent; an agent the catalog does not have is advice
AGENT_INTENT: Mapping[str, str] = {
    "advice": "advice",
    "web_lookup": "advice",
    "discover": "discover",
    "hotel_search": "booking_search",
    "flight_search": "booking_search",
    "create_trip": "create_trip",
    "edit_plan": "edit_plan",
}


# The one task a turn runs: the agent (always a key of AGENT_INTENT), what the classifier picked
# ("none" when it picked nothing) and the text the agent works on
@dataclass(frozen=True)
class Task:
    agent: str
    picked: str
    text: str


# Ask the classifier where the message goes, with the last messages as history
def classify(
    data: ChatContext, turn: ChatTurn, deps: ChatDeps, call_ctx: CallContext
) -> RoutingDecision:
    history = [{"role": m.role, "content": message_for_model(m)} for m in data.history]
    messages = [*history, {"role": "user", "content": turn.message.content}]
    return OrchestratorAgent(deps.router).route(messages, CATALOG, call_ctx)


# The task of a decision; the visitor's message when the step gives no task text
def plan_task(decision: RoutingDecision, message: str) -> Task:
    # ponytail: only the first step runs; a multi-step decision is cut to its first agent
    step = decision.steps[0] if decision.status == "routed" else None
    picked = step.agent if step is not None else "none"
    agent = picked if picked in AGENT_INTENT else "advice"
    text = step.task.strip() if step is not None and step.task.strip() else message
    return Task(agent, picked, text)
