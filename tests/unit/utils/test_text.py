"""Tests for text utility functions."""

from sebco_qa_engine.utils.text import strip_ansi


class TestStripAnsi:
    def test_strips_color_codes(self):
        assert strip_ansi("\x1b[32mhello\x1b[0m world") == "hello world"

    def test_strips_bold(self):
        assert strip_ansi("\x1b[1mbold\x1b[22m") == "bold"

    def test_no_escapes_unchanged(self):
        assert strip_ansi("no escapes here") == "no escapes here"

    def test_empty_string(self):
        assert strip_ansi("") == ""

    def test_only_escape_sequence(self):
        assert strip_ansi("\x1b[0m") == ""

    def test_mutmut_progress_bar_style(self):
        # mutmut outputs lines like: "\x1b[2K\x1b[1A🎉  42 🙁  3"
        raw = "\x1b[2K\x1b[1A\U0001f389  42 \U0001f641  3"
        result = strip_ansi(raw)
        assert "\x1b" not in result
        assert "42" in result
        assert "3" in result

    def test_multiple_sequences_in_one_line(self):
        text = "\x1b[31mred\x1b[0m \x1b[34mblue\x1b[0m"
        assert strip_ansi(text) == "red blue"

    def test_preserves_newlines(self):
        text = "\x1b[32mline1\x1b[0m\nline2"
        assert strip_ansi(text) == "line1\nline2"
