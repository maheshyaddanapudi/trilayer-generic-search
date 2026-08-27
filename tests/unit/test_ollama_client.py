from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.llm.ollama_client import OllamaLLMClient


def _ok_response(content: str = "answer text") -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"message": {"role": "assistant", "content": content}}
    return resp


def test_ollama_client_success():
    with patch("src.llm.ollama_client.httpx.post", return_value=_ok_response("hi there")) as mock_post:
        client = OllamaLLMClient(base_url="http://localhost:11434", model="gemma4:31b")
        result = client.complete("Hello", max_tokens=128, temperature=0.2)

    assert result == "hi there"
    # Validate request payload shape
    args, kwargs = mock_post.call_args
    assert args[0] == "http://localhost:11434/api/chat"
    payload = kwargs["json"]
    assert payload["model"] == "gemma4:31b"
    assert payload["stream"] is False
    assert payload["options"]["temperature"] == 0.2
    assert payload["options"]["num_predict"] == 128
    assert payload["messages"] == [{"role": "user", "content": "Hello"}]


def test_ollama_client_strips_trailing_slash_in_base_url():
    with patch("src.llm.ollama_client.httpx.post", return_value=_ok_response()) as mock_post:
        client = OllamaLLMClient(base_url="http://localhost:11434/", model="m")
        client.complete("x")

    assert mock_post.call_args[0][0] == "http://localhost:11434/api/chat"


def test_ollama_client_with_system_prompt():
    with patch("src.llm.ollama_client.httpx.post", return_value=_ok_response()) as mock_post:
        client = OllamaLLMClient(base_url="http://localhost:11434", model="m")
        client.complete("Hi", system="You are helpful")

    payload = mock_post.call_args[1]["json"]
    assert payload["messages"][0] == {"role": "system", "content": "You are helpful"}
    assert payload["messages"][1] == {"role": "user", "content": "Hi"}


def test_ollama_client_no_system_omits_system_message():
    with patch("src.llm.ollama_client.httpx.post", return_value=_ok_response()) as mock_post:
        client = OllamaLLMClient(base_url="http://localhost:11434", model="m")
        client.complete("Hi")

    payload = mock_post.call_args[1]["json"]
    assert all(m["role"] != "system" for m in payload["messages"])


def test_ollama_client_retry_then_succeed():
    bad = MagicMock()
    bad.raise_for_status.side_effect = RuntimeError("transient 500")
    good = _ok_response("recovered")

    with patch("src.llm.ollama_client.httpx.post", side_effect=[bad, good]), \
         patch("src.llm.ollama_client.time") as mock_time:
        client = OllamaLLMClient(base_url="http://x", model="m", max_retries=3)
        result = client.complete("Hi")

    assert result == "recovered"
    assert mock_time.sleep.call_count == 1


def test_ollama_client_all_retries_fail():
    bad = MagicMock()
    bad.raise_for_status.side_effect = RuntimeError("always fails")

    with patch("src.llm.ollama_client.httpx.post", return_value=bad), \
         patch("src.llm.ollama_client.time") as mock_time:
        client = OllamaLLMClient(base_url="http://x", model="m", max_retries=3)
        with pytest.raises(RuntimeError, match="failed after 3 attempts"):
            client.complete("Hi")

    assert mock_time.sleep.call_count == 3


def test_ollama_client_unexpected_response_shape_treated_as_error():
    """If 'content' is not a string, the client should retry then fail."""
    weird = MagicMock()
    weird.raise_for_status = MagicMock()
    weird.json.return_value = {"message": {"content": {"unexpected": "object"}}}

    with patch("src.llm.ollama_client.httpx.post", return_value=weird), \
         patch("src.llm.ollama_client.time"):
        client = OllamaLLMClient(base_url="http://x", model="m", max_retries=1)
        with pytest.raises(RuntimeError, match="failed after 1 attempts"):
            client.complete("Hi")


def test_ollama_client_missing_message_treated_as_empty_string():
    """If 'message' is absent entirely, content defaults to '' (still a string)."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {}  # no "message" key at all

    with patch("src.llm.ollama_client.httpx.post", return_value=resp):
        client = OllamaLLMClient(base_url="http://x", model="m")
        result = client.complete("Hi")

    assert result == ""
