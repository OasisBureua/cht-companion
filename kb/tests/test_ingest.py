from unittest.mock import MagicMock, patch

from embedding import EmbeddingError
from ingest import ingest_source, make_source_id
from store import SourceInput

SOURCE = SourceInput(
    source_id="youtube_caption:abc123",
    source_type="youtube_caption",
    title="Test Video",
    url="https://youtube.com/watch?v=abc123",
    embedding_model="amazon.titan-embed-text-v2:0",
    doctors=["Dr. Test"],
    topics=["T-DXd"],
)


def test_make_source_id_deterministic() -> None:
    assert make_source_id("youtube_caption", "abc123") == "youtube_caption:abc123"
    # same inputs, same id — re-ingest targets the same row, unlike the legacy uuid-suffixed scheme
    assert make_source_id("youtube_caption", "abc123") == make_source_id("youtube_caption", "abc123")


def test_ingest_empty_text_is_a_noop() -> None:
    result = ingest_source(SOURCE, "   ")
    assert result.chunks_total == 0
    assert result.chunks_written == 0
    assert result.error is None


@patch("ingest.embed_texts")
def test_ingest_embedding_failure_writes_nothing(mock_embed) -> None:
    mock_embed.side_effect = EmbeddingError("throttled")
    result = ingest_source(SOURCE, "Some real transcript text about HER2-low breast cancer treatment.")
    assert result.error == "throttled"
    assert result.chunks_written == 0


@patch("ingest.upsert_chunks")
@patch("ingest.upsert_source")
@patch("ingest.connect")
@patch("ingest.embed_texts")
def test_ingest_happy_path_calls_upsert(mock_embed, mock_connect, mock_upsert_source, mock_upsert_chunks) -> None:
    text = "Sentence about T-DXd. " * 5
    from chunking import chunk_text

    n_chunks = len(chunk_text(text))
    mock_embed.return_value = [[0.0] * 1024 for _ in range(n_chunks)]

    conn_cm = MagicMock()
    mock_connect.return_value.__enter__.return_value = conn_cm
    conn_cm.transaction.return_value.__enter__.return_value = None

    from store import UpsertResult

    mock_upsert_chunks.return_value = UpsertResult(written=n_chunks, skipped=0)

    result = ingest_source(SOURCE, text)

    assert result.chunks_written == n_chunks
    assert result.error is None
    mock_upsert_source.assert_called_once()
    mock_upsert_chunks.assert_called_once()
