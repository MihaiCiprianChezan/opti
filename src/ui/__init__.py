"""
UI module — re-exports Energy Star components from the existing energy/ package.
This keeps the original code in place while providing a clean v2 import path.
"""
from energy.star import Star as EnergyStar
from energy.colors import Colors, Color
from energy.media_player import VideoPlayer, GifPlayer
from energy.media_effect import VideoMediaEffect, GifMediaEffect
from energy.color_overlay import ColorOverlayWidget
from energy.draggable_widget import DraggableWidget
