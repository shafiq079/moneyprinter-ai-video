from app.services.local_ai.media import _aspect_matches


def test_aspect_match_requires_ratio_not_only_orientation():
    assert _aspect_matches(576, 1024, "9:16")
    assert _aspect_matches(1024, 576, "16:9")
    assert _aspect_matches(704, 1280, "9:16")
    assert _aspect_matches(1280, 704, "16:9")

    # These were the original Hugging Face smoke dimensions. They have the
    # right orientation, but are 2:3 / 3:2 rather than 9:16 / 16:9.
    assert not _aspect_matches(512, 768, "9:16")
    assert not _aspect_matches(768, 512, "16:9")


def test_square_aspect_keeps_small_rounding_tolerance():
    assert _aspect_matches(1024, 1024, "1:1")
    assert _aspect_matches(1000, 1024, "1:1")
    assert not _aspect_matches(900, 1024, "1:1")
