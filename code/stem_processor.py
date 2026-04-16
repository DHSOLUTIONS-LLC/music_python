"""
Advanced stem processing module for Sample Split.

Handles stem mixing, loudness normalization, and consistency validation.
Uses htdemucs_ft model for high-quality separation with improved 'other' stem.

Stem mapping:
  - Acapella → vocals.mp3
  - Drums → drums.mp3
  - Bass → bass.mp3
  - Melody → other.mp3
  - Instrumental → other + drums + bass (combined mix)
"""

import os
import logging
from pathlib import Path
from typing import Optional, List, Dict
from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError

logger = logging.getLogger(__name__)


class StemProcessor:
    """Process and combine stems with loudness normalization."""

    DEFAULT_TARGET_DBFS = -1.0
    TARGET_LUFS = -14.0

    @staticmethod
    def load_audio(path: str) -> Optional[AudioSegment]:
        """Load audio file safely."""
        try:
            if not os.path.exists(path):
                logger.warning(f"Audio file not found: {path}")
                return None
            return AudioSegment.from_file(path)
        except CouldntDecodeError as e:
            logger.error(f"Failed to decode audio {path}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to load audio {path}: {e}")
            return None

    @staticmethod
    def normalize_loudness(audio: AudioSegment, target_dbfs: float = DEFAULT_TARGET_DBFS) -> AudioSegment:
        """Normalize audio to target loudness level."""
        if not audio:
            return audio

        peak = audio.max_dBFS
        if peak > target_dbfs:
            gain_adjustment = target_dbfs - peak
            audio = audio.apply_gain(gain_adjustment)
            logger.debug(f"Applied {gain_adjustment:.2f}dB gain adjustment")
        return audio

    @staticmethod
    def standardize_audio(audio: AudioSegment, channels: int = 2, frame_rate: int = 44100) -> AudioSegment:
        """Standardize audio format (channels and sample rate)."""
        if audio.channels != channels:
            audio = audio.set_channels(channels)
        if audio.frame_rate != frame_rate:
            audio = audio.set_frame_rate(frame_rate)
        return audio

    @classmethod
    def mix_stems(
        cls,
        stem_paths: List[str],
        target_loudness: float = DEFAULT_TARGET_DBFS,
        apply_fade: bool = False
    ) -> Optional[AudioSegment]:
        """
        Mix multiple stems into one audio file.

        Args:
            stem_paths: List of paths to MP3 files to mix
            target_loudness: Target loudness in dBFS
            apply_fade: Whether to apply fade-in/out (useful for smooth transitions)

        Returns:
            Mixed AudioSegment or None if mixing fails
        """
        if not stem_paths:
            logger.error("No stem paths provided for mixing")
            return None

        # Load and standardize all stems
        stems = []
        for path in stem_paths:
            audio = cls.load_audio(path)
            if audio is None:
                logger.warning(f"Skipping unavailable stem: {path}")
                continue

            # Standardize format and reduce clipping headroom
            audio = cls.standardize_audio(audio)
            audio = audio - 2.0  # Reduce each stem by 2dB before mixing to prevent clipping
            stems.append(audio)

        if not stems:
            logger.error("No stems successfully loaded for mixing")
            return None

        # Mix stems by overlaying them
        mixed = stems[0]
        for stem in stems[1:]:
            mixed = mixed.overlay(stem)

        # Apply loudness normalization to final mix
        mixed = cls.normalize_loudness(mixed, target_loudness)

        if apply_fade:
            fade_duration = 500  # 0.5 seconds
            mixed = mixed.fade_in(fade_duration).fade_out(fade_duration)

        logger.info(f"Mixed {len(stems)} stems successfully")
        return mixed

    @classmethod
    def get_instrumental(cls, stem_base_path: str, apply_normalization: bool = True) -> Optional[AudioSegment]:
        """
        Generate instrumental by combining: other + drums + bass.

        Args:
            stem_base_path: Directory containing separated stems
            apply_normalization: Whether to normalize loudness

        Returns:
            Mixed instrumental AudioSegment or None if unavailable
        """
        stem_files = {
            "other": os.path.join(stem_base_path, "other.mp3"),
            "drums": os.path.join(stem_base_path, "drums.mp3"),
            "bass": os.path.join(stem_base_path, "bass.mp3"),
        }

        # Verify all required stems exist
        missing = [name for name, path in stem_files.items() if not os.path.exists(path)]
        if missing:
            logger.error(f"Cannot create instrumental - missing stems: {missing}")
            return None

        # Mix with proper loudness handling
        stem_paths = [stem_files["other"], stem_files["drums"], stem_files["bass"]]
        instrumental = cls.mix_stems(stem_paths, apply_fade=True)

        if instrumental and apply_normalization:
            instrumental = cls.normalize_loudness(instrumental)

        return instrumental

    @classmethod
    def export_stem(
        cls,
        audio: AudioSegment,
        output_path: str,
        format: str = "mp3",
        bitrate: str = "192k"
    ) -> bool:
        """
        Export audio to file with specified parameters.

        Args:
            audio: AudioSegment to export
            output_path: Target file path
            format: Export format (mp3, wav, etc.)
            bitrate: Bitrate for mp3 (e.g., '192k', '320k')

        Returns:
            True if export successful, False otherwise
        """
        try:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

            export_kwargs = {"format": format}
            if format == "mp3":
                export_kwargs["bitrate"] = bitrate

            audio.export(output_path, **export_kwargs)
            logger.info(f"Exported stem to {output_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to export stem to {output_path}: {e}")
            return False

    @staticmethod
    def validate_stems(stem_base_path: str) -> Dict[str, bool]:
        """
        Validate all required stems exist and are readable.

        Returns:
            Dict with stem names as keys and validation status as values
        """
        required_stems = ["vocals.mp3", "drums.mp3", "bass.mp3", "other.mp3"]
        validation = {}

        for stem in required_stems:
            path = os.path.join(stem_base_path, stem)
            if os.path.exists(path) and os.path.getsize(path) > 100_000:  # At least 100KB
                validation[stem] = True
            else:
                validation[stem] = False

        return validation

    @staticmethod
    def get_stem_duration(path: str) -> Optional[float]:
        """Get audio duration in seconds."""
        try:
            audio = AudioSegment.from_file(path)
            return len(audio) / 1000.0
        except Exception as e:
            logger.error(f"Failed to get duration for {path}: {e}")
            return None

    @staticmethod
    def ensure_consistent_length(stem_paths: List[str], tolerance_ms: int = 100) -> bool:
        """
        Check that all stems have consistent duration (within tolerance).

        Returns:
            True if all stems have consistent length, False otherwise
        """
        if not stem_paths:
            return True

        try:
            durations = []
            for path in stem_paths:
                audio = AudioSegment.from_file(path)
                durations.append(len(audio))

            max_duration = max(durations)
            min_duration = min(durations)
            diff = max_duration - min_duration

            if diff <= tolerance_ms:
                logger.info(f"Stem lengths consistent (max diff: {diff}ms)")
                return True
            else:
                logger.warning(f"Stem length variance: {diff}ms (tolerance: {tolerance_ms}ms)")
                return False
        except Exception as e:
            logger.error(f"Failed to validate stem lengths: {e}")
            return False
