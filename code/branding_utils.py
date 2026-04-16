"""
Branding utilities for video rendering.
Handles intro cards, watermarks, stem icons, and image resizing for video clips.

Section 2: Branding Requirements
- SGS/SGS2 watermarks on all channels
- Stem icons (Acapella, Drums, Bass, Melody, Instrumental) top-right
- Consistent branding across all channels
"""

from typing import Optional, Union
from pathlib import Path
import os

try:
    from moviepy import ColorClip, CompositeVideoClip, ImageClip, TextClip
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False
    ColorClip = CompositeVideoClip = ImageClip = TextClip = None

# Section 2: Branding asset paths (using existing assets structure)
BRANDING_ASSETS_DIR = Path("assets")
ICONS_DIR = BRANDING_ASSETS_DIR / "assets" / "icons"
LABELS_DIR = BRANDING_ASSETS_DIR / "assets" / "label"

# Watermark/label paths - map channels to label files
# Updated to use correct watermarks for each channel:
# - Main channel: SGS (sgs.png)
# - Backup channel: SGS 2 (sgs_2.png)
# - Acapella channel: Son Got Acapellas (son_got_acappellas.png)
# - Drum channel: Son Got Drums (son_got_drums.png)
# - Sample Split channel: Sample Split (sample_split.png)
WATERMARK_PATHS = {
    # Main channel variations - uses SGS watermark
    "main": LABELS_DIR / "sgs.png",
    "main_channel": LABELS_DIR / "sgs.png",
    "mainchannel": LABELS_DIR / "sgs.png",
    
    # Backup/SGS2 channel - uses SGS 2 watermark
    "back up": LABELS_DIR / "sgs_2.png",
    "backup": LABELS_DIR / "sgs_2.png",
    "sgs_2": LABELS_DIR / "sgs_2.png",
    "sgs 2": LABELS_DIR / "sgs_2.png",
    
    # Drums channel - uses Son Got Drums watermark
    "drum": LABELS_DIR / "son_got_drums.png",
    "drums": LABELS_DIR / "son_got_drums.png",
    "son_got_drums": LABELS_DIR / "son_got_drums.png",
    "songotdrums": LABELS_DIR / "son_got_drums.png",
    
    # Vocal/Acapella channel - uses Son Got Acapellas watermark
    "vocal": LABELS_DIR / "son_got_acappellas.png",
    "vocals": LABELS_DIR / "son_got_acappellas.png",
    "son_got_acapellas": LABELS_DIR / "son_got_acappellas.png",
    "son_got_acappellas": LABELS_DIR / "son_got_acappellas.png",
    "songotacapellas": LABELS_DIR / "son_got_acappellas.png",
    
    # Sample Split channel - uses Sample Split watermark
    "sample split": LABELS_DIR / "sample_split.png",
    "sample_split": LABELS_DIR / "sample_split.png",
    "samplesplit": LABELS_DIR / "sample_split.png",
    
    # TikTok channel - uses TikTok watermark
    "tiktok": LABELS_DIR / "tik_tok.png",
    "tiktok_channel": LABELS_DIR / "tik_tok.png",
    "tik tok": LABELS_DIR / "tik_tok.png",
    "tiktokchannel": LABELS_DIR / "tik_tok.png",
}

# Stem icon paths - map stem types to icon files
STEM_ICONS = {
    "acapella": ICONS_DIR / "acapella.png",
    "drums": ICONS_DIR / "drums.png",
    "bass": ICONS_DIR / "bass.png",
    "melody": ICONS_DIR / "melody.png",
    "instrumental": ICONS_DIR / "instrumental.png",
}


WATERMARK_CONFIG = {
    "Main": {"text": "SGS", "opacity": 0.8, "font_size": 60},
    "Back Up": {"text": "SGS2", "opacity": 0.8, "font_size": 60},
    "Drum": {"text": "SGS", "opacity": 0.8, "font_size": 60},
    "Vocal": {"text": "SGS", "opacity": 0.8, "font_size": 60},
    "Sample Split": {"text": "SGS", "opacity": 0.8, "font_size": 60},
    "Tik Tok": {"text": "SGS", "opacity": 0.8, "font_size": 60},
}


def apply_moviepy_resize(clip, new_size=None, *args, **kwargs):
    """
    Resize a moviepy clip.
    
    Args:
        clip: MoviePy clip to resize
        new_size: Tuple of (width, height) or None
        *args, **kwargs: Additional arguments for resized
        
    Returns:
        Resized clip
    """
    if not MOVIEPY_AVAILABLE or clip is None:
        return clip
    
    if new_size:
        return clip.resized(new_size)
    elif args or kwargs:
        return clip.resized(*args, **kwargs)
    return clip


def _get_watermark_path(channel: str) -> Optional[Path]:
    """
    Section 2: Get watermark/label path based on channel.
    Maps channel names to label files in assets/assets/label/
    Main channel uses sgs_2.png (Section 2: reuse SGS2 asset, remove '2' and replace with 'SGS').
    """
    channel_lower = channel.lower().strip()
    
    # Try direct lookup first
    if channel_lower in WATERMARK_PATHS:
        path = WATERMARK_PATHS[channel_lower]
        if path.exists():
            return path
    
    # Try partial matches for channel names
    for key, path in WATERMARK_PATHS.items():
        if key in channel_lower or channel_lower in key:
            if path.exists():
                return path
    
    # Fallback: try common patterns
    if "main" in channel_lower:
        fallback = LABELS_DIR / "sgs.png"
        if fallback.exists():
            return fallback
        # If sgs.png doesn't exist, try sgs_2.png as backup
        fallback = LABELS_DIR / "sgs_2.png"
        if fallback.exists():
            return fallback
    
    return None

def _get_stem_icon_path(stem_type: str) -> Optional[Path]:
    """Section 2: Get stem icon path for top-right placement."""
    stem_key = stem_type.lower()
    icon_path = STEM_ICONS.get(stem_key)
    if icon_path and icon_path.exists():
        return icon_path
    return None

def add_watermark(clip, channel: str, duration: float) -> Optional["CompositeVideoClip"]:
    """
    Section 2: Add SGS/SGS2 watermark to video clip.
    Watermark appears on ALL channels and ALL uploads.
    """
    if not MOVIEPY_AVAILABLE:
        return None
    
    watermark_path = _get_watermark_path(channel)
    if not watermark_path:
        # Only warn once per channel to avoid spam
        if not hasattr(add_watermark, '_warned_channels'):
            add_watermark._warned_channels = set()
        if channel not in add_watermark._warned_channels:
            print(f"⚠️ Watermark not found for channel: {channel}")
            print(f"   Add watermark to: assets/sgs2_watermark.png (required) or assets/sgs_watermark.png (optional)")
            print(f"   See assets/README.md for details")
            add_watermark._warned_channels.add(channel)
        return None
    
    try:
        watermark = ImageClip(str(watermark_path)).with_duration(duration)
        
        # Resize watermark while preserving aspect ratio to avoid distortion
        # Target width: 200px, height will scale proportionally
        # But cap height at 80px to ensure it fits nicely
        target_width = 200
        max_height = 80
        
        # Calculate aspect ratio-preserving size
        original_w, original_h = watermark.w, watermark.h
        aspect_ratio = original_w / original_h
        
        # Calculate new dimensions
        if original_w > original_h:
            # Landscape: use width as base
            new_width = min(target_width, original_w)
            new_height = int(new_width / aspect_ratio)
            if new_height > max_height:
                new_height = max_height
                new_width = int(new_height * aspect_ratio)
        else:
            # Portrait or square: use height as base
            new_height = min(max_height, original_h)
            new_width = int(new_height * aspect_ratio)
            if new_width > target_width:
                new_width = target_width
                new_height = int(new_width / aspect_ratio)
        
        watermark = apply_moviepy_resize(watermark, new_size=(new_width, new_height))
        
        # Position: bottom-left with margin (20px from edges) - matches reference image
        # Calculate position: (margin_x, height - watermark_height - margin_y)
        margin_x, margin_y = 20, 20
        watermark = watermark.with_position((margin_x, clip.h - watermark.h - margin_y))
        
        return CompositeVideoClip([clip, watermark])
    except Exception as e:
        print(f"Warning: Could not add watermark: {e}")
        return None

def add_stem_icon(clip, stem_type: str, duration: float) -> Optional["CompositeVideoClip"]:
    """
    Section 2: Add stem icon to top-right of video.
    Five icons: Acapella, Drums, Bass, Melody, Instrumental.
    Must appear top-right consistently.
    """
    if not MOVIEPY_AVAILABLE:
        return None
    
    icon_path = _get_stem_icon_path(stem_type)
    if not icon_path:
        # Only warn once per stem type to avoid spam
        if not hasattr(add_stem_icon, '_warned_stems'):
            add_stem_icon._warned_stems = set()
        if stem_type not in add_stem_icon._warned_stems:
            print(f"⚠️ Stem icon not found for: {stem_type}")
            print(f"   Add icon to: assets/icon_{stem_type.lower()}.png")
            print(f"   See assets/README.md for details")
            add_stem_icon._warned_stems.add(stem_type)
        return None
    
    try:
        icon = ImageClip(str(icon_path)).with_duration(duration)
        # Resize icon (adjust size as needed)
        icon = apply_moviepy_resize(icon, new_size=(80, 80))
        # Position: top-right with margin (20px from edges)
        margin_x, margin_y = 20, 20
        icon = icon.with_position((clip.w - icon.w - margin_x, margin_y))
        
        return CompositeVideoClip([clip, icon])
    except Exception as e:
        print(f"Warning: Could not add stem icon: {e}")
        return None

def add_intro_card(duration: float, channel: str, thumb_path: Optional[str] = None, stem_type: str = "") -> Optional[Union["CompositeVideoClip", "ColorClip"]]:
    """
    Create an intro card for videos with branding.
    Section 2: Includes watermark and stem icon.
    
    Args:
        duration: Duration of the video in seconds
        channel: Channel name
        thumb_path: Optional path to thumbnail image
        stem_type: Type of stem (e.g., "Acapella", "Drums")
        
    Returns:
        MoviePy clip with intro card, watermark, and stem icon, or None if moviepy unavailable
    """
    if not MOVIEPY_AVAILABLE:
        return None
    
    try:
        # Create background
        background = ColorClip(
            size=(1280, 720),
            color=(0, 0, 0),
            duration=duration
        )
        
        clips = [background]
        
        # Add thumbnail if available
        if thumb_path and os.path.exists(thumb_path):
            try:
                thumb_clip = ImageClip(thumb_path).with_duration(duration)
                thumb_clip = apply_moviepy_resize(thumb_clip, new_size=(720, 720))
                thumb_clip = thumb_clip.with_position("center")
                clips.append(thumb_clip)
            except Exception as e:
                print(f"Warning: Could not add thumbnail to intro card: {e}")
        
        # Composite base clip
        base_clip = CompositeVideoClip(clips, size=(1280, 720))
        
        # Section 2: Add watermark (on ALL channels)
        watermarked = add_watermark(base_clip, channel, duration)
        if watermarked:
            base_clip = watermarked
        
        # Section 2: Add stem icon (top-right)
        if stem_type:
            iconed = add_stem_icon(base_clip, stem_type, duration)
            if iconed:
                base_clip = iconed
        
        return base_clip
        
    except Exception as e:
        print(f"Warning: Could not create intro card: {e}")
        return None



