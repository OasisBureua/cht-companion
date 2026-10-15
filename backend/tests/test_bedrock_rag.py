from unittest.mock import MagicMock, patch

import pytest

from api import bedrock
from api.bedrock import RerankError, RewriteError, _build_generation_messages, rerank, rewrite_query


def test_generation_messages_without_history_is_one_user_turn() -> None:
    messages = _build_generation_messages("What is CHT?", "[c1] (About): CHM is ...")

    assert messages == [{"role": "user", "content": "Context:\n[c1] (About): CHM is ...\n\nQuestion: What is CHT?"}]


def test_generation_messages_says_when_nothing_matched() -> None:
    [message] = _build_generation_messages("Who won the game?", "")

    assert message["content"].startswith("No knowledge-base context matched this question.")


def test_generation_messages_put_history_first_and_strip_old_citations() -> None:
    history = [
        {"role": "user", "content": "Tell me about DB-12"},
        {"role": "assistant", "content": "DB-12 enrolled HER2+ patients [c1] [c2]."},
    ]

    messages = _build_generation_messages("what about brain mets?", "[c1] (DB-12): ...", history)

    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[1]["content"] == "DB-12 enrolled HER2+ patients."
    assert messages[2]["content"].endswith("Question: what about brain mets?")


def test_generation_messages_keep_roles_alternating() -> None:
    history = [
        {"role": "assistant", "content": "Hello, how can I help?"},
        {"role": "user", "content": "first"},
        {"role": "user", "content": "second"},
        {"role": "assistant", "content": "   "},
    ]

    messages = _build_generation_messages("third", "", history)

    assert [m["role"] for m in messages] == ["user"]
    assert messages[0]["content"].startswith("first\n\nsecond\n\n")


@patch("api.bedrock._agent_client")
def test_rerank_returns_scores_best_first(mock_client_fn) -> None:
    client = MagicMock()
    client.rerank.return_value = {"results": [{"index": 1, "relevanceScore": 0.2}, {"index": 0, "relevanceScore": 0.9}]}
    mock_client_fn.return_value = client

    assert rerank("q", ["a", "b"], top_n=5) == [(0, 0.9), (1, 0.2)]

    kwargs = client.rerank.call_args.kwargs
    assert kwargs["queries"] == [{"type": "TEXT", "textQuery": {"text": "q"}}]
    config = kwargs["rerankingConfiguration"]["bedrockRerankingConfiguration"]
    assert config["numberOfResults"] == 2
    assert config["modelConfiguration"]["modelArn"].endswith("foundation-model/cohere.rerank-v3-5:0")


@patch("api.bedrock._agent_client")
def test_rerank_wraps_bedrock_errors(mock_client_fn) -> None:
    mock_client_fn.return_value.rerank.side_effect = RuntimeError("AccessDeniedException")

    with pytest.raises(RerankError, match="AccessDenied"):
        rerank("q", ["a"], top_n=5)


def test_rerank_disabled_raises(monkeypatch) -> None:
    monkeypatch.setattr(bedrock, "RERANK_MODEL", "")

    with pytest.raises(RerankError, match="disabled"):
        rerank("q", ["a"], top_n=5)


@patch("api.bedrock._client")
def test_rewrite_query_returns_model_text(mock_client_fn) -> None:
    client = MagicMock()
    client.converse.return_value = {"output": {"message": {"content": [{"text": ' "DB-12 brain metastases" '}]}}}
    mock_client_fn.return_value = client

    rewritten = rewrite_query(
        "what about brain mets?", [{"role": "assistant", "content": "DB-12 is a trial [c1]."}]
    )

    assert rewritten == "DB-12 brain metastases"
    sent = client.converse.call_args.kwargs["messages"][0]["content"][0]["text"]
    assert "assistant: DB-12 is a trial." in sent
    assert "Latest message: what about brain mets?" in sent


@patch("api.bedrock._client")
def test_rewrite_query_empty_result_raises(mock_client_fn) -> None:
    mock_client_fn.return_value.converse.return_value = {"output": {"message": {"content": [{"text": "  "}]}}}

    with pytest.raises(RewriteError):
        rewrite_query("q", [{"role": "user", "content": "x"}])
