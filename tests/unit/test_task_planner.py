from __future__ import annotations

from typing import Any, Literal

from orchestration.routing_schema import RoutingDecision, RoutingMeta, RoutingStep
from orchestration.task_planner import Task, plan_task

MESSAGE = "Tìm khách sạn ở Đà Nẵng"
META = RoutingMeta(model_id="m", attempts=1, input_tokens=0, output_tokens=0, error=None)


def decision(status: Literal["routed", "fallback"], steps: list[Any]) -> RoutingDecision:
    return RoutingDecision(
        status=status,
        architecture="router" if len(steps) == 1 else ("sequential" if steps else None),
        steps=steps,
        aggregation=None,
        clarification=None,
        reasoning="r",
        meta=META,
    )


def step(agent: str, task: str = "hotels in Da Nang") -> RoutingStep:
    return RoutingStep(id="s1", agent=agent, task=task)


def test_routed_step_gives_its_agent_and_task():
    got = plan_task(decision("routed", [step("hotel_search")]), MESSAGE)
    assert got == Task(agent="hotel_search", picked="hotel_search", text="hotels in Da Nang")


def test_agent_not_in_catalog_falls_back_to_advice():
    got = plan_task(decision("routed", [step("weather")]), MESSAGE)
    assert got == Task(agent="advice", picked="weather", text="hotels in Da Nang")


def test_fallback_without_steps_runs_advice_on_the_message():
    got = plan_task(decision("fallback", []), MESSAGE)
    assert got == Task(agent="advice", picked="none", text=MESSAGE)


def test_multi_step_decision_runs_only_the_first_step():
    steps = [step("web_lookup", "find events"), step("edit_plan", "add them")]
    got = plan_task(decision("routed", steps), MESSAGE)
    assert got == Task(agent="web_lookup", picked="web_lookup", text="find events")


def test_blank_task_uses_the_message():
    blank = RoutingStep.model_construct(id="s1", agent="advice", task="   ")
    got = plan_task(decision("routed", [blank]), MESSAGE)
    assert got == Task(agent="advice", picked="advice", text=MESSAGE)
