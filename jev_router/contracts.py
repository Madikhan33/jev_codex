"""Internal data contracts; routing results retain the public JSON field names."""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class Category(TypedDict):
    domain: str
    owner: str
    title: str
    question: str
    yes: str
    no: str
    positive_examples: list[str]
    negative_examples: list[str]
    profile_notes: str


class Profile(TypedDict):
    family: str
    model: str
    effort: str
    rank: int
    criterion: str


class Policy(TypedDict):
    yes_threshold: float
    no_threshold: float
    profile_threshold: float
    profile_margin: float
    top_k: int
    max_prompt_chars: int
    max_context_chars: int
    request_timeout_seconds: float
    jev_model: str


class Catalog(TypedDict):
    categories: dict[str, Category]
    profiles: dict[str, Profile]
    policy: Policy
    # Prompt objects vary by question; concrete wire types are validated by the SDK.
    routing: dict[str, Any]


class ChoiceDecision(TypedDict):
    value: str
    probability: float
    confidence: float
    accepted: bool


class CategoryScore(TypedDict):
    work_type: str
    domain: str
    probability: float


class WorkRoute(CategoryScore):
    profile: str | None
    profile_decision: ChoiceDecision


class OwnershipGroup(TypedDict):
    owner: str
    work_types: list[str]
    profile: str | None
    agent_type: str | None
    model: str | None
    effort: str | None


class Usage(TypedDict):
    input_tokens: int | None
    output_tokens: int | None
    classification_calls: NotRequired[int]


class RoutingResult(TypedDict):
    schema_version: int
    intent: ChoiceDecision
    coordination: ChoiceDecision
    routes: list[WorkRoute]
    groups: list[OwnershipGroup]
    top_candidates: list[CategoryScore]
    uncertain: list[CategoryScore]
    uncovered_probability: float
    has_uncovered_work: bool
    review_required: bool
    strategy: str
    capabilities_verified: bool
    usage: Usage
