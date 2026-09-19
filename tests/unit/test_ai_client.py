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
