"""Small TypeSafe Python SDK adapter. No network activity during import."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from typesafe_sdk import Choice, Noul


class JevTransport:
    """Reuse one HTTP client for both stages, with bounded requests and no retries."""

    def __init__(self, api_key: str, *, model: str, timeout: float) -> None:
        # SDK debug logging includes unredacted request bodies. Hook processes must
        # not leak submitted prompts to stderr, even if the parent enables debugging.
        os.environ["TYPESAFE_LOG_LEVEL"] = "off"
        from typesafe_sdk import Choice, Noul, NoulCriteria, RetryPolicy, TypeSafeClient

        logging.getLogger("typesafe_sdk").disabled = True
        self.Choice = Choice
        self.Noul = Noul
        self.NoulCriteria = NoulCriteria
        self.model = model
        self.client = TypeSafeClient(
            api_key=api_key, retry=RetryPolicy(max_retries=0, timeout=timeout)
        )

    def __enter__(self) -> JevTransport:
        self.client.__enter__()
        return self

    def __exit__(self, *args: Any) -> Any:
        return self.client.__exit__(*args)

    def __call__(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
        typed_questions: dict[str, Noul | Choice] = {}
        for key, definition in questions.items():
            if definition["type"] == "noul":
                typed_questions[key] = self.Noul(
                    instructions=definition["instructions"],
                    criteria=self.NoulCriteria(**definition["criteria"]),
                )
            elif definition["type"] == "choice":
                typed_questions[key] = self.Choice(
                    instructions=definition["instructions"],
                    criteria=definition["criteria"],
                )
            else:
                raise ValueError("Unknown question primitive")
        response = self.client.system_one(model=self.model, state=state, questions=typed_questions)
        return response.model_dump(mode="json")
