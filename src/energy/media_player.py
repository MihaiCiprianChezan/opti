"""
Media player classes for handling GIF and video playback.

This module provides classes for playing GIF animations and avatar
with support for playback control and media switching.
"""

import logging
import os

os.environ["QT_LOGGING_RULES"] = "*.debug=false;*.info=false;*.warning=false"
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QMovie
from PySide6.QtMultimedia import QMediaPlayer, QMediaMetaData
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QLabel, QWidget

from utils.app_logger import AppLogger
from energy.media_effect import GifMediaEffect, VideoMediaEffect


class MediaPlayer:
    """
    Base class for media players.

    This class provides a common interface for playing media,
    regardless of the underlying implementation.
    """

    def __init__(self, parent_widget):
        """
        Initialize the media player.

        Args:
            parent_widget: The widget that will contain the media player
        """
        self.parent_widget = parent_widget
        self.logger = AppLogger(name=self.__class__.__name__, log_level=logging.DEBUG)
        self.name = self.__class__.__name__
        self.media_path = None
        self.playback_rate = 1.0
        self.media_widget = None
        self.media_effect = None
        self.original_size = (200, 200)  # Default size

    def load_media(self, media_path):
        """
        Load media from the specified path.

        Args:
            media_path (str): The path to the media file
        """
        raise NotImplementedError("Subclasses must implement load_media")

    def play(self):
        """
        Start playback of the media.
        """
        raise NotImplementedError("Subclasses must implement play")

    def stop(self):
        """
        Stop playback of the media.
        """
        raise NotImplementedError("Subclasses must implement stop")

    def set_playback_rate(self, rate):
        """
        Set the playback speed for the media.

        Args:
            rate (float): Playback rate (1.0 is normal speed, 2.0 is double speed, etc.)
        """
        if rate <= 0:
            self.logger.warning(f"Invalid playback rate: {rate}. Must be positive.")
            return

        self.playback_rate = rate

    def get_media_widget(self):
        """
        Get the widget that displays the media.

        Returns:
            QWidget: The media widget
        """
        return self.media_widget

    def get_original_size(self):
        """
        Get the original size of the media.

        Returns:
            tuple: The original size (width, height)
        """
        return self.original_size

    def set_color(self, color, duration=500):
        """
        Set the colorization color for the media.

        Args:
            color (QColor): The color to apply
            duration (int): The duration of the transition animation in milliseconds
        """
        if self.media_effect:
            self.media_effect.set_color(color, duration)

    def reset_color(self, duration=500):
        """
        Reset the colorization color for the media.

        Args:
            duration (int): The duration of the transition animation in milliseconds
        """
        if self.media_effect:
            self.media_effect.reset_color(duration)

    def set_opacity(self, opacity):
        """
        Set the opacity for the media.

        Args:
            opacity (float): The opacity value (0.0 to 1.0)
        """
        if self.media_effect:
            self.media_effect.set_opacity(opacity)

    def get_opacity(self):
        """
        Get the current opacity of the media.

        Returns:
            float: The current opacity value
        """
        if self.media_effect:
            return self.media_effect.get_opacity()
        return 1.0  # Default opacity

    def cleanup_resources(self):
        """
        Clean up resources properly when the media player is closed.
        """
        self.stop()

        # Clean up the overlay widget if it exists
        if self.overlay_widget:
            self.overlay_widget.setParent(None)
            self.overlay_widget.deleteLater()
            self.overlay_widget = None
            self.logger.debug(f"Cleaned up overlay widget")


class GifPlayer(MediaPlayer):
    """
    Media player for GIF animations.

    This class uses QMovie to play GIF animations.
    """

    def __init__(self, parent_widget):
        """
        Initialize the GIF player.

        Args:
            parent_widget: The widget that will contain the GIF player
        """
        super().__init__(parent_widget)
        self.movie = None
        self.label = None

    def load_media(self, media_path):
        """
        Load a GIF animation from the specified path.

        Args:
            media_path (str): The path to the GIF file
        """
        self.media_path = media_path

        # Clean up any existing resources
        if self.movie:
            self.movie.stop()

        if self.label:
            self.label.setParent(None)

        # Create a new QMovie
        self.movie = QMovie(media_path)

        # Get the original size of the GIF
        self.movie.start()
        self.original_size = (self.movie.frameRect().width(), self.movie.frameRect().height())

        # Create a QLabel to display the GIF
        self.label = QLabel(self.parent_widget)
        self.label.setAttribute(Qt.WA_TranslucentBackground, True)
        self.label.setMovie(self.movie)

        # Add the label to the parent widget's layout
        if self.parent_widget.layout():
            self.parent_widget.layout().addWidget(self.label)

        # Set the media widget reference
        self.media_widget = self.label

        # Create a media effect for the GIF
        self.media_effect = GifMediaEffect(self.label)

        # Apply the current playback rate
        self.set_playback_rate(self.playback_rate)

        self.logger.debug(f"Loaded GIF: {media_path}")

    def play(self):
        """
        Start playback of the GIF animation.
        """
        if self.movie:
            self.movie.start()
            self.logger.debug(f"Started GIF playback")

    def stop(self):
        """
        Stop playback of the GIF animation.
        """
        if self.movie:
            self.movie.stop()
            self.logger.debug(f"Stopped GIF playback")

    def set_playback_rate(self, rate):
        """
        Set the playback speed for the GIF animation.

        Args:
            rate (float): Playback rate (1.0 is normal speed, 2.0 is double speed, etc.)
        """
        super().set_playback_rate(rate)

        if self.movie:
            self.movie.setSpeed(int(100 * rate))
            self.logger.debug(f"Set GIF playback rate to {rate}x")


class VideoPlayer(MediaPlayer):
    """
    Media player for avatar.

    This class uses QMediaPlayer and QVideoWidget to play avatar.
    """

    def __init__(self, parent_widget, use_hardware_acceleration=True):
        """
        Initialize the video player.

        Args:
            parent_widget: The widget that will contain the video player
            use_hardware_acceleration (bool): Use GPU acceleration (True) or software decoding (False)
        """
        super().__init__(parent_widget)
        self.media_player = None
        self.video_widget = None
        self.overlay_widget = None
        self.is_paused = False
        self.use_hardware_acceleration = use_hardware_acceleration

        # Set FFmpeg environment variables for acceleration control
        if not use_hardware_acceleration:
            # Force software decoding
            os.environ["QT_MEDIA_BACKEND"] = "ffmpeg"
            os.environ["QT_FFMPEG_HWACCEL"] = "none"
            self.logger.info("🔧 Configured for SOFTWARE video decoding")
        else:
            # Allow hardware acceleration (default)
            if "QT_FFMPEG_HWACCEL" in os.environ:
                del os.environ["QT_FFMPEG_HWACCEL"]
            self.logger.info("🚀 Configured for HARDWARE video acceleration")

    def load_media(self, media_path):
        """
        Load a video from the specified path into memory for faster playback.

        Args:
            media_path (str): The path to the video file
        """
        self.media_path = media_path

        # Clean up any existing resources
        if self.media_player:
            self.media_player.stop()

        if self.video_widget:
            self.video_widget.setParent(None)

        if self.overlay_widget:
            self.overlay_widget.setParent(None)

        # MEMORY CACHING: Load video file completely into memory for faster access
        try:
            with open(media_path, 'rb') as file:
                video_data = file.read()

            # Create a QBuffer to hold the video data in memory
            from PySide6.QtCore import QBuffer, QIODevice
            self.video_buffer = QBuffer()
            self.video_buffer.setData(video_data)
            self.video_buffer.open(QIODevice.ReadOnly)

            self.logger.debug(f"Loaded {len(video_data)} bytes of video into memory buffer")
            use_memory_buffer = True

        except Exception as e:
            self.logger.warning(f"Failed to load video into memory: {e}, falling back to file streaming")
            self.video_buffer = None
            use_memory_buffer = False

        # Create a new QMediaPlayer
        self.media_player = QMediaPlayer()

        # Create a QVideoWidget to display the video
        self.video_widget = QVideoWidget(self.parent_widget)

        # Make the video widget transparent to mouse events so parent can handle them
        self.video_widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        # Enable translucent background for transparency and colorization effects
        self.video_widget.setAttribute(Qt.WA_TranslucentBackground, True)

        # Make sure the video widget is visible
        self.video_widget.setVisible(True)
        self.video_widget.show()

        # Configure the media player - USE MEMORY BUFFER IF AVAILABLE
        self.media_player.setVideoOutput(self.video_widget)

        if use_memory_buffer and self.video_buffer:
            # Use the memory buffer for faster playback
            self.media_player.setSourceDevice(self.video_buffer)
            self.logger.debug(f"Using memory buffer for video playback")
        else:
            # Fallback to file-based streaming
            self.media_player.setSource(QUrl.fromLocalFile(os.path.abspath(media_path)))
            self.logger.debug(f"Using file streaming for video playback")

        self.media_player.setLoops(QMediaPlayer.Infinite)  # Loop the video

        # Create a transparent overlay widget for colorization effects FIRST
        self.overlay_widget = QWidget(self.parent_widget)
        self.overlay_widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.overlay_widget.setAttribute(Qt.WA_TranslucentBackground, True)

        # Make the overlay widget a regular widget, not a separate window
        self.overlay_widget.setWindowFlags(Qt.Widget)

        # Set a completely transparent background initially
        self.overlay_widget.setStyleSheet("background-color: rgba(0, 0, 0, 0);")

        # Make the overlay widget visible
        self.overlay_widget.setVisible(True)

        # Add the overlay widget to the parent widget's layout FIRST (bottom layer)
        if self.parent_widget.layout():
            self.parent_widget.layout().addWidget(self.overlay_widget)

        # Add the video widget to the parent widget's layout SECOND (top layer)
        if self.parent_widget.layout():
            self.parent_widget.layout().addWidget(self.video_widget)

        # Make sure the overlay widget is the same size as the video widget
        self.overlay_widget.setGeometry(self.video_widget.geometry())

        # Log that we're using an overlay for colorization effects
        self.logger.debug(f"Created overlay widget for colorization effects as a regular widget")

        # Make video widget transparent
        self.video_widget.setWindowOpacity(0.5)  # Make video semi-transparent
        if hasattr(self.parent_widget, 'setWindowOpacity'):
            self.parent_widget.setWindowOpacity(0.8)
        self.video_widget.setAttribute(Qt.WA_TranslucentBackground, True)
        self.video_widget.setAttribute(Qt.WA_NoSystemBackground, True)


        # Don't change parent opacity - only video widget
        # self.parent_widget.setWindowOpacity(0.8)  # Removed

        # Set the media widget reference to the video widget
        self.media_widget = self.video_widget

        # Create a media effect for the overlay widget instead of the video widget
        self.media_effect = VideoMediaEffect(self.overlay_widget)

        # Connect signals for video
        self.media_player.mediaStatusChanged.connect(self._handle_media_status)

        # Apply the current playback rate
        self.set_playback_rate(self.playback_rate)

        self.logger.debug(f"Loaded video: {media_path} with overlay for effects")

    def play(self):
        """
        Start playback of the video.
        """
        if self.media_player:
            self.media_player.play()
            self.is_paused = False
            self.logger.debug(f"Started video playback")

    def stop(self):
        """
        Stop playback of the video.
        """
        if self.media_player:
            self.media_player.stop()
            self.is_paused = False
            self.logger.debug(f"Stopped video playback")

    def pause(self):
        """
        Pause playback of the video.
        """
        if self.media_player:
            self.media_player.pause()
            self.is_paused = True
            self.logger.debug(f"Paused video playback")

    def resume(self):
        """
        Resume playback of the video if it was paused.
        """
        if self.media_player and self.is_paused:
            self.media_player.play()
            self.is_paused = False
            self.logger.debug(f"Resumed video playback")

    def toggle_pause(self):
        """
        Toggle between pause and play states.
        """
        if self.media_player:
            if self.is_paused:
                self.resume()
            else:
                self.pause()
            return self.is_paused

    def set_playback_rate(self, rate):
        """
        Set the playback speed for the video.

        Args:
            rate (float): Playback rate (1.0 is normal speed, 2.0 is double speed, etc.)
        """
        super().set_playback_rate(rate)

        if self.media_player:
            self.media_player.setPlaybackRate(rate)
            self.logger.debug(f"Set video playback rate to {rate}x")

    def get_media_dimensions(self):
        """Get the dimensions of the video from metadata."""
        try:
            metadata = self.media_player.metaData()
            if metadata:
                video_frame = metadata.value(self.media_player.metaData().Resolution)
                if video_frame:
                    return video_frame.width(), video_frame.height()

            # Fallback to manual frame check if metadata is not available
            frame = self.media_player.videoOutput().videoFrame()
            if frame.isValid():
                return frame.width(), frame.height()

            # Default dimensions if all else fails
            return 200, 200

        except Exception as e:
            self.logger.warning(f"Could not get video dimensions: {str(e)}")
            return 200, 200  # Default dimensions

    def process_frame(self):
        """Process the next video frame"""
        if self.media_player and not self.is_paused:
            # Process the next frame
            self.media_player.setPosition(self.media_player.position() + 16)  # Move ~60fps

            # Loop video if needed
            if self.media_player.position() >= self.media_player.duration():
                self.media_player.setPosition(0)

            # Force update the video widget
            if self.video_widget:
                self.video_widget.update()

            # Update the overlay if it exists
            if self.overlay_widget:
                self.overlay_widget.update()

    def _handle_media_status(self, status):
        """Handle media status changes for video playback."""
        self.logger.debug(f"Media status changed: {status}")

        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            self.logger.debug(f"Video loaded, updating dimensions")

            try:
                # Get metadata using proper Qt6 key format
                metadata = self.media_player.metaData()
                if metadata:
                    resolution = metadata.value(QMediaMetaData.Key.Resolution)
                    if resolution and resolution.isValid():
                        width = resolution.width()
                        height = resolution.height()
                        self.original_size = (width, height)
                        self.logger.debug(f"Video dimensions from metadata: {width}x{height}")

                        # Update widget sizes
                        self.video_widget.setGeometry(0, 0, width, height)
                        self.video_widget.setVisible(True)
                        self.video_widget.show()

                        if self.overlay_widget:
                            self.overlay_widget.setGeometry(0, 0, width, height)
                            self.overlay_widget.setVisible(True)
                            self.overlay_widget.raise_()
                            self.logger.debug(f"Updated overlay dimensions")

                        # Force repaint
                        self.parent_widget.update()

                        # Ensure video is playing
                        if self.media_player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                            self.media_player.play()

            except Exception as e:
                self.logger.debug(f"Could not get video dimensions from metadata: {str(e)}")
                # Fall back to default size
                self.original_size = (200, 200)

        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            # Restart playback when video ends (if looping is not working)
            self.media_player.setPosition(0)
            self.media_player.play()
            self.logger.debug(f"Restarted video at end")

    def cleanup_resources(self):
        """
        Clean up resources properly when the media player is closed.
        """
        if self.media_player:
            self.media_player.stop()
            self.media_player.deleteLater()
            self.media_player = None

        if self.video_widget:
            self.video_widget.setParent(None)
            self.video_widget.deleteLater()
            self.video_widget = None

        if self.overlay_widget:
            self.overlay_widget.setParent(None)
            self.overlay_widget.deleteLater()
            self.overlay_widget = None

        # Clean up memory buffer
        if hasattr(self, 'video_buffer') and self.video_buffer:
            self.video_buffer.close()
            self.video_buffer = None
            self.logger.debug(f"Cleaned up video memory buffer")

        # Reset media effect
        if self.media_effect:
            self.media_effect = None

        self.logger.debug(f"VideoPlayer resources cleaned up")
