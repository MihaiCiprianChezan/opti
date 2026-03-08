import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QMouseEvent
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QWidget

from utils.app_logger import AppLogger


class DraggableWidget(QWidget):
    """
    Base class for widgets that can be dragged around the screen.

    This class provides functionality for dragging the widget with the mouse
    and showing a context menu on right-click.
    """

    def __init__(self, parent=None):
        """Initialize the draggable widget."""
        super().__init__(parent)
        self.logger = AppLogger(name=self.__class__.__name__, log_level=logging.DEBUG)
        self.name = self.__class__.__name__
        # State variables for dragging
        self.is_dragging = False
        self.offset = None
        # Configure the window
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")  # Fully transparent widget

    def init_position(self, size=None):
        """Set the initial position of the widget to the bottom-right corner of the screen with padding."""
        screen_geometry = QApplication.primaryScreen().availableGeometry()
        screen_width, screen_height = screen_geometry.width(), screen_geometry.height()
        padding = 100

        if size is None:
            widget_width, widget_height = self.width(), self.height()
        else:
            widget_width, widget_height = size

        self.move(screen_width - widget_width - padding, screen_height - widget_height - padding)

    def mousePressEvent(self, event: QMouseEvent):
        """Enable dragging the widget when left-clicked, or show context menu on right-click."""
        if event.button() == Qt.LeftButton:  # Left click for dragging
            self.is_dragging = True
            self.offset = event.globalPosition().toPoint() - self.pos()
        elif event.button() == Qt.RightButton:  # Right click to show the context menu
            self.show_context_menu(event.pos())
        else:
            super().mousePressEvent(event)  # Call the base class in other situations

    def mouseMoveEvent(self, event: QMouseEvent):
        """Move the widget as the mouse drags it."""
        if self.is_dragging:
            self.move(event.globalPosition().toPoint() - self.offset)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        """Stop dragging when the mouse is released."""
        if event.button() == Qt.LeftButton:
            self.is_dragging = False
        else:
            super().mouseReleaseEvent(event)

    def show_context_menu(self, position):
        """Display a context menu when right-clicking on the widget."""
        # Create the menu
        menu = QMenu(self)
        # Add actions to the menu
        self.add_context_menu_actions(menu)
        # Display the menu at the requested position
        menu.exec(self.mapToGlobal(position))

    def add_context_menu_actions(self, menu):
        """Add actions to the context menu."""
        # Add a default exit action
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close_with_confirmation)
        menu.addAction(exit_action)

    def close_with_confirmation(self):
        """Show a confirmation dialog before closing the application."""
        reply = QMessageBox.question(
            self,
            "Confirm Exit",
            "Are you sure you want to exit the application?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.cleanup_resources()
            QApplication.quit()

    def cleanup_resources(self):
        """Clean up resources properly when the widget is closed."""
        self.logger.debug(f"Resources cleaned up")

    def closeEvent(self, event):
        """Handle the close event to ensure resources are properly cleaned up."""
        self.cleanup_resources()
        super().closeEvent(event)
