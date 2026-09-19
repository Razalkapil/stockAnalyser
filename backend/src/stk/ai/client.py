"""The LLM boundary: a tiny protocol, the real Anthropic client, and structured-JSON calling.

``LlmClient`` is the ONLY thing the rest of the code sees, so tests substitute a fake and no test
ever touches the network or spends money. ``AnthropicClient`` is the single place that knows the
SDK.

STRUCTURED OUTPUT is prompt-driven and validated on OUR side: the model is told to reply with one
JSON object, the reply has any code fences stripped, and it is parsed with pydantic. On failure
there is exactly ONE retry, with the validation errors appended so the model can correct itself.
After that the run is recorded ``invalid_output`` -- it never raises into the pipeline.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from pydantic import BaseModel, ValidationError

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


class LlmError(RuntimeError):
    """The call failed (network, auth, rate limit, refusal). Carries a message safe to store."""


@dataclass
class LlmReply:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str | None = None


class LlmClient(Protocol):
    def complete(self, *, system: str, messages: list[dict[str, str]], max_tokens: int
                 ) -> LlmReply: ...


def strip_fences(text: str) -> str:
    """Remove a Markdown code fence around a JSON reply, if the model added one."""
    m = _FENCE.match(text)
    return m.group(1) if m else text.strip()


@dataclass
class StructuredResult:
    value: BaseModel | None
    attempts: int
    input_tokens: int
    output_tokens: int
    model: str
    raw_text: str
    error: str | None = None
    errors_seen: list[str] = field(default_factory=list)


def _errors(exc: ValidationError | ValueError) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
    return str(exc)


def call_structured[M: BaseModel](
    client: LlmClient,
    *,
    system: str,
    user: str,
    schema: type[M],
    max_tokens: int,
    semantic_check: object = None,
) -> StructuredResult:
    """Ask for JSON matching ``schema``; validate; retry ONCE with the errors; never raise.

    ``semantic_check(value) -> list[str]`` (optional) returns problems a schema cannot express
    (e.g. a pick id that was never in the input). Its problems drive the retry exactly like a
    parse error does.
    """
    messages = [{"role": "user", "content": user}]
    total_in = total_out = 0
    last_text, last_model = "", ""
    seen: list[str] = []

    for attempt in (1, 2):
        try:
            reply = client.complete(system=system, messages=messages, max_tokens=max_tokens)
        except LlmError as exc:
            return StructuredResult(None, attempt, total_in, total_out, last_model, last_text,
                                    error=f"call failed: {exc}", errors_seen=seen)
        total_in += reply.input_tokens
        total_out += reply.output_tokens
        last_text, last_model = reply.text, reply.model

        if reply.stop_reason == "refusal":
            return StructuredResult(None, attempt, total_in, total_out, last_model, last_text,
                                    error="the model declined to answer (refusal)",
                                    errors_seen=seen)
        if reply.stop_reason == "max_tokens":
            problems = "the reply was cut off at max_tokens"
        else:
            try:
                value = schema.model_validate(json.loads(strip_fences(reply.text)))
                problems = ""
                if callable(semantic_check):
                    bad = semantic_check(value)
                    problems = "; ".join(bad)
                if not problems:
                    return StructuredResult(value, attempt, total_in, total_out, last_model,
                                            last_text, errors_seen=seen)
            except (ValidationError, ValueError) as exc:
                problems = _errors(exc)

        seen.append(problems)
        messages = [
            *messages,
            {"role": "assistant", "content": reply.text},
            {"role": "user", "content": (
                "That reply was rejected: " + problems + ". Reply again with ONE corrected JSON "
                "object only -- no prose, no code fences.")},
        ]

    return StructuredResult(None, 2, total_in, total_out, last_model, last_text,
                            error="invalid output after one retry: " + seen[-1],
                            errors_seen=seen)


class AnthropicClient:
    """The real client. Credentials come from the environment (ANTHROPIC_API_KEY, or an
    `ant auth login` profile) -- never from config or the repo."""

    def __init__(self, *, model: str, effort: str, timeout_s: float) -> None:
        import anthropic  # noqa: PLC0415 -- only this class needs the SDK

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(timeout=timeout_s)
        self._model = model
        self._effort = effort

    def complete(self, *, system: str, messages: list[dict[str, str]], max_tokens: int
                 ) -> LlmReply:
        a = self._anthropic
        try:
            # Streaming: a long, high-max_tokens request must not hit an HTTP timeout.
            with self._client.messages.stream(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                messages=cast(Any, messages),
                thinking={"type": "adaptive"},
                output_config=cast(Any, {"effort": self._effort}),
            ) as stream:
                final = stream.get_final_message()
        except a.AuthenticationError as exc:
            raise LlmError("authentication failed -- set ANTHROPIC_API_KEY or run `ant auth "
                           "login`") from exc
        except a.RateLimitError as exc:
            raise LlmError("rate limited by the API") from exc
        except a.BadRequestError as exc:
            raise LlmError(f"the API rejected the request: {exc.message}") from exc
        except a.APIStatusError as exc:
            raise LlmError(f"API error {exc.status_code}: {exc.message}") from exc
        except a.APIConnectionError as exc:
            raise LlmError("could not reach the API (network)") from exc

        text = "".join(b.text for b in final.content if b.type == "text")
        return LlmReply(text=text, model=final.model, input_tokens=final.usage.input_tokens,
                        output_tokens=final.usage.output_tokens, stop_reason=final.stop_reason)
