import copy
import json
import subprocess
from types import SimpleNamespace

import pytest
from test_model_budget import MemoryStore

from smartci.investigation.budget import BudgetError, Ledger
from smartci.investigation.http import HTTPS, Reply
from smartci.investigation.openai_provider import OpenAIProvider
from smartci.selection import digest


class ModelAPI:
    def __init__(self, store, count=200, output=None):
        self.store, self.count = store, count
        self.output = output or {
            "model": "gpt-6.2-astra",
            "service_tier": "default",
            "status": "completed",
            "usage": {"input_tokens": 200, "output_tokens": 20},
            "output": [
                {"type": "reasoning", "encrypted_content": "DO_NOT_STORE_REASONING"},
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": '{"kind":"finish"}'}],
                },
            ],
        }
        self.calls = []

    def request(self, method, path, body):
        assert len(self.store.state.reservations) == 1  # Durable admission first.
        self.calls.append((method, path, copy.deepcopy(body)))
        if path.endswith("input_tokens"):
            return Reply(
                200,
                json.dumps(
                    {"object": "response.input_tokens", "input_tokens": self.count}
                ).encode(),
            )
        return Reply(200, json.dumps(self.output).encode())


def provider(store=None, **kwargs):
    store = store or MemoryStore()
    api = ModelAPI(store, **kwargs)
    return (
        OpenAIProvider(api, Ledger(store, "approved"), digest("investigation")),
        api,
        store,
    )


def test_response_request_is_bounded_and_usage_is_not_confused_with_reservation():
    p, api, store = provider()
    assert p.next_action('{"previous":null}') == '{"kind":"finish"}'
    assert len(api.calls) == 2
    payload = api.calls[1][2]
    assert payload["max_output_tokens"] == 1000
    assert payload["store"] is False
    assert payload["service_tier"] == "default"
    assert payload["tools"] == []
    assert payload["prompt_cache_options"] == {"mode": "explicit", "ttl": "30m"}
    assert p.accounting()["model_calls"] == 1
    assert p.accounting()["reserved_micro_usd"] == 90_000
    assert store.state.reservations[0].usage == {
        "input_tokens": 200,
        "output_tokens": 20,
    }
    assert "DO_NOT_STORE_REASONING" not in json.dumps(p.messages)


@pytest.mark.parametrize("count", [0, -1, True, 5001, 200.0, "200"])
def test_invalid_or_excessive_input_count_prevents_inference(count):
    p, api, store = provider(count=count)
    with pytest.raises(BudgetError):
        p.next_action("{}")
    assert len(api.calls) == 1
    assert p.model_calls == 0
    assert len(store.state.reservations) == 1


@pytest.mark.parametrize(
    "defect",
    [
        "incomplete",
        "usage_missing",
        "usage_excess",
        "wrong_model",
        "wrong_tier",
        "refusal",
        "shell_action",
        "multiple_actions",
    ],
)
def test_invalid_responses_cannot_become_tool_actions(defect):
    p, api, store = provider()
    if defect == "incomplete":
        api.output["status"] = "incomplete"
    elif defect == "usage_missing":
        api.output.pop("usage")
    elif defect == "usage_excess":
        api.output["usage"]["output_tokens"] = 1001
    elif defect == "wrong_model":
        api.output["model"] = "different"
    elif defect == "wrong_tier":
        api.output["service_tier"] = "priority"
    elif defect == "refusal":
        api.output["output"][1]["content"][0] = {"type": "refusal"}
    elif defect == "shell_action":
        api.output["output"][1]["content"][0]["text"] = (
            '{"kind":"execute","command":"cat secret"}'
        )
    elif defect == "multiple_actions":
        api.output["output"].append(api.output["output"][1])
    with pytest.raises(ValueError):
        p.next_action("{}")
    assert p.model_calls == 1
    assert len(store.state.reservations) == 1


def test_timeout_and_duplicate_invocation_never_retry():
    p, api, store = provider()

    def fail(method, path, body):
        raise OSError("TOKEN_MUST_NOT_BE_LOGGED")

    api.request = fail
    with pytest.raises(OSError):
        p.next_action("{}")
    restarted, restarted_api, _ = provider(store)
    with pytest.raises(ValueError):
        restarted.next_action("{}")
    assert restarted_api.calls == []
    assert len(store.state.reservations) == 1


def test_http_uses_isolated_worker_with_credentials_only_on_stdin(monkeypatch):
    def run(argv, **kwargs):
        assert "SECRET_KEY" not in str(argv)
        assert argv[1:3] == ["-I", "-m"]
        assert kwargs["timeout"] == 20
        assert "OPENAI_API_KEY" not in kwargs["env"]
        assert json.loads(kwargs["input"])["token"] == "SECRET_KEY"
        return SimpleNamespace(returncode=0, stdout=b"200\n{}")

    monkeypatch.setattr(subprocess, "run", run)
    assert HTTPS("api.openai.com", "SECRET_KEY").request(
        "POST", "/v1/responses", {}
    ) == Reply(200, b"{}")

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("SECRET_KEY", 20)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(OSError, match="^API transport failed$"):
        HTTPS("api.openai.com", "SECRET_KEY").request("POST", "/v1/responses", {})


@pytest.mark.parametrize(
    "host,token",
    [
        ("evil.invalid", "key"),
        ("api.openai.com", ""),
        ("api.openai.com", "x\r\nHeader: x"),
    ],
)
def test_host_and_credential_boundaries(host, token):
    with pytest.raises(ValueError):
        HTTPS(host, token)
