import logging

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from utils.app_logger import AppLogger


class ColorOverlayWidget(QWidget):
    """
    A transparent widget that applies colorization effects.

    This widget can be positioned on top of other widgets to apply colorization effects.
    It has a transparent background except for the colorization effect.
    """

    def __init__(self, parent=None):
        """Initialize the color overlay widget."""
        super().__init__(parent)
        self.logger = AppLogger(name=self.__class__.__name__, log_level=logging.DEBUG)
        self.name = self.__class__.__name__
        # Initialize with a transparent color
        self.color = QColor(0, 0, 0, 0)
        self.start_color = QColor(self.color)
        self.end_color = QColor(self.color)
        # Make the widget transparent for mouse events
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        # TRANSPARENCY FIX: Proper attributes for separate window transparency
        self.setAttribute(Qt.WA_TranslucentBackground, True)  # Enable transparency
        self.setAttribute(Qt.WA_NoSystemBackground, True)  # No system background
        self.setAutoFillBackground(False)  # Don't fill background
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)  # Allow transparent painting
        # Ensure it stays on top of its siblings within the parent
        self.raise_()
        # Hide the widget initially
        self.hide()
        self.logger.debug(f"Initialized ColorOverlayWidget with WindowStaysOnTopHint")

    def set_color(self, color, duration=0):
        """Set the colorization color with optional fade animation."""
        if duration <= 0:
            # Instant color change (no animation)
            self.color = color
            # Show the widget if the color has an alpha > 0, otherwise hide it
            if color.alpha() > 0:
                self.show()
                self.raise_()
                self.update()
            else:
                self.hide()
        else:
            end_color = QColor(color)
            # Show the widget for the animation if the target color has alpha > 0
            if end_color.alpha() > 0:
                self.show()
                self.raise_()
            if hasattr(self, "color_animation") and self.color_animation.state() == QPropertyAnimation.Running:
                self.color_animation.stop()
            # Create or reuse the property animation for the color transition
            if not hasattr(self, "color_animation"):
                self.color_animation = QPropertyAnimation(self, b"animatedColor")
                self.color_animation.finished.connect(self._on_animation_finished)
            self.start_color = QColor(self.color)  # Make a copy of current color
            self.end_color = end_color
            # Configure animation
            self.color_animation.setDuration(duration)
            self.color_animation.setStartValue(0.0)
            self.color_animation.setEndValue(1.0)
            self.color_animation.setEasingCurve(QEasingCurve.InOutQuad)
            self.color_animation.finished.connect(self._on_animation_finished)
            self.color_animation.start()

    def _on_animation_finished(self):
        """Handle animation completion."""
        # Set the final color
        self.color = self.end_color
        # Hide the widget if the final color is transparent
        if self.color.alpha() == 0:
            self.hide()

    def get_animated_color(self):
        """Getter for the animated color property."""
        return 0.0  # Just return a dummy value, the actual value is not used

    def set_animated_color(self, progress):
        """ Setter for the animated color property."""
        if hasattr(self, "start_color") and hasattr(self, "end_color"):
            # Interpolate between start and end colors efficiently
            if progress <= 0.0:
                self.color = QColor(self.start_color)
            elif progress >= 1.0:
                self.color = QColor(self.end_color)
            else:
                # Fast integer math for color interpolation
                r = int(self.start_color.red() + (self.end_color.red() - self.start_color.red()) * progress)
                g = int(self.start_color.green() + (self.end_color.green() - self.start_color.green()) * progress)
                b = int(self.start_color.blue() + (self.end_color.blue() - self.start_color.blue()) * progress)
                a = int(self.start_color.alpha() + (self.end_color.alpha() - self.start_color.alpha()) * progress)
                self.color = QColor(r, g, b, a)

            self.update()

    # Define the animated color property
    animatedColor = Property(float, get_animated_color, set_animated_color)

    def paintEvent(self, event):
        """Paint the colorization effect with maximum visibility."""
        # If the color is fully transparent or widget has zero size, don't draw anything
        if self.color.alpha() == 0 or self.width() == 0 or self.height() == 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        # Fill the entire widget area - the mask will handle the circular clipping
        painter.fillRect(self.rect(), self.color)
