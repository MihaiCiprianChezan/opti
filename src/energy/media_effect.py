import logging

from PySide6.QtCore import Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QGraphicsColorizeEffect, QGraphicsEffect

from utils.app_logger import AppLogger

DEFAULT_DURATION = 800

class MediaEffect:
    """
    Base class for handling colorization and transparency effects.

    This class provides a common interface for applying effects to media widgets,
    regardless of the underlying implementation.
    """

    def __init__(self, target_widget):
        """
        Initialize the media effect.

        Args:
            target_widget: The widget to apply the effect to
        """
        self.target_widget = target_widget
        self.logger = AppLogger(name=self.__class__.__name__, log_level=logging.DEBUG)
        self.name = self.__class__.__name__

    def set_color(self, color, duration=DEFAULT_DURATION):
        """
        Set the colorization color.

        Args:
            color (QColor): The color to apply
            duration (int): The duration of the transition animation in milliseconds
        """
        raise NotImplementedError("Subclasses must implement set_color")

    def reset_color(self, duration=DEFAULT_DURATION):
        """
        Reset the colorization color.

        Args:
            duration (int): The duration of the transition animation in milliseconds
        """
        raise NotImplementedError("Subclasses must implement reset_color")

    def set_opacity(self, opacity):
        """
        Set the opacity.

        Args:
            opacity (float): The opacity value (0.0 to 1.0)
        """
        raise NotImplementedError("Subclasses must implement set_opacity")

    def get_opacity(self):
        """
        Get the current opacity.

        Returns:
            float: The current opacity value
        """
        raise NotImplementedError("Subclasses must implement get_opacity")


class GifMediaEffect(MediaEffect):
    """
    Media effect for GIF widgets.

    This class uses QGraphicsColorizeEffect for colorization and manages
    the effect's strength using animations.
    """

    def __init__(self, target_widget):
        """
        Initialize the GIF media effect.

        Args:
            target_widget: The GIF widget to apply the effect to
        """
        super().__init__(target_widget)
        self.color_effect = None
        self.color_animation = None

    def set_color(self, color, duration=DEFAULT_DURATION):
        """
        Set the colorization color for the GIF widget.

        Args:
            color (QColor): The color to apply
            duration (int): The duration of the transition animation in milliseconds
        """
        # Stop any running animation
        if self.color_animation is not None:
            self.color_animation.stop()
            try:
                self.color_animation.deleteLater()
            except RuntimeError:
                self.logger.warning(f"Attempted to delete an already-deleted QVariantAnimation.")
            self.color_animation = None

        # Remove any existing effect
        existing_effect = self.target_widget.graphicsEffect()
        if existing_effect:
            self.target_widget.setGraphicsEffect(None)
            try:
                existing_effect.deleteLater()
            except RuntimeError:
                self.logger.warning(f"Attempted to delete an already-deleted QGraphicsEffect.")

        # Create and apply a new color effect
        self.color_effect = QGraphicsColorizeEffect(self.target_widget)
        self.color_effect.setColor(color)
        self.target_widget.setGraphicsEffect(self.color_effect)

        # Create a new animation
        self.color_animation = QVariantAnimation(self.target_widget)
        self.color_animation.setStartValue(0.0)
        self.color_animation.setEndValue(1.0)
        self.color_animation.setDuration(duration)

        # Update the effect's strength during animation
        def update_strength(strength):
            if self.color_effect:  # Check if color_effect still exists
                try:
                    self.color_effect.setStrength(strength)
                    # Force an update to ensure the effect is rendered
                    self.target_widget.update()
                    # self.logger.debug(f"Updated QGraphicsColorizeEffect strength to {strength}")
                except RuntimeError:
                    self.logger.debug(f"QGraphicsColorizeEffect already deleted during animation.")

        self.color_animation.valueChanged.connect(update_strength)

        # Debugging info for when the animation completes
        def on_animation_complete():
            self.logger.debug(f"Transition to {color} complete.")

        self.color_animation.finished.connect(on_animation_complete)

        # Start the animation
        self.color_animation.start()

    def reset_color(self, duration=800):
        """
        Reset the colorization color for the GIF widget.

        Args:
            duration (int): The duration of the transition animation in milliseconds
        """
        # Stop any running animation
        if self.color_animation is not None:
            self.color_animation.stop()
            try:
                self.color_animation.deleteLater()
            except RuntimeError:
                self.logger.warning(f"Attempted to delete an already-deleted QVariantAnimation.")
            self.color_animation = None

        # Check if there is an existing effect
        existing_effect = self.target_widget.graphicsEffect()
        if not existing_effect or not isinstance(existing_effect, QGraphicsColorizeEffect):
            return  # No effect to remove

        # Create an animation to reduce the effect's strength smoothly
        animation = QVariantAnimation(self.target_widget)
        animation.setStartValue(1.0)  # Full strength of the effect
        animation.setEndValue(0.0)  # No effect (reset state)
        animation.setDuration(duration)  # Duration in milliseconds

        def fade_out_effect(strength):
            # Validate strength
            if not (0.0 <= strength <= 1.0):
                raise ValueError("Strength must be between 0.0 and 1.0")

            effect = self.target_widget.graphicsEffect()
            if effect is None:
                # Apply a new graphics effect if one does not exist
                effect = QGraphicsColorizeEffect()
                self.target_widget.setGraphicsEffect(effect)
            if isinstance(effect, QGraphicsColorizeEffect):
                effect.setStrength(strength)
                # Force an update to ensure the effect is rendered
                self.target_widget.update()
                # self.logger.debug(f"Updated QGraphicsColorizeEffect strength to {strength} during fade out")
                if strength == 0.0:
                    # Remove the color effect when faded out
                    self.target_widget.setGraphicsEffect(None)
                    self.target_widget.update()
                    self.logger.debug(f"Removed QGraphicsColorizeEffect")

        # Connect the animation's valueChanged signal to dynamically update the effect
        animation.valueChanged.connect(fade_out_effect)
        animation.start()

    def set_opacity(self, opacity):
        """
        Set the opacity for the GIF widget.

        Args:
            opacity (float): The opacity value (0.0 to 1.0)
        """
        # GIF widgets use the parent widget's opacity
        self.target_widget.setWindowOpacity(opacity)

    def get_opacity(self):
        """
        Get the current opacity of the GIF widget.

        Returns:
            float: The current opacity value
        """
        return self.target_widget.windowOpacity()


class CombinedEffect(QGraphicsEffect):
    """
    A custom graphics effect that combines colorization and opacity effects.

    This allows applying both color overlay and transparency to a widget simultaneously,
    which is not directly supported by Qt's standard graphics effects.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.color = QColor(0, 0, 0)  # Default color (no colorization)
        self.strength = 0.0  # Default strength (no colorization)
        self.opacity = 0.5  # Default opacity (50% opaque)

    def setColor(self, color):
        """Set the colorization color."""
        self.color = color
        self.update()

    def getColor(self):
        """Get the colorization color."""
        return self.color

    def setStrength(self, strength):
        """Set the colorization strength (0.0 to 1.0)."""
        self.strength = max(0.0, min(1.0, strength))  # Clamp between 0 and 1
        self.update()

    def getStrength(self):
        """Get the colorization strength."""
        return self.strength

    def setOpacity(self, opacity):
        """Set the opacity (0.0 to 1.0)."""
        self.opacity = max(0.0, min(1.0, opacity))  # Clamp between 0 and 1
        self.update()

    def getOpacity(self):
        """Get the opacity."""
        return self.opacity

    def draw(self, painter):
        """
        Draw the effect by applying both colorization and opacity.

        This is called by Qt's rendering system.
        """
        # Get the current opacity and strength
        current_opacity = self.getOpacity()
        current_strength = self.getStrength()
        current_color = self.getColor()

        if current_opacity <= 0.0:
            return  # Nothing to draw if fully transparent

        # Get the source pixmap
        source = self.sourcePixmap(Qt.LogicalCoordinates)
        if source.isNull():
            return  # Nothing to draw if source is null

        # Get the bounding rectangle
        rect = self.boundingRectFor(source.rect())

        # Save the painter state
        painter.save()

        # Apply opacity directly to the painter
        painter.setOpacity(current_opacity)

        # If colorization strength is 0, just draw the source with opacity
        if current_strength <= 0.0:
            painter.drawPixmap(rect.toRect(), source)
        else:
            # Apply colorization using a more direct approach
            # Create a copy of the source pixmap to modify
            colorized = source.copy()

            # Create a painter for the colorized pixmap
            colorize_painter = QPainter(colorized)

            # Use a single composition mode for a more subtle, transparent effect
            colorize_painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

            # Create a color with appropriate strength and reduced opacity
            overlay_color = QColor(current_color)
            overlay_color.setAlphaF(current_strength * 0.5)  # Reduce opacity by half for better transparency

            # Fill the pixmap with the color overlay
            colorize_painter.fillRect(colorized.rect(), overlay_color)

            colorize_painter.end()

            # Draw the colorized pixmap
            painter.drawPixmap(rect.toRect(), colorized)

        # Restore the painter state
        painter.restore()


class VideoMediaEffect(MediaEffect):
    """
    Media effect for video widgets.

    This class applies colorization by drawing a colored overlay directly on top of the video
    using a custom paintEvent with strong composition modes for maximum visibility.
    """

    def __init__(self, target_widget):
        """
        Initialize the video media effect.

        Args:
            target_widget: The overlay widget to apply the effect to
        """
        super().__init__(target_widget)
        self.color_animation = None
        self.current_color = QColor(0, 0, 0, 0)  # Fully transparent black
        self.current_opacity = 0.5  # Default opacity (50% opaque)

        # Set initial transparent background
        self.target_widget.setStyleSheet("background-color: rgba(0, 0, 0, 0);")
        self.target_widget.update()

        self.logger.debug(f"Initialized VideoMediaEffect with direct overlay approach for colorization")

    def set_color(self, color, duration=DEFAULT_DURATION):
        """
        Set the colorization color for the video widget using a much more aggressive approach
        that ensures the color is visible regardless of the video content.

        Args:
            color (QColor): The color to apply
            duration (int): The duration of the transition animation in milliseconds
        """
        # Stop any running animation
        if self.color_animation is not None:
            self.color_animation.stop()
            try:
                self.color_animation.deleteLater()
            except RuntimeError:
                self.logger.warning(f"Attempted to delete an already-deleted QVariantAnimation.")
            self.color_animation = None

        # Create a new animation to transition the background color
        # Store the target color with reduced opacity for better transparency
        target_color = QColor(color)
        target_color.setAlpha(128)  # 50% opacity for better transparency
        self.current_color = target_color

        # Start with fully transparent color
        start_color = QColor(color)
        start_color.setAlpha(0)

        self.color_animation = QVariantAnimation(self.target_widget)
        self.color_animation.setStartValue(0)
        self.color_animation.setEndValue(128)  # 50% opacity
        self.color_animation.setDuration(duration)

        # Create a custom paint method for the overlay widget

        # Store the original paintEvent if it hasn't been stored yet
        if not hasattr(self.target_widget, "_original_paintEvent"):
            self.target_widget._original_paintEvent = self.target_widget.paintEvent

        # Define a new paintEvent that draws a colored rectangle over the widget
        def custom_paintEvent(event):
            # Call the original paintEvent first
            if hasattr(self.target_widget, "_original_paintEvent"):
                self.target_widget._original_paintEvent(event)

            # Draw the colored overlay
            painter = QPainter(self.target_widget)
            painter.setRenderHint(QPainter.Antialiasing)

            # Create a more transparent version of the color for the overlay
            overlay_color = QColor(self.current_color)
            overlay_color.setAlpha(100)  # 40% opacity for better transparency

            # Use a single composition mode for a more subtle, transparent effect
            # SourceOver mode respects transparency and blends more naturally
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.fillRect(self.target_widget.rect(), overlay_color)

            painter.end()

        # Replace the paintEvent method
        self.target_widget.paintEvent = custom_paintEvent

        # Update the background color during animation
        def update_color(alpha):
            color_copy = QColor(color)
            color_copy.setAlpha(alpha)
            self.current_color = color_copy

            # Force a repaint to update the overlay
            self.target_widget.update()

            # Ensure the overlay widget is visible and on top
            self.target_widget.setVisible(True)
            self.target_widget.raise_()

            # Set z-order to ensure overlay is on top (if widget supports it)
            if hasattr(self.target_widget, "setZValue"):
                self.target_widget.setZValue(999)

            # Make sure the parent widget knows to update
            if self.target_widget.parent():
                self.target_widget.parent().update()

            # Force the parent to repaint as well
            parent = self.target_widget.parent()
            if parent:
                parent.update()
                # If there's a grandparent, update it too to ensure propagation
                if parent.parent():
                    parent.parent().update()

            self.logger.debug(f"Updated overlay color to rgba({color_copy.red()}, {color_copy.green()}, {color_copy.blue()}, {alpha})")

        self.color_animation.valueChanged.connect(update_color)

        # Debugging info for when the animation completes
        def on_animation_complete():
            # Ensure the overlay widget is still visible and on top after animation
            self.target_widget.setVisible(True)
            self.target_widget.raise_()
            self.logger.debug(f"Color transition complete to rgba({target_color.red()}, {target_color.green()}, {target_color.blue()}, {target_color.alpha()})")

        self.color_animation.finished.connect(on_animation_complete)

        # Start the animation
        self.color_animation.start()

    def reset_color(self, duration=DEFAULT_DURATION):
        """
        Reset the colorization color for the video widget by transitioning
        the overlay color back to fully transparent and restoring the original paintEvent.

        Args:
            duration (int): The duration of the transition animation in milliseconds
        """
        # Stop any running animation
        if self.color_animation is not None:
            self.color_animation.stop()
            try:
                self.color_animation.deleteLater()
            except RuntimeError:
                self.logger.warning(f"Attempted to delete an already-deleted QVariantAnimation.")
            self.color_animation = None

        # Create a new animation to transition back to transparent
        # Get the current color's alpha value
        start_alpha = self.current_color.alpha() if self.current_color else 204  # Default to 80% if no current color

        self.color_animation = QVariantAnimation(self.target_widget)
        self.color_animation.setStartValue(start_alpha)
        self.color_animation.setEndValue(0)  # Fully transparent
        self.color_animation.setDuration(duration)

        # Update the color during animation
        def fade_out_color(alpha):
            # Create a new color with the same RGB values but updated alpha
            if self.current_color:
                color_copy = QColor(self.current_color)
                color_copy.setAlpha(alpha)
                self.current_color = color_copy
            else:
                self.current_color = QColor(0, 0, 0, alpha)  # Default to black if no current color

            # Force a repaint to update the overlay
            self.target_widget.update()

            # Ensure the overlay widget remains visible during fade-out
            self.target_widget.setVisible(True)

            self.logger.debug(f"Fading out overlay color to alpha={alpha}")

        self.color_animation.valueChanged.connect(fade_out_color)

        # Debugging info for when the animation completes
        def on_animation_complete():
            # Restore the original paintEvent if it exists
            if hasattr(self.target_widget, "_original_paintEvent"):
                self.target_widget.paintEvent = self.target_widget._original_paintEvent
                self.logger.debug(f"Restored original paintEvent")

            # Reset current color to transparent black
            self.current_color = QColor(0, 0, 0, 0)

            # Force a repaint to update the widget
            self.target_widget.update()

            self.logger.debug(f"Color reset complete, overlay is now fully transparent")

        self.color_animation.finished.connect(on_animation_complete)

        # Start the animation
        self.color_animation.start()

    def set_opacity(self, opacity):
        """
        Set the opacity for the video widget by controlling the parent widget's opacity.

        Args:
            opacity (float): The opacity value (0.0 to 1.0)
        """
        # Clamp opacity between 0 and 1
        opacity = max(0.0, min(1.0, opacity))

        # Store the current opacity
        self.current_opacity = opacity

        # Set the opacity of the parent widget (which contains both the video and overlay)
        parent = self.target_widget.parent()
        if parent:
            parent.setWindowOpacity(opacity)
            self.logger.debug(f"Set parent widget opacity to {opacity}")
        else:
            self.logger.warning(f"Cannot set opacity: parent widget not found")

    def get_opacity(self):
        """
        Get the current opacity of the video widget.

        Returns:
            float: The current opacity value
        """
        # Return the stored opacity value
        return self.current_opacity
