from handler import handler


def test_handler_returns_ok() -> None:
    result = handler({"source": "aws.events"}, None)
    assert result["ok"] is True
    assert "cht-companion-kb" in result["message"]
