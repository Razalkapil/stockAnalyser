"""Structured calling: fences, one retry with the errors, and never raising."""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from stk.ai.client import LlmError, LlmReply, call_structured, strip_fences


class Out(BaseModel):
    n: int
    label: str


class Scripted:
    """Replies with each scripted item in turn; an Exception item is raised."""

    def __init__(self, *items):
        self.items = list(items)
        self.calls: list[list[dict]] = []

    def complete(self, *, system, messages, max_tokens):
        self.calls.append(list(messages))
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def reply(text, *, stop="end_turn", tin=100, tout=20):
    return LlmReply(text=text, model="m", input_tokens=tin, output_tokens=tout, stop_reason=stop)


def run(client, check=None):
    return call_structured(client, system="s", user="u", schema=Out, max_tokens=100,
                           semantic_check=check)


class TestFences:
    @pytest.mark.parametrize("text", [
        '{"n": 1, "label": "a"}',
        '```json\n{"n": 1, "label": "a"}\n```',
        '```\n{"n": 1, "label": "a"}\n```',
        '  ```JSON\n{"n": 1, "label": "a"}\n```  ',
        '\n{"n": 1, "label": "a"}\n',
    ])
    def test_a_fenced_or_bare_reply_parses(self, text):
        assert json.loads(strip_fences(text)) == {"n": 1, "label": "a"}

    def test_a_fence_in_the_middle_is_not_touched(self):
        assert strip_fences('x ```y``` z') == 'x ```y``` z'


class TestRetry:
    def test_first_try_success_makes_one_call(self):
        c = Scripted(reply('{"n": 1, "label": "a"}'))
        r = run(c)
        assert r.value == Out(n=1, label="a") and r.attempts == 1 and len(c.calls) == 1

    def test_invalid_then_valid_retries_once_and_shows_the_model_its_errors(self):
        c = Scripted(reply('{"n": "not a number", "label": "a"}'), reply('{"n": 2, "label": "b"}'))
        r = run(c)
        assert r.value == Out(n=2, label="b") and r.attempts == 2
        retry = c.calls[1]
        assert retry[-2] == {"role": "assistant", "content": '{"n": "not a number", "label": "a"}'}
        assert "n:" in retry[-1]["content"] and "rejected" in retry[-1]["content"]

    def test_invalid_twice_gives_up_with_the_reason_and_never_raises(self):
        c = Scripted(reply("not json"), reply("still not json"))
        r = run(c)
        assert r.value is None and r.attempts == 2 and len(c.calls) == 2
        assert r.error and "invalid output after one retry" in r.error

    def test_a_third_call_is_never_made(self):
        c = Scripted(reply("x"), reply("y"), reply('{"n": 1, "label": "a"}'))
        run(c)
        assert len(c.calls) == 2

    def test_tokens_are_summed_across_attempts(self):
        c = Scripted(reply("bad", tin=100, tout=10), reply('{"n": 1, "label": "a"}', tin=150,
                                                           tout=30))
        r = run(c)
        assert (r.input_tokens, r.output_tokens) == (250, 40)


class TestSemanticChecks:
    def test_problems_a_schema_cannot_express_drive_the_retry(self):
        c = Scripted(reply('{"n": 99, "label": "a"}'), reply('{"n": 1, "label": "a"}'))
        r = run(c, lambda v: ["n=99 is not a valid pick"] if v.n == 99 else [])
        assert r.value == Out(n=1, label="a") and r.attempts == 2
        assert "n=99 is not a valid pick" in c.calls[1][-1]["content"]

    def test_a_persistent_semantic_problem_fails(self):
        c = Scripted(reply('{"n": 99, "label": "a"}'), reply('{"n": 99, "label": "a"}'))
        r = run(c, lambda v: ["invented"])
        assert r.value is None and "invented" in r.error


class TestFailureModes:
    def test_a_failed_call_is_reported_not_raised(self):
        r = run(Scripted(LlmError("rate limited by the API")))
        assert r.value is None and r.error == "call failed: rate limited by the API"

    def test_a_failure_on_the_retry_keeps_the_tokens_already_spent(self):
        r = run(Scripted(reply("bad", tin=100, tout=10), LlmError("network")))
        assert r.value is None and (r.input_tokens, r.output_tokens) == (100, 10)

    def test_a_refusal_is_not_retried(self):
        c = Scripted(reply("", stop="refusal"))
        r = run(c)
        assert r.value is None and "declined" in r.error and len(c.calls) == 1

    def test_a_truncated_reply_is_retried_and_told_why(self):
        c = Scripted(reply('{"n": 1, "lab', stop="max_tokens"), reply('{"n": 1, "label": "a"}'))
        r = run(c)
        assert r.value is not None and "cut off" in c.calls[1][-1]["content"]

    def test_extra_keys_are_rejected_not_silently_dropped(self):
        class Strict(BaseModel):
            model_config = {"extra": "forbid"}
            n: int
        c = Scripted(reply('{"n": 1, "extra": 2}'), reply('{"n": 1}'))
        r = call_structured(c, system="s", user="u", schema=Strict, max_tokens=10)
        assert r.attempts == 2 and r.value == Strict(n=1)


# --- Groq ---------------------------------------------------------------------------------------

import httpx  # noqa: E402

from stk.ai.client import GroqClient, make_client  # noqa: E402
from stk.config.ai import AiConfig, ProviderSettings  # noqa: E402


def groq(handler, **kw):
    sleeps: list[float] = []
    client = GroqClient(model="m1", timeout_s=5, api_key="k-secret",
                        transport=httpx.MockTransport(handler), sleep=sleeps.append, **kw)
    return client, sleeps


def ok(content='{"n": 1, "label": "a"}', finish="stop", pin=11, pout=7, model="m1-served"):
    return httpx.Response(200, json={
        "model": model, "choices": [{"message": {"content": content}, "finish_reason": finish}],
        "usage": {"prompt_tokens": pin, "completion_tokens": pout}})


def err(status, message="boom", code="", headers=None, **extra):
    return httpx.Response(status, headers=headers,
                          json={"error": {"message": message, "code": code, **extra}})


def call(client):
    return client.complete(system="SYS", messages=[{"role": "user", "content": "hi"}],
                           max_tokens=123)


class TestGroqRequestAndReply:
    def test_request_shape(self):
        seen = {}

        def handler(request):
            seen["url"], seen["auth"] = str(request.url), request.headers["authorization"]
            seen["body"] = json.loads(request.content)
            return ok()

        call(groq(handler)[0])
        assert seen["url"] == "https://api.groq.com/openai/v1/chat/completions"
        assert seen["auth"] == "Bearer k-secret"
        body = seen["body"]
        assert body["model"] == "m1" and body["max_completion_tokens"] == 123
        assert body["response_format"] == {"type": "json_object"}
        assert body["messages"] == [{"role": "system", "content": "SYS"},
                                    {"role": "user", "content": "hi"}]

    def test_reply_mapping_and_usage(self):
        r = call(groq(lambda _r: ok(pin=1234, pout=56))[0])
        assert (r.text, r.model, r.input_tokens, r.output_tokens, r.stop_reason) == (
            '{"n": 1, "label": "a"}', "m1-served", 1234, 56, "end_turn")

    @pytest.mark.parametrize(("finish", "expected"), [
        ("stop", "end_turn"), ("length", "max_tokens"), ("content_filter", "refusal"),
        ("tool_calls", "end_turn")])
    def test_finish_reason_mapping(self, finish, expected):
        assert call(groq(lambda _r: ok(finish=finish))[0]).stop_reason == expected

    def test_a_null_content_is_an_empty_reply_not_a_crash(self):
        assert call(groq(lambda _r: ok(content=None))[0]).text == ""

    def test_a_truncated_reply_drives_call_structured_s_one_retry(self):
        replies = iter([ok('{"n": 1, "lab', finish="length"), ok()])
        client, _ = groq(lambda _r: next(replies))
        r = call_structured(client, system="s", user="u", schema=Out, max_tokens=50)
        assert r.value == Out(n=1, label="a") and r.attempts == 2
        assert r.input_tokens == 22  # both calls counted


class TestGroqFailures:
    @pytest.mark.parametrize(("status", "fragment"), [
        (401, "authentication failed"), (403, "authentication failed"),
        (413, "too large"), (400, r"rejected the request \(400\)"),
        (404, r"rejected the request \(404\)"), (500, "API error 500"), (503, "API error 503")])
    def test_status_maps_to_a_safe_message(self, status, fragment):
        with pytest.raises(LlmError, match=fragment) as e:
            call(groq(lambda _r: err(status))[0])
        assert "k-secret" not in str(e.value)  # the key never reaches a stored message

    def test_a_short_rate_limit_waits_once_and_retries(self):
        replies = iter([err(429, headers={"retry-after": "2"}), ok()])
        client, sleeps = groq(lambda _r: next(replies))
        assert call(client).text
        assert sleeps == [2.0]

    def test_a_long_rate_limit_is_not_waited_out(self):
        client, sleeps = groq(
            lambda _r: err(429, "tokens per minute", headers={"retry-after": "600"}))
        with pytest.raises(LlmError, match=r"rate limited.*retry after 600s.*tokens per minute"):
            call(client)
        assert sleeps == []

    def test_a_persistent_short_rate_limit_gives_up_after_one_retry(self):
        n = []
        client, sleeps = groq(lambda _r: (n.append(1), err(429, headers={"retry-after": "1"}))[1])
        with pytest.raises(LlmError, match="rate limited"):
            call(client)
        assert len(n) == 2 and sleeps == [1.0]

    def test_json_validate_failed_hands_the_bad_text_to_the_retry(self):
        replies = iter([
            err(400, "Failed to generate JSON", code="json_validate_failed",
                failed_generation='{"n": "x"'),
            ok()])
        seen = []

        def handler(request):
            seen.append(json.loads(request.content)["messages"])
            return next(replies)

        r = call_structured(groq(handler)[0], system="s", user="u", schema=Out, max_tokens=50)
        assert r.value == Out(n=1, label="a") and r.attempts == 2
        # the second request showed the model its own invalid output and why it failed
        assert seen[1][-2] == {"role": "assistant", "content": '{"n": "x"'}
        assert "rejected" in seen[1][-1]["content"]

    def test_network_and_timeout_errors_are_llm_errors(self):
        def refuse(_r):
            raise httpx.ConnectError("no route")

        def slow(_r):
            raise httpx.ReadTimeout("slow")

        with pytest.raises(LlmError, match="network"):
            call(groq(refuse)[0])
        with pytest.raises(LlmError, match="timed out"):
            call(groq(slow)[0])

    @pytest.mark.parametrize("body", [{}, {"choices": []}, {"choices": [{}]}, ["x"]])
    def test_a_malformed_success_body_is_an_llm_error(self, body):
        with pytest.raises(LlmError, match="unexpected response shape"):
            call(groq(lambda _r: httpx.Response(200, json=body))[0])

    def test_call_structured_reports_a_failed_call_not_invalid_output(self):
        r = call_structured(groq(lambda _r: err(401))[0], system="s", user="u", schema=Out,
                            max_tokens=50)
        assert r.value is None and r.error.startswith("call failed")

    def test_a_missing_key_is_a_clear_error(self, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        with pytest.raises(LlmError, match="GROQ_API_KEY is not set"):
            GroqClient(model="m", timeout_s=5)

    def test_a_blank_key_counts_as_missing(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "   ")
        with pytest.raises(LlmError, match="GROQ_API_KEY is not set"):
            GroqClient(model="m", timeout_s=5)


class TestModels:
    def test_lists_sorted_ids(self):
        client, _ = groq(lambda _r: httpx.Response(200, json={"data": [{"id": "b"}, {"id": "a"}]}))
        assert client.list_models() == ["a", "b"]

    def test_a_bad_key_is_an_llm_error(self):
        with pytest.raises(LlmError, match="authentication failed"):
            groq(lambda _r: err(401))[0].list_models()


class TestInputGuard:
    def test_an_oversized_prompt_is_refused_locally_and_reported_as_a_failed_call(self):
        c = Scripted()  # would raise IndexError if called
        r = call_structured(c, system="s" * 10, user="u" * 100, schema=Out, max_tokens=10,
                            max_input_chars=50)
        assert c.calls == [] and r.value is None and r.attempts == 0
        assert r.error.startswith("call failed") and "max_input_chars=50" in r.error

    def test_within_the_limit_it_proceeds(self):
        r = call_structured(Scripted(reply('{"n": 1, "label": "a"}')), system="s", user="u",
                            schema=Out, max_tokens=10, max_input_chars=50)
        assert r.value == Out(n=1, label="a")


class TestProviderSelection:
    def test_groq_is_the_default_provider_and_resolves_its_settings(self):
        cfg = AiConfig(providers={"groq": ProviderSettings(model="g", max_tokens=5000,
                                                           max_input_chars=99),
                                  "anthropic": ProviderSettings(model="a")})
        assert (cfg.provider, cfg.model, cfg.max_tokens, cfg.max_input_chars) == (
            "groq", "g", 5000, 99)

    def test_anthropic_resolves_its_own_settings(self):
        cfg = AiConfig(provider="anthropic", providers={
            "groq": ProviderSettings(model="g"),
            "anthropic": ProviderSettings(model="a", max_tokens=777, effort="high")})
        assert (cfg.model, cfg.max_tokens, cfg.effort) == ("a", 777, "high")

    def test_a_missing_provider_block_fails_when_config_loads(self):
        with pytest.raises(ValueError, match=r"no providers\.anthropic block"):
            AiConfig(provider="anthropic", providers={"groq": ProviderSettings(model="g")})

    def test_an_unknown_provider_is_rejected(self):
        with pytest.raises(ValueError):
            AiConfig(provider="openai", providers={})  # type: ignore[arg-type]

    def test_the_factory_builds_the_configured_client(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "k")
        cfg = AiConfig(providers={"groq": ProviderSettings(model="g")})
        assert isinstance(make_client(cfg), GroqClient)

    def test_the_factory_fails_loudly_without_a_key(self, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        with pytest.raises(LlmError, match="GROQ_API_KEY"):
            make_client(AiConfig(providers={"groq": ProviderSettings(model="g")}))

    def test_the_committed_config_selects_a_priced_model(self):
        from stk.config.ai import load_ai_config  # noqa: PLC0415

        cfg = load_ai_config()
        assert cfg.provider in ("groq", "anthropic")
        assert cfg.estimate_cost_usd(cfg.model, 1000, 1000) is not None
