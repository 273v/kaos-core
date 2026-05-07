from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from kaos_core.exceptions import URLElicitationRequiredError
from kaos_core.types.content import KaosModel
from kaos_core.types.enums import ElicitationMode

SENSITIVE_MARKERS = {"password", "secret", "token", "credential", "api_key"}


class ElicitationRequest(KaosModel):
    elicitation_id: str
    message: str
    mode: ElicitationMode = ElicitationMode.FORM
    requested_schema: dict[str, object] | None = None
    url: str | None = None
    timeout: float | None = Field(default=None, gt=0.0)

    @model_validator(mode="after")
    def validate_mode(self) -> ElicitationRequest:
        if self.mode is ElicitationMode.FORM and self.url is not None:
            msg = "Form mode cannot include a URL"
            raise ValueError(msg)
        if self.mode is ElicitationMode.URL and self.url is None:
            msg = "URL mode requires a URL"
            raise ValueError(msg)
        if self.mode is ElicitationMode.FORM and self.requested_schema is not None:
            properties = self.requested_schema.get("properties", {})
            if any(marker in str(properties).lower() for marker in SENSITIVE_MARKERS):
                msg = "Sensitive schemas must use URL elicitation"
                raise URLElicitationRequiredError(msg)
        return self


class ElicitationResponse(KaosModel):
    elicitation_id: str
    action: Literal["accept", "decline", "cancel"]
    content: dict[str, object] | None = None


class ElicitationCompletionNotification(KaosModel):
    elicitation_id: str
    success: bool
    error: str | None = None
