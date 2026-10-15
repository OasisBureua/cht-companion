from podcast_metadata import lookup_podcast, podcast_title, podcast_url


def test_podcast6_filename_maps_to_youtube_title() -> None:
    meta = lookup_podcast("podcast6_edit.txt")
    assert meta is not None
    assert meta["transcript_file"] == "podcast6_edit.txt"
    assert podcast_title("raw/podcast6_edit.txt") == meta["youtube_title"]
    assert podcast_url("podcast6_edit.txt") == f"https://www.youtube.com/watch?v={meta['youtube_id']}"


def test_unknown_file_is_not_a_podcast() -> None:
    assert lookup_podcast("Pembrolizumab_FDA_Label_2014.pdf") is None
    assert podcast_title("Pembrolizumab_FDA_Label_2014.pdf") is None
