"""Configuration and request model tests."""

import pytest
from pydantic import ValidationError

from models import InputRequest, ModelConfig, RuntimeConfig, SearchConfig


def test_input_request_strips_prompt() -> None:
    request = InputRequest(prompt="  Agent workflow  ")

    assert request.prompt == "Agent workflow"


@pytest.mark.parametrize(
    ("model", "field", "expected"),
    [
        (ModelConfig(model="test", api_key="key", max_retries=3), "max_retries", 3),
        (
            SearchConfig(api_key="key", max_content_chars=1500),
            "max_content_chars",
            1500,
        ),
        (RuntimeConfig(max_slide_revisions=3), "max_slide_revisions", 3),
    ],
)
def test_quality_configuration_fields(
    model: object,
    field: str,
    expected: int,
) -> None:
    assert getattr(model, field) == expected


def test_rejects_invalid_revision_limit() -> None:
    with pytest.raises(ValidationError):
        RuntimeConfig(max_slide_revisions=0)
