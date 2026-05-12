"""Unit tests for core.tts_engine.TTSEngine."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def audio_dir(tmp_path: Path) -> Path:
    return tmp_path / "audio"


def _make_engine(audio_dir: Path, **kwargs):
    """Create a TTSEngine with gTTS mocked out at module level."""
    from core.tts_engine import TTSEngine

    with patch("core.tts_engine.gTTS") as mock_cls:
        mock_cls.return_value = MagicMock()
        engine = TTSEngine(audio_dir=str(audio_dir), **kwargs)

    # Keep the mock reachable for post-construction assertions
    engine.__mock_gtts__ = mock_cls  # type: ignore[attr-defined]
    return engine, mock_cls


class TestInit:
    def test_is_available_with_gtts(self, audio_dir: Path) -> None:
        engine, _ = _make_engine(audio_dir)
        assert engine.is_available is True
        assert engine._backend == "gtts"

    def test_unavailable_when_both_backends_missing(self, audio_dir: Path) -> None:
        from core.tts_engine import TTSEngine

        with (
            patch("core.tts_engine.gTTS", None),
            patch("core.tts_engine.pyttsx3", None),
        ):
            engine = TTSEngine(audio_dir=str(audio_dir))

        assert engine.is_available is False
        assert engine._backend is None

    def test_audio_directory_created(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "audio"
        assert not nested.exists()
        engine, _ = _make_engine(nested)
        assert nested.exists()


class TestSynthesize:
    def test_returns_mp3_filename(self, audio_dir: Path) -> None:
        engine, _ = _make_engine(audio_dir)
        with patch("core.tts_engine.gTTS") as mock_cls:
            mock_cls.return_value = MagicMock()
            engine._backend = "gtts"
            result = engine.synthesize("hello")
        assert result is not None
        assert result.endswith(".mp3")

    def test_passes_lang_to_gtts(self, audio_dir: Path) -> None:
        engine, _ = _make_engine(audio_dir)
        with patch("core.tts_engine.gTTS") as mock_cls:
            mock_cls.return_value = MagicMock()
            engine._backend = "gtts"
            engine.synthesize("bonjour", lang="fr")
        mock_cls.assert_called_once_with(text="bonjour", lang="fr")

    def test_defaults_lang_to_en(self, audio_dir: Path) -> None:
        engine, _ = _make_engine(audio_dir)
        with patch("core.tts_engine.gTTS") as mock_cls:
            mock_cls.return_value = MagicMock()
            engine._backend = "gtts"
            engine.synthesize("hello")
        mock_cls.assert_called_once_with(text="hello", lang="en")

    def test_empty_text_raises_value_error(self, audio_dir: Path) -> None:
        engine, _ = _make_engine(audio_dir)
        with pytest.raises(ValueError, match="empty"):
            engine.synthesize("")

    def test_whitespace_only_raises_value_error(self, audio_dir: Path) -> None:
        engine, _ = _make_engine(audio_dir)
        with pytest.raises(ValueError):
            engine.synthesize("   ")

    def test_unavailable_engine_returns_none(self, audio_dir: Path) -> None:
        from core.tts_engine import TTSEngine

        with (
            patch("core.tts_engine.gTTS", None),
            patch("core.tts_engine.pyttsx3", None),
        ):
            engine = TTSEngine(audio_dir=str(audio_dir))

        result = engine.synthesize("hello")
        assert result is None


class TestCache:
    def test_same_text_same_lang_returns_cached_filename(self, audio_dir: Path) -> None:
        engine, _ = _make_engine(audio_dir)
        with patch("core.tts_engine.gTTS") as mock_cls:
            mock_cls.return_value = MagicMock()
            engine._backend = "gtts"
            r1 = engine.synthesize("hello")
            r2 = engine.synthesize("hello")
        # gTTS should only be called once (second call hits cache)
        assert r1 == r2
        assert mock_cls.call_count == 1

    def test_different_lang_produces_different_filename(self, audio_dir: Path) -> None:
        engine, _ = _make_engine(audio_dir)
        with patch("core.tts_engine.gTTS") as mock_cls:
            mock_cls.return_value = MagicMock()
            engine._backend = "gtts"
            r_en = engine.synthesize("hello", lang="en")
            r_fr = engine.synthesize("hello", lang="fr")
        assert r_en != r_fr
        assert mock_cls.call_count == 2

    def test_expired_cache_triggers_new_synthesis(self, audio_dir: Path) -> None:
        engine, _ = _make_engine(audio_dir, cache_ttl_seconds=0)
        with patch("core.tts_engine.gTTS") as mock_cls, \
             patch("core.tts_engine.time") as mock_time:
            mock_cls.return_value = MagicMock()
            engine._backend = "gtts"
            mock_time.time.side_effect = [0.0, 1.0, 2.0, 3.0]
            engine.synthesize("hello")
            engine.synthesize("hello")  # cache TTL=0, should re-synthesise
        assert mock_cls.call_count == 2
