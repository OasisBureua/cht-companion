from unittest.mock import MagicMock, patch

import pytest

from api.bedrock import GenerationError, generate_completion


def _mock_converse_response(text: str, stop_reason: str = "end_turn") -> dict:
    return {
        "output": {"message": {"content": [{"text": text}]}},
        "stopReason": stop_reason,
        "usage": {"inputTokens": 100, "outputTokens": 50, "totalTokens": 150},
    }


@patch("api.bedrock._client")
def test_generate_completion_returns_text_and_finish_reason(mock_client_fn) -> None:
    mock_client = MagicMock()
    mock_client.converse.return_value = _mock_converse_response("Executive summary text.")
    mock_client_fn.return_value = mock_client

    text, finish_reason = generate_completion("System prompt", "User content")

    assert text == "Executive summary text."
    assert finish_reason == "complete"

    call_kwargs = mock_client.converse.call_args.kwargs
    assert call_kwargs["system"] == [{"text": "System prompt"}]
    assert call_kwargs["messages"] == [{"role": "user", "content": [{"text": "User content"}]}]


@patch("api.bedrock._client")
def test_generate_completion_maps_max_tokens_stop_reason_to_truncated(mock_client_fn) -> None:
    mock_client = MagicMock()
    mock_client.converse.return_value = _mock_converse_response("Partial...", stop_reason="max_tokens")
    mock_client_fn.return_value = mock_client

    _text, finish_reason = generate_completion("System prompt", "User content")

    assert finish_reason == "truncated"


@patch("api.bedrock._client")
def test_generate_completion_joins_multiple_content_blocks(mock_client_fn) -> None:
    mock_client = MagicMock()
    mock_client.converse.return_value = {
        "output": {"message": {"content": [{"text": "Part one. "}, {"text": "Part two."}]}},
        "stopReason": "end_turn",
        "usage": {},
    }
    mock_client_fn.return_value = mock_client

    text, _finish_reason = generate_completion("System prompt", "User content")

    assert text == "Part one. Part two."


@patch("api.bedrock._client")
def test_generate_completion_raises_generation_error_on_boto3_failure(mock_client_fn) -> None:
    mock_client = MagicMock()
    mock_client.converse.side_effect = RuntimeError("throttled")
    mock_client_fn.return_value = mock_client

    with pytest.raises(GenerationError, match="throttled"):
        generate_completion("System prompt", "User content")


@patch("api.bedrock._client")
def test_generate_completion_passes_max_tokens_and_temperature(mock_client_fn) -> None:
    mock_client = MagicMock()
    mock_client.converse.return_value = _mock_converse_response("Text.")
    mock_client_fn.return_value = mock_client

    generate_completion("System prompt", "User content", max_tokens=2048, temperature=0.5)

    call_kwargs = mock_client.converse.call_args.kwargs
    assert call_kwargs["inferenceConfig"] == {"maxTokens": 2048, "temperature": 0.5}


@patch("api.bedrock._client")
def test_generate_completion_omits_temperature_by_default(mock_client_fn) -> None:
    mock_client = MagicMock()
    mock_client.converse.return_value = _mock_converse_response("Text.")
    mock_client_fn.return_value = mock_client

    generate_completion("System prompt", "User content")

    call_kwargs = mock_client.converse.call_args.kwargs
    assert "temperature" not in call_kwargs["inferenceConfig"]
