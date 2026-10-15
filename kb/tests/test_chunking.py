from chunking import chunk_text


def test_empty_text_returns_no_chunks() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_short_text_is_one_chunk() -> None:
    chunks = chunk_text("A short sentence.")
    assert len(chunks) == 1
    assert chunks[0].index == 0
    assert chunks[0].text == "A short sentence."


def test_long_text_splits_into_multiple_chunks() -> None:
    paragraph = "This is a sentence about breast cancer treatment. " * 60
    chunks = chunk_text(paragraph, target_chars=500, overlap_chars=100)
    assert len(chunks) > 1
    assert [c.index for c in chunks] == list(range(len(chunks)))
    for c in chunks:
        assert c.text


def test_long_line_with_no_sentence_breaks_still_splits() -> None:
    # regression: a single long \n-delimited paragraph with no ". " punctuation
    # nearby used to fall through to one oversized chunk instead of recursing
    # into finer separators (word-level fallback).
    long_line = ("word " * 3000).strip() + "\n" + ("more " * 10)
    chunks = chunk_text(long_line, target_chars=1024, overlap_chars=200)
    assert len(chunks) > 1
    assert all(len(c.text) <= 1024 + 200 for c in chunks)  # allow overlap slack


def test_chunks_overlap_carries_context() -> None:
    paragraph = "Sentence number %d about T-DXd and HER2-low breast cancer treatment options. "
    text = "".join(paragraph % i for i in range(40))
    chunks = chunk_text(text, target_chars=400, overlap_chars=80)
    assert len(chunks) > 1
    # the tail of chunk N should reappear at the head of chunk N+1
    tail = chunks[0].text[-40:]
    assert tail in chunks[1].text or chunks[1].text.startswith(tail[:20])
