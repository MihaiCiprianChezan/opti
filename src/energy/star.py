import logging
import os
import sys
from pathlib import Path

from energy.media_effect import DEFAULT_DURATION

os.environ["FFMPEG_LOGLEVEL"] = "quiet"

from PySide6.QtCore import QCoreApplication, QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QVBoxLayout

from utils.app_logger import AppLogger
from energy.color_overlay import ColorOverlayWidget
from energy.draggable_widget import DraggableWidget
from energy.media_player import VideoPlayer


class Star(DraggableWidget):
    """
    A customizable animated widget that displays media vide in a circular area.

    Features:
    - Supports video files (MP4, AVI, MOV, etc.)
    - Colorization capabilities to change the appearance of the animation
    - Playback speed control for avatar
    - Maintains a circular shape for both media types
    - Draggable interface with right-click context menu
    - Keyboard shortcuts for color changes and playback control

    Usage examples:
    - For video files: EnergyBall("./avatar/animation.mp4")

    Keyboard controls:
    - 1-8: Change colors
    - Space: Reset color
    - +/-: Increase/decrease playback speed
    - 0: Reset playback speed to normal
    - Page Up/Down: Zoom in/out
    - Home: Reset zoom to 1.0x
    - Mouse Wheel: Zoom in/out
    - Escape: Exit

    Commands (via receive_command method):
    - "change_color": Change the color overlay (params: {"color": (r, g, b)})
    - "reset_colorized": Remove color overlay
    - "set_playback_rate": Change playback speed (params: {"rate": float})
    - "set_media_source": Change media source (params: {"path": "path/to/media"})
    - "zoom_in": Zoom in by one step
    - "zoom_out": Zoom out by one step
    - "reset_zoom": Reset zoom to 1.0x
    - "set_zoom": Set specific zoom scale (params: {"scale": float})
    """

    __slots__ = (
        "name",
        "logger",
        "circle_color",
        "use_hardware_acceleration",
        "media_player",
        "media_path",
        "color_overlay",
        "_cached_mask",
        "_last_size",
        "_current_overlay_color",
        "_zoom_scale",
        "_original_size",
        "_min_size",
        "_max_size",
        "_zoom_step",
        "_zoom_timer",
        "_pending_zoom_scale",
        "_is_zooming",
        "_suppress_paint_events",
        "_render_buffer",
    )

    def __init__(self, media_path=f"{Path(__file__).parent}/avatar/opti500.mp4", use_hardware_acceleration=True):
        """
        Initialize the EnergyBall widget.
        """
        super().__init__()
        self.name = self.__class__.__name__
        self.logger = AppLogger(name=self.__class__.__name__, log_level=logging.DEBUG)
        self.circle_color = QColor(0, 0, 0, 180)  # Semi-transparent black
        self._current_overlay_color = QColor(0, 0, 0, 0)  # Fully transparent black'
        self._cached_mask = None
        self._last_size = None

        # Zoom functionality attributes
        self._zoom_scale = 1.0  # Current zoom scale factor
        self._original_size = 0  # Original media size
        self._min_size = 30  # Minimum widget size in pixels
        self._max_size = 500  # Maximum widget size in pixels
        self._zoom_step = 0.03  # Smaller zoom increment for smoother scaling
        self._pending_zoom_scale = None  # Pending zoom scale for batched updates
        self._is_zooming = False  # Flag to prevent recursive zoom operations
        self._suppress_paint_events = False  # Flag to suppress paint events during zoom
        self._render_buffer = None  # Buffer for smooth rendering during transitions

        # Timer for batched zoom updates to eliminate flickering
        self._zoom_timer = QTimer()
        self._zoom_timer.setSingleShot(True)
        self._zoom_timer.timeout.connect(self._apply_pending_zoom)
        self._zoom_timer.setInterval(22)  # ~60 FPS update rate

        self.use_hardware_acceleration = use_hardware_acceleration
        self.logger.info(
            f"🌟 Energy Star initialized with {'GPU' if use_hardware_acceleration else 'SOFTWARE'} acceleration"
        )
        self.media_player = None
        self.media_path = None
        self.set_media_source(media_path)
        self.color_overlay = ColorOverlayWidget(self)
        self.color_overlay.hide()  # Hide initially
        self.color_overlay.raise_()
        self.init_position(self.media_player.get_original_size())

    def _detect_media_type(self, file_path):
        """
        Detect the type of media file based on its extension.
        """
        _, ext = os.path.splitext(file_path.lower())
        if ext in [".mp4", ".avi", ".mov", ".mkv", ".wmv"]:
            return "video"
        else:
            self.logger.warning(f"Unsupported file type: {ext}. Defaulting to MP¤ mode.")
            return ".mp4"

    def set_media_source(self, media_path):
        """Change the media source dynamically."""
        if self.media_player:
            self.media_player.cleanup_resources()
        media_type = self._detect_media_type(media_path)
        self.media_player = VideoPlayer(self, use_hardware_acceleration=self.use_hardware_acceleration)
        self.media_player.load_media(media_path)
        self.media_player.play()
        original_size = self.media_player.get_original_size()
        if self.media_player.get_media_widget():
            media_widget = self.media_player.get_media_widget()
            self._configure_media_widget_scaling(media_widget)
            media_widget.setParent(self)
            media_widget.setGeometry(0, 0, self.width(), self.height())
            media_widget.show()
            if hasattr(self.media_player, "overlay_widget") and self.media_player.overlay_widget:
                overlay = self.media_player.overlay_widget
                overlay.setParent(self)
                overlay.setGeometry(0, 0, self.width(), self.height())
                overlay.show()
        self._original_size = original_size
        self._apply_zoom_scale()
        self.media_path = media_path
        self.update()
        self.logger.debug(f"Set media source to {media_path}")

    def set_playback_rate(self, rate):
        """Set the playback speed for the animation or video."""
        if self.media_player:
            self.media_player.set_playback_rate(rate)

    def wheelEvent(self, event):
        """Handle mouse wheel events for zooming functionality with flicker-free batched updates."""
        if self._is_zooming:
            event.accept()
            return
        delta = event.angleDelta().y()
        zoom_multiplier = abs(delta) / 120.0
        effective_zoom_step = self._zoom_step * zoom_multiplier
        if delta > 0:
            new_scale = min(self._zoom_scale + effective_zoom_step, self._get_max_zoom_scale())
        else:
            new_scale = max(self._zoom_scale - effective_zoom_step, self._get_min_zoom_scale())
        if abs(new_scale - self._zoom_scale) > 0.01:
            self._zoom_scale = new_scale
            self._apply_zoom_scale()
        event.accept()

    def _get_min_zoom_scale(self):
        """Calculate minimum zoom scale based on minimum size constraint."""
        if not self._original_size:
            return 0.5
        min_dimension = min(self._original_size)
        return max(0.3, self._min_size / min_dimension)

    def _get_max_zoom_scale(self):
        """Calculate maximum zoom scale based on maximum size constraint."""
        if not self._original_size:
            return 3.0
        max_dimension = max(self._original_size)
        return min(5.0, self._max_size / max_dimension)

    def _apply_zoom_scale(self):
        """Apply the current zoom scale to the widget."""
        if not self._original_size or self._is_zooming:
            return
        self._pending_zoom_scale = self._zoom_scale
        self._zoom_timer.start()

        # self.logger.debug(f"Scheduled zoom scale {self._zoom_scale:.2f}x")

    def _update_overlay_position_immediately(self):
        """Update overlay position immediately during scroll events to prevent desync."""
        if hasattr(self, "color_overlay") and self.color_overlay and self.color_overlay.isVisible():
            global_pos = self.mapToGlobal(self.rect().topLeft())
            current_size = self.color_overlay.size()
            self.color_overlay.setGeometry(global_pos.x(), global_pos.y(), current_size.width(), current_size.height())

    def _hide_all_widgets(self):
        """Hide all widgets and return their visibility states."""
        visibility_states = {'main': self.isVisible()}
        if self.isVisible():
            self.hide()
        if self.media_player and self.media_player.get_media_widget():
            media_widget = self.media_player.get_media_widget()
            visibility_states['media'] = media_widget.isVisible()
            media_widget.hide()
            if hasattr(self.media_player, "overlay_widget") and self.media_player.overlay_widget:
                overlay = self.media_player.overlay_widget
                visibility_states['video_overlay'] = overlay.isVisible()
                overlay.hide()
        if hasattr(self, "color_overlay") and self.color_overlay:
            visibility_states['color_overlay'] = self.color_overlay.isVisible()
            self.color_overlay.hide()
        return visibility_states

    def _restore_widget_visibility(self, visibility_states):
        """Restore widget visibility from saved states."""
        # Restore main widget visibility FIRST
        if visibility_states.get('main', False):
            self.show()
        if self.media_player and self.media_player.get_media_widget():
            media_widget = self.media_player.get_media_widget()
            if visibility_states.get('media', False):
                media_widget.show()
                media_widget.raise_()
            if hasattr(self.media_player, "overlay_widget") and self.media_player.overlay_widget:
                overlay = self.media_player.overlay_widget
                if visibility_states.get('video_overlay', False):
                    overlay.show()
                    overlay.raise_()
        if hasattr(self, "color_overlay") and self.color_overlay:
            if visibility_states.get('color_overlay', False):
                self.color_overlay.show()
                self.color_overlay.raise_()

    def _sync_overlay_geometry(self):
        """Synchronize overlay geometry with main widget - CLEAN PATTERN."""
        if not hasattr(self, "color_overlay") or not self.color_overlay:
            return
        QApplication.processEvents()
        global_pos = self.mapToGlobal(self.rect().topLeft())
        self.color_overlay.setGeometry(global_pos.x(), global_pos.y(), self.width(), self.height())
        if self.mask():
            self.color_overlay.setMask(self.mask())

    def _update_widget_geometry(self, width, height, center):
        """Update main widget geometry - CLEAN PATTERN."""
        self.setFixedSize(QSize(width, height))
        new_rect = self.geometry()
        new_rect.moveCenter(center)
        self.setGeometry(new_rect)

    def _update_media_geometry(self, width, height):
        """Update media widget geometry - CLEAN PATTERN."""
        if not self.media_player:
            return
        media_widget = self.media_player.get_media_widget()
        if media_widget:
            media_widget.setGeometry(0, 0, width, height)
            media_widget.setFixedSize(width, height)
            if hasattr(media_widget, 'setScaledContents'):
                media_widget.setScaledContents(True)
        if hasattr(self.media_player, "overlay_widget") and self.media_player.overlay_widget:
            overlay = self.media_player.overlay_widget
            overlay.setGeometry(0, 0, width, height)
            overlay.setFixedSize(width, height)

    def _apply_pending_zoom(self):
        """Execute the pending zoom operation with complete flicker elimination."""
        if not self._original_size or self._pending_zoom_scale is None:
            return

        self._is_zooming = True
        new_width = int(self._original_size[0] * self._pending_zoom_scale)
        new_height = int(self._original_size[1] * self._pending_zoom_scale)
        current_center = self.geometry().center()
        self._suppress_paint_events = True

        # visibility_states = self._hide_all_widgets()
        # self._restore_widget_visibility(visibility_states)

        self.setUpdatesEnabled(False)
        # Assuming mediaplayer is a child of the widget and filling the entire parent
        self._update_widget_geometry(new_width, new_height, current_center)
        # self._update_media_geometry(new_width, new_height)
        self._cached_mask = None
        self._last_size = None
        new_mask = self._create_circle_mask()
        if self.media_player and self.media_player.get_media_widget():
            media_widget = self.media_player.get_media_widget()
            media_widget.setMask(new_mask)
            if hasattr(self.media_player, "overlay_widget") and self.media_player.overlay_widget:
                overlay = self.media_player.overlay_widget
                overlay.setMask(new_mask)
        self._suppress_paint_events = False
        self.setUpdatesEnabled(True)

        self._sync_overlay_geometry()
        if self.color_overlay.isVisible():
            if self.media_player and self.media_player.get_media_widget():
                media_widget = self.media_player.get_media_widget()
                if media_widget.isVisible():
                    media_widget.stackUnder(self.color_overlay)
            if hasattr(self.media_player, "overlay_widget") and self.media_player.overlay_widget:
                if self.media_player.overlay_widget.isVisible():
                    self.media_player.overlay_widget.stackUnder(self.color_overlay)
            self.color_overlay.raise_()

        self.update()
        self._pending_zoom_scale = None
        self._is_zooming = False

    def get_zoom_info(self):
        """Get current zoom information for debugging/display purposes."""
        return {
            "current_scale": self._zoom_scale,
            "min_scale": self._get_min_zoom_scale(),
            "max_scale": self._get_max_zoom_scale(),
            "current_size": (self.width(), self.height()),
            "original_size": self._original_size
        }

    def pause_playback(self):
        """
        Pause the video playback.
        """
        if self.media_player and isinstance(self.media_player, VideoPlayer):
            self.media_player.pause()
            # self.logger.debug(f"Paused video playback")
            return True
        return False

    def resume_playback(self):
        """
        Resume the video playback if it was paused.
        """
        if self.media_player and isinstance(self.media_player, VideoPlayer):
            self.media_player.resume()
            # self.logger.debug(f"Resumed video playback")
            return True
        return False

    def toggle_pause(self):
        """
        Toggle between pause and play states.
        """
        if self.media_player and isinstance(self.media_player, VideoPlayer):
            is_paused = self.media_player.toggle_pause()
            # self.logger.debug(f"Toggled pause state, is_paused: {is_paused}")
            return is_paused
        return False

    def is_paused(self):
        """
        Check if the video is currently paused.
        """
        if self.media_player and isinstance(self.media_player, VideoPlayer):
            return self.media_player.is_paused
        return False

    def set_colorized(self, color, duration=DEFAULT_DURATION):
        if not self.media_player or not self.color_overlay:
            return
        try:
            self.color_overlay.raise_()
            self._current_overlay_color = QColor(color)
            global_pos = self.mapToGlobal(self.rect().topLeft())
            self.color_overlay.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
            self.color_overlay.setGeometry(global_pos.x(), global_pos.y(), self.width(), self.height())
            if self.mask():
                self.color_overlay.setMask(self.mask())
            self.color_overlay.set_color(self._current_overlay_color, duration)
            self.color_overlay.show()
        except RuntimeError:
            pass  # Qt widget already deleted during shutdown

    def reset_colorized(self, command=None, _params=None, duration=DEFAULT_DURATION):
        """
        Reset the colorization color for the media with fade animation.
        """
        if not self.media_player or not self.color_overlay:
            return
        try:
            transparent_color = QColor(0, 0, 0, 0)
            self.color_overlay.set_color(transparent_color, duration)
            self.update()
        except RuntimeError:
            pass  # Qt widget already deleted during shutdown

    def _create_circle_mask(self, width=None, height=None):
        """Create and cache the circular mask with mathematically correct positioning"""
        # Use provided dimensions or current widget size
        if width is None or height is None:
            width, height = self.width(), self.height()

        current_size = (width, height)

        # Only recalculate if size has changed
        if self._cached_mask is None or current_size != self._last_size:
            # CORRECT MATH: Circle should fill the entire widget area
            # Use the smaller dimension as diameter, but center it properly in the widget
            diameter = min(width, height)
            radius = diameter // 2

            # Calculate the TOP-LEFT position to center the circle in the widget
            # For a circle to be centered: top_left = (widget_size - circle_size) / 2
            circle_x = (width - diameter) // 2
            circle_y = (height - diameter) // 2

            # COORDINATE ALIGNMENT FIX: Use QPainterPath for exact control
            path = QPainterPath()
            path.addEllipse(circle_x, circle_y, diameter, diameter)

            # Convert to region using the path (more predictable than QRegion.Ellipse)
            self._cached_mask = QRegion(path.toFillPolygon().toPolygon())
            self._last_size = current_size

            # self.logger.debug(f"Created CENTERED mask: {width}x{height}, diameter={diameter}, position=({circle_x}, {circle_y})")

            # Debug: Check actual mask bounds and detect coordinate misalignment
            actual_bounds = self._cached_mask.boundingRect()
            # self.logger.debug(f"Actual mask bounds: ({actual_bounds.x()}, {actual_bounds.y()}, {actual_bounds.width()}x{actual_bounds.height()})")

            # Check for coordinate misalignment
            x_offset = actual_bounds.x() - circle_x
            y_offset = actual_bounds.y() - circle_y
            if x_offset != 0 or y_offset != 0:
                # COORDINATE MISALIGNMENT DETECTED - CORRECTION: Adjust mask position to match expected coordinates
                if x_offset != 0 or y_offset != 0:
                    corrected_path = QPainterPath()
                    corrected_path.addEllipse(circle_x - x_offset, circle_y - y_offset, diameter, diameter)
                    self._cached_mask = QRegion(corrected_path.toFillPolygon().toPolygon())

                    corrected_bounds = self._cached_mask.boundingRect()
                    # self.logger.debug(f"CORRECTED mask bounds: ({corrected_bounds.x()}, {corrected_bounds.y()}, {corrected_bounds.width()}x{corrected_bounds.height()})")

        return self._cached_mask

    def _configure_media_widget_scaling(self, media_widget):
        """Configure proper content scaling for different media widget types."""
        from PySide6.QtMultimediaWidgets import QVideoWidget
        from PySide6.QtWidgets import QLabel

        if isinstance(media_widget, QVideoWidget):
            # For video widgets, try multiple approaches to ensure proper scaling
            try:
                # Try KeepAspectRatioByExpanding to fill the entire widget
                media_widget.setAspectRatioMode(Qt.KeepAspectRatioByExpanding)
                # self.logger.debug("Configured QVideoWidget with KeepAspectRatioByExpanding mode")
            except AttributeError:
                try:
                    # Fallback to IgnoreAspectRatio
                    media_widget.setAspectRatioMode(Qt.IgnoreAspectRatio)
                    # self.logger.debug("Configured QVideoWidget with IgnoreAspectRatio mode")
                except AttributeError:
                    # Final fallback
                    pass
                    # self.logger.debug("QVideoWidget aspect ratio mode not available")
        else:
            # Generic widget scaling attempt
            if hasattr(media_widget, 'setScaledContents'):
                media_widget.setScaledContents(True)
                # self.logger.debug(f"Configured {type(media_widget).__name__} with setScaledContents(True)")

    def _apply_colorization(self, painter, circle_rect):
        """Apply colorization effect to the widget efficiently"""
        # Check if we have the media player and its effect
        if hasattr(self.media_player, "media_effect") and self.media_player.media_effect:
            effect = self.media_player.media_effect
            if hasattr(effect, "current_color") and effect.current_color.alpha() > 0:
                color = effect.current_color
                color_path = QPainterPath()
                x, y, width, height = circle_rect
                color_path.addEllipse(x, y, width, height)
                painter.save()
                painter.setClipPath(color_path)
                painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
                painter.fillRect(self.rect(), color)
                painter.restore()

    def paintEvent(self, event):
        # Suppress paint events during zoom operations to prevent flickering
        if self._suppress_paint_events:
            return

        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform, True)

        # Calculate circle dimensions to match mask exactly using CORRECT math
        width, height = self.width(), self.height()
        diameter = min(width, height)

        # Calculate the TOP-LEFT position to center the circle (same as mask)
        circle_x = (width - diameter) // 2
        circle_y = (height - diameter) // 2

        # Create correctly positioned circle rectangle
        circle_rect = (circle_x, circle_y, diameter, diameter)

        # Draw background circle with exact same dimensions as mask
        painter.setBrush(self.circle_color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(*circle_rect)

        # Apply mask (only if needed)
        mask = self._create_circle_mask()
        if self.mask() != mask:
            self.setMask(mask)
            self._apply_mask_to_widgets(mask)

        # Draw border with same precision
        painter.setPen(QColor(50, 50, 50, 150))
        painter.drawEllipse(*circle_rect)

        # Apply colorization
        self._apply_colorization(painter, circle_rect)

    def receive_command(self, command, params):
        """
        Handle commands from external sources with improved performance.
        """
        command_handlers = {
            "reset_colorized": self.reset_colorized,
            "change_color": lambda cmd, p: self.handle_change_color(cmd, p),
            "set_playback_rate": lambda _, p: self.set_playback_rate(float(p.get("rate", 1.0))),
            "set_media_source": lambda _, p: (
                self.set_media_source(p.get("path")) if p.get("path") else self.logger.warning("No media path provided")
            ),
            "rectangle_selection": self.rectangle_selection,
            "rectangle_selection_timeout": self.rectangle_selection_timeout,
            "show_ball": lambda _, __: (self.show(), self.logger.debug("Showing energy ball")),
            "toggle_acceleration": lambda _, __: self.toggle_acceleration_mode(),
            "set_acceleration": lambda _, p: self.set_acceleration_mode(p.get("hardware", True)),
            "zoom_in": lambda _, __: self._handle_zoom_in(),
            "zoom_out": lambda _, __: self._handle_zoom_out(),
            "reset_zoom": lambda _, __: self._handle_reset_zoom(),
            "set_zoom": lambda _, p: self._handle_set_zoom(p.get("scale", 1.0)),
            "exit": lambda _, __: self.exit(),
        }
        handler = command_handlers.get(command)
        if handler:
            try:
                handler(command, params)
            except RuntimeError:
                pass  # Qt widget already deleted during shutdown
        else:
            self.logger.warning(f"Command not recognized: {command}")

    def _apply_mask_to_widgets(self, mask):
        """Apply mask to all child widgets with perfect synchronization"""
        # Apply to media widget
        if self.media_player and self.media_player.get_media_widget():
            media_widget = self.media_player.get_media_widget()

            # Ensure perfect geometry synchronization
            widget_width, widget_height = self.width(), self.height()
            target_geometry = (0, 0, widget_width, widget_height)

            # Always update geometry to ensure perfect alignment
            media_widget.setGeometry(*target_geometry)
            media_widget.setFixedSize(widget_width, widget_height)

            # Apply mask with exact dimensions
            media_widget.setMask(mask)

            # Configure content scaling based on widget type
            self._configure_media_widget_scaling(media_widget)

            if not media_widget.isVisible():
                media_widget.setVisible(True)
                media_widget.raise_()

            # self.logger.debug(f"Applied mask to media widget: {widget_width}x{widget_height}")

            # For video player, also apply to overlay with same precision
            if hasattr(self.media_player, "overlay_widget") and self.media_player.overlay_widget:
                overlay = self.media_player.overlay_widget

                # Perfect overlay synchronization
                overlay.setGeometry(*target_geometry)
                overlay.setFixedSize(widget_width, widget_height)
                overlay.setMask(mask)

                if not overlay.isVisible():
                    overlay.setVisible(True)
                    overlay.raise_()

                # self.logger.debug(f"Applied mask to overlay widget: {widget_width}x{widget_height}")

    def handle_change_color(self, command, params):
        """
        Handle the change_color command.
        """
        color = params.get("color", (0, 0, 0))
        if color == (0, 0, 0):
            self.reset_colorized(command, params)
        else:
            self.change_color(command, params)

    def change_color(self, command=None, params={}):
        """
        Change the color of the media.
        """
        color = params.get("color", (0, 0, 0))
        self.set_colorized(QColor(*color))

    def rectangle_selection(self, command, params={}):
        """
        Handle the rectangle_selection command.
        """
        rect = params.get("RectangleOverlay", None)
        if rect:
            self.logger.debug(f"Initializing rectangle selection using RectangleOverlay attribute")
            params["RectangleOverlay"].show()
        else:
            self.logger.debug(f"RectangleOverlay attribute not found. Cannot initialize rectangle selection.")

    def rectangle_selection_timeout(self, command, params={}):
        """
        Handle the rectangle_selection_timeout command.
        """
        rect = params.get("RectangleOverlay", None)
        if rect:
            self.logger.debug(f"Initializing rectangle selection using RectangleOverlay attribute")
            params["RectangleOverlay"].hide()
        else:
            self.logger.debug(f"RectangleOverlay attribute not found. Cannot initialize rectangle selection.")

    def _handle_zoom_in(self):
        """Handle zoom in command."""
        new_scale = min(self._zoom_scale + self._zoom_step, self._get_max_zoom_scale())
        if new_scale != self._zoom_scale:
            self._zoom_scale = new_scale
            self._apply_zoom_scale()
            # self.logger.debug(f"Zoomed in to {self._zoom_scale:.1f}x")

    def _handle_zoom_out(self):
        """Handle zoom out command."""
        new_scale = max(self._zoom_scale - self._zoom_step, self._get_min_zoom_scale())
        if new_scale != self._zoom_scale:
            self._zoom_scale = new_scale
            self._apply_zoom_scale()
            # self.logger.debug(f"Zoomed out to {self._zoom_scale:.1f}x")

    def _handle_reset_zoom(self):
        """Handle reset zoom command."""
        if self._zoom_scale != 1.0:
            self._zoom_scale = 1.0
            self._apply_zoom_scale()
            # self.logger.debug("Reset zoom to 1.0x")

    def _handle_set_zoom(self, scale):
        """Handle set zoom command with specific scale."""
        min_scale = self._get_min_zoom_scale()
        max_scale = self._get_max_zoom_scale()
        new_scale = max(min_scale, min(scale, max_scale))
        if new_scale != self._zoom_scale:
            self._zoom_scale = new_scale
            self._apply_zoom_scale()
            # self.logger.debug(f"Set zoom to {self._zoom_scale:.1f}x")

    def moveEvent(self, event):
        """Handle move events - CLEAN PATTERN."""
        super().moveEvent(event)
        # CLEAN PATTERN: Use centralized overlay sync method
        self._sync_overlay_geometry()

    def resizeEvent(self, event):
        """Handle resize events - CLEAN PATTERN."""
        super().resizeEvent(event)
        # CLEAN PATTERN: Use centralized overlay sync method
        self._sync_overlay_geometry()
        # self._ensure_color_overlay_on_top()

    def cleanup_resources(self):
        """
        Clean up resources properly when the widget is closed.
        """
        # Stop zoom timer
        if hasattr(self, "_zoom_timer") and self._zoom_timer:
            self._zoom_timer.stop()

        if self.media_player:
            self.media_player.cleanup_resources()
        if hasattr(self, "color_overlay") and self.color_overlay:
            try:
                self.color_overlay.hide()
                self.color_overlay.deleteLater()
            except RuntimeError:
                # Widget already deleted, ignore
                pass

    def keyPressEvent(self, event):
        """Handle key events with better performance using a lookup table"""
        key = event.key()
        # Color map with TRANSPARENCY for efficient color assignment
        color_keys = {
            Qt.Key_1: (255, 0, 0, 150),    # Red 60% transparent
            Qt.Key_2: (0, 255, 0, 150),    # Green 60% transparent
            Qt.Key_3: (0, 0, 255, 150),    # Blue 60% transparent
            Qt.Key_4: (255, 255, 0, 150),  # Yellow 60% transparent
            Qt.Key_5: (0, 255, 255, 150),  # Cyan 60% transparent
            Qt.Key_6: (255, 0, 255, 150),  # Magenta 60% transparent
            Qt.Key_7: (255, 255, 255, 120), # White 50% transparent
            Qt.Key_8: (128, 128, 128, 180), # Gray 70% transparent
        }

        if key in color_keys:
            color = color_keys[key]
            self.logger.debug(f"Key {key-Qt.Key_0} pressed, setting color")
            self.set_colorized(QColor(*color))
        elif key == Qt.Key_Space:
            self.logger.debug("Space key pressed, resetting color")
            self.reset_colorized(None)
        elif key in (Qt.Key_Plus, Qt.Key_Equal) and self.media_player:
            new_rate = min(self.media_player.playback_rate + 0.25, 3.0)
            self.set_playback_rate(new_rate)
            self.logger.debug(f"Playback rate increased to {new_rate}x")
        elif key == Qt.Key_Minus and self.media_player:
            new_rate = max(self.media_player.playback_rate - 0.25, 0.25)
            self.set_playback_rate(new_rate)
            self.logger.debug(f"Playback rate decreased to {new_rate}x")
        elif key == Qt.Key_0:
            self.set_playback_rate(1.0)
            self.logger.debug("Playback rate reset to 1.0x")
        elif key == Qt.Key_P:
            is_paused = self.toggle_pause()
            self.logger.debug(f"Toggled pause state, is_paused: {is_paused}")
        elif key == Qt.Key_H:
            self.toggle_acceleration_mode()
        elif key == Qt.Key_PageUp:
            self._handle_zoom_in()
        elif key == Qt.Key_PageDown:
            self._handle_zoom_out()
        elif key == Qt.Key_Home:
            self._handle_reset_zoom()
        elif key == Qt.Key_Escape:
            self.cleanup_resources()
            self.close()
            QCoreApplication.quit()

    def exit(self):
        self.cleanup_resources()
        self.close()
        QCoreApplication.quit()

    def toggle_acceleration_mode(self):
        """Toggle between hardware and software acceleration"""
        self.use_hardware_acceleration = not self.use_hardware_acceleration
        acceleration_type = "GPU" if self.use_hardware_acceleration else "SOFTWARE"
        self.logger.info(f"🔄 Switched to {acceleration_type} acceleration")

        # Reload media with new acceleration setting
        if self.media_path:
            self.set_media_source(self.media_path)

    def set_acceleration_mode(self, use_hardware):
        """Set acceleration mode explicitly"""
        if self.use_hardware_acceleration != use_hardware:
            self.use_hardware_acceleration = use_hardware
            acceleration_type = "GPU" if use_hardware else "SOFTWARE"
            self.logger.info(f"🎯 Set acceleration to {acceleration_type}")

            # Reload media with new acceleration setting
            if self.media_path:
                self.set_media_source(self.media_path)

    def run(self):
        """
        Run the EnergyBall widget.
        This method is called when the widget is executed as a standalone application.
        """
        self.logger.debug(f"Running EnergyBall widget")
        # self.show()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Set up logging
    logger = AppLogger()
    logger.debug("Starting EnergyBall application")
    media_path = "avatar/opti500.mp4"
    energy_ball = Star(media_path)

    # Print controls
    print("EnergyBall Controls:")
    print("  1-8: Change colors")
    print("  Space: Reset color")
    print("  +/-: Increase/decrease playback speed")
    print("  0: Reset playback speed to normal")
    print("  Page Up/Down: Zoom in/out")
    print("  Home: Reset zoom to 1.0x")
    print("  Mouse Wheel: Zoom in/out")
    print("  Escape: Exit")

    # POSITIONING FIX: Center the widget on screen
    screen = app.primaryScreen().geometry()
    widget_size = energy_ball.size()
    x = (screen.width() - widget_size.width() // 1.25)
    y = (screen.height() - widget_size.height() // 1.20)
    energy_ball.move(x, y)

    # Show the widget
    energy_ball.show()
    logger.debug("EnergyBall widget shown")

    # Run the application
    sys.exit(app.exec())
