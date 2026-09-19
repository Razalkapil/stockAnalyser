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
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

import httpx
from pydantic import BaseModel, ValidationError

from stk.config.ai import AiConfig

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


def prompt_json(payload: object) -> str:
    """The prompt payload as COMPACT, deterministic JSON. Indentation is whitespace the model
    does not need and a token-limited provider does count (about a third of a typical prompt)."""
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str)


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
    #: Only set when ``keep_on_semantic_failure`` returned a parsed value that still has
    #: semantic problems -- the caller must then handle those items individually.
    semantic_problems: list[str] = field(default_factory=list)


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
    keep_on_semantic_failure: bool = False,
    max_input_chars: int | None = None,
) -> StructuredResult:
    """Ask for JSON matching ``schema``; validate; retry ONCE with the errors; never raise.

    ``semantic_check(value) -> list[str]`` (optional) returns problems a schema cannot express
    (e.g. a pick id that was never in the input). Its problems drive the retry exactly like a
    parse error does.

    ``max_input_chars``: if the prompt is longer, nothing is sent and the result is a
    ``call failed`` error (so it is recorded as a failed run, not as invalid model output).

    ``keep_on_semantic_failure``: if the reply PARSES but is still semantically imperfect after
    the retry, return it (with ``semantic_problems``) instead of discarding it -- for replies made
    of independent items (proposals), where throwing away the good ones with the bad is a loss.
    A reply that does not parse is never kept.
    """
    if max_input_chars is not None and len(system) + len(user) > max_input_chars:
        # Refuse locally rather than spend a request on a guaranteed provider-side rejection.
        return StructuredResult(
            None, 0, 0, 0, "", "",
            error=(f"call failed: the prompt is {len(system) + len(user):,} characters, over "
                   f"the configured max_input_chars={max_input_chars:,}"))
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
                bad = semantic_check(value) if callable(semantic_check) else []
                problems = "; ".join(bad)
                if not bad:
                    return StructuredResult(value, attempt, total_in, total_out, last_model,
                                            last_text, errors_seen=seen)
                if attempt == 2 and keep_on_semantic_failure:
                    seen.append(problems)
                    return StructuredResult(value, attempt, total_in, total_out, last_model,
                                            last_text, errors_seen=seen, semantic_problems=bad)
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


GROQ_BASE_URL = "https://api.groq.com/openai/v1"
#: A 429 that asks us to wait longer than this is not retried in-process: the run is recorded as
#: failed and the next scheduled run tries again.
MAX_RATE_LIMIT_WAIT_S = 30.0

_GROQ_STOP = {"stop": "end_turn", "length": "max_tokens", "content_filter": "refusal"}


def _groq_error_body(resp: httpx.Response) -> tuple[str, str, str]:
    """(message, code, failed_generation) from a Groq error body, tolerant of a non-JSON one."""
    try:
        err = resp.json().get("error") or {}
    except (ValueError, AttributeError):
        return resp.text[:300], "", ""
    if not isinstance(err, dict):
        return str(err)[:300], "", ""
    return (str(err.get("message", ""))[:300], str(err.get("code", "")),
            str(err.get("failed_generation", "")))


class GroqClient:
    """Groq's OpenAI-compatible chat endpoint over plain httpx (no SDK).

    Credentials come from ``GROQ_API_KEY`` in the environment -- never from config or the repo.
    JSON mode is on, because every prompt asks for exactly one JSON object; validation stays
    ours (``call_structured``). Every failure is an ``LlmError`` with a message safe to store.
    """

    def __init__(
        self, *, model: str, timeout_s: float, api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep, base_url: str = GROQ_BASE_URL,
    ) -> None:
        key = api_key if api_key is not None else os.environ.get("GROQ_API_KEY", "")
        if not key.strip():
            raise LlmError("GROQ_API_KEY is not set -- add it to .env (see .env.example)")
        self._model = model
        self._sleep = sleep
        self._http = httpx.Client(
            base_url=base_url, timeout=timeout_s, transport=transport,
            headers={"Authorization": f"Bearer {key.strip()}"})

    def _post(self, path: str, body: dict[str, Any]) -> httpx.Response:
        try:
            return self._http.post(path, json=body)
        except httpx.TimeoutException as exc:
            raise LlmError("the API timed out") from exc
        except httpx.HTTPError as exc:
            raise LlmError(f"could not reach the API (network): {type(exc).__name__}") from exc

    def complete(self, *, system: str, messages: list[dict[str, str]], max_tokens: int
                 ) -> LlmReply:
        body = {
            "model": self._model,
            "messages": [{"role": "system", "content": system}, *messages],
            "max_completion_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        resp = self._post("/chat/completions", body)
        if resp.status_code == 429:
            wait = _retry_after(resp)
            if wait is not None and wait <= MAX_RATE_LIMIT_WAIT_S:
                self._sleep(wait)
                resp = self._post("/chat/completions", body)

        if resp.status_code != 200:
            message, code, failed = _groq_error_body(resp)
            if resp.status_code == 400 and code == "json_validate_failed":
                # The model produced invalid JSON. Hand the text back: call_structured's one
                # retry shows the model exactly what was wrong with it.
                return LlmReply(text=failed, model=self._model, stop_reason="end_turn")
            raise LlmError(_groq_failure(resp, message))

        try:
            data = resp.json()
            choice = data["choices"][0]
            usage = data.get("usage") or {}
            return LlmReply(
                text=choice["message"].get("content") or "",
                model=str(data.get("model") or self._model),
                input_tokens=int(usage.get("prompt_tokens", 0)),
                output_tokens=int(usage.get("completion_tokens", 0)),
                stop_reason=_GROQ_STOP.get(str(choice.get("finish_reason")), "end_turn"),
            )
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise LlmError(f"unexpected response shape from the API: {exc!r}") from exc

    def list_models(self) -> list[str]:
        """Ids of the models this key may use (the quickest live check of the key)."""
        try:
            resp = self._http.get("/models")
        except httpx.HTTPError as exc:
            raise LlmError(f"could not reach the API (network): {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise LlmError(_groq_failure(resp, _groq_error_body(resp)[0]))
        try:
            return sorted(str(m["id"]) for m in resp.json()["data"])
        except (ValueError, KeyError, TypeError) as exc:
            raise LlmError(f"unexpected response shape from the API: {exc!r}") from exc


def _retry_after(resp: httpx.Response) -> float | None:
    try:
        return float(resp.headers["retry-after"])
    except (KeyError, ValueError):
        return None


def _groq_failure(resp: httpx.Response, message: str) -> str:
    status = resp.status_code
    if status in (401, 403):
        return "authentication failed -- check GROQ_API_KEY"
    if status == 429:
        wait = _retry_after(resp)
        hint = f" (retry after {wait:g}s)" if wait is not None else ""
        return f"rate limited by the API{hint}: {message}"
    if status == 413:
        return f"the request was too large for the API: {message}"
    if 400 <= status < 500:
        return f"the API rejected the request ({status}): {message}"
    return f"API error {status}: {message}"


def make_client(ai: AiConfig) -> LlmClient:
    """The client for the configured provider. Only this module knows the concrete classes."""
    if ai.provider == "groq":
        return GroqClient(model=ai.model, timeout_s=ai.timeout_s)
    return AnthropicClient(model=ai.model, effort=ai.effort, timeout_s=ai.timeout_s)
