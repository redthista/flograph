"""flograph.core.images — deciding whether a source string is a file path,
a data: URI or a base64 blob, and turning it into bytes.

Deliberately Qt-free: this module is shared by the Image node (which runs in
an engine worker) and the canvas card, so it must import on a bare install.
"""
import base64

import pytest

from flograph.core.images import (
    UNKNOWN_MIME, decode_base64, looks_like_base64, parse_data_uri,
    resolve_source, sniff_mime, to_data_uri,
)

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
    "IQAAAABJRU5ErkJggg==")
GIF = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")


class TestSniffMime:
    def test_recognises_formats_by_magic_bytes(self):
        assert sniff_mime(PNG) == "image/png"
        assert sniff_mime(GIF) == "image/gif"
        assert sniff_mime(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
        assert sniff_mime(b"BM....") == "image/bmp"

    def test_webp_marker_is_not_at_the_start(self):
        assert sniff_mime(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"

    def test_svg_is_recognised_by_its_text(self):
        assert sniff_mime(b'<svg xmlns="...">') == "image/svg+xml"
        assert sniff_mime(b'<?xml version="1.0"?><svg/>') == "image/svg+xml"

    def test_falls_back_to_the_extension(self):
        assert sniff_mime(b"\x00\x01\x02", "/x/thing.webp") == "image/webp"

    def test_gives_up_cleanly(self):
        assert sniff_mime(b"\x00\x01\x02", "/x/thing.bin") == UNKNOWN_MIME


class TestLooksLikeBase64:
    def test_accepts_a_real_blob(self):
        assert looks_like_base64(base64.b64encode(PNG).decode())

    def test_rejects_short_strings(self):
        assert not looks_like_base64("abc")

    def test_rejects_paths(self):
        assert not looks_like_base64("/home/someone/pictures/holiday.png")
        assert not looks_like_base64(r"C:\Users\me\Pictures\shot.png")

    def test_rejects_prose(self):
        assert not looks_like_base64("not a file and not base64!!")


class TestDecodeBase64:
    def test_round_trips(self):
        assert decode_base64(base64.b64encode(PNG).decode()) == PNG

    def test_tolerates_whitespace_and_newlines(self):
        packed = base64.b64encode(PNG).decode()
        wrapped = "\n".join(packed[i:i + 8] for i in range(0, len(packed), 8))
        assert decode_base64(wrapped) == PNG

    def test_accepts_the_urlsafe_alphabet(self):
        blob = bytes(range(250, 256)) + PNG
        assert decode_base64(base64.urlsafe_b64encode(blob).decode()) == blob

    def test_tolerates_missing_padding(self):
        packed = base64.b64encode(PNG).decode().rstrip("=")
        assert decode_base64(packed) == PNG

    def test_rejects_rubbish(self):
        assert decode_base64("this is not base64 at all !!!") is None


class TestParseDataUri:
    def test_reads_a_base64_uri(self):
        uri = to_data_uri(PNG, "image/png")
        data, mime = parse_data_uri(uri)
        assert data == PNG and mime == "image/png"

    def test_reads_a_percent_encoded_uri(self):
        data, mime = parse_data_uri("data:image/svg+xml,%3Csvg%2F%3E")
        assert data == b"<svg/>" and mime == "image/svg+xml"

    def test_sniffs_when_the_uri_omits_the_type(self):
        packed = base64.b64encode(PNG).decode()
        data, mime = parse_data_uri(f"data:;base64,{packed}")
        assert data == PNG and mime == "image/png"

    def test_not_a_data_uri(self):
        assert parse_data_uri("/x/a.png") is None


class TestResolveSource:
    def test_a_file(self, tmp_path):
        path = tmp_path / "a.png"
        path.write_bytes(PNG)
        data, mime, resolved = resolve_source(str(path))
        assert data == PNG and mime == "image/png"
        assert resolved == str(path)   # a real file reports its path

    def test_a_data_uri(self):
        data, mime, path = resolve_source(to_data_uri(PNG, "image/png"))
        assert data == PNG and mime == "image/png"
        assert path is None            # never was a file

    def test_bare_base64(self):
        data, mime, path = resolve_source(base64.b64encode(GIF).decode())
        assert data == GIF and mime == "image/gif"
        assert path is None

    def test_a_file_wins_over_a_base64_reading_of_its_name(self, tmp_path):
        """A filename made only of base64-legal characters is still a file."""
        path = tmp_path / "abcdefghijklmnopqrstuvwxyz"
        path.write_bytes(PNG)
        _, _, resolved = resolve_source(str(path))
        assert resolved == str(path)

    def test_empty_is_a_helpful_error(self):
        with pytest.raises(ValueError, match="no image given"):
            resolve_source("   ")

    def test_a_missing_file_says_so(self):
        with pytest.raises(FileNotFoundError, match="not found"):
            resolve_source("/nope/absent.png")

    def test_base64_of_something_that_is_not_an_image_is_rejected(self):
        packed = base64.b64encode(b"this is a text file, not a picture").decode()
        with pytest.raises(ValueError, match="not into a recognised image"):
            resolve_source(packed)

    def test_a_broken_data_uri_says_so(self):
        with pytest.raises(ValueError, match="data: URI"):
            resolve_source("data:image/png;base64,!!!not base64!!!")


class TestToDataUri:
    def test_is_what_a_browser_expects(self):
        uri = to_data_uri(PNG, "image/png")
        assert uri.startswith("data:image/png;base64,")
        assert base64.b64decode(uri.split(",", 1)[1]) == PNG
