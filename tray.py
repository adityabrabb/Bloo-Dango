import os
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QListWidget, QListWidgetItem, QCheckBox, QLineEdit,
    QDateTimeEdit, QFormLayout, QMessageBox
)
from PyQt5.QtCore import Qt, QTimer, QDateTime, QObject, pyqtSignal
import pystray
from PIL import Image
import storage

# Qt display format matching storage.DT_FORMAT.
QT_DT_FORMAT = "yyyy-MM-ddTHH:mm:ss"
# Friendlier format for on-screen display.
QT_DISPLAY_FORMAT = "yyyy-MM-dd HH:mm"


def show_dialog(dialog):
    """Show a modal dialog and make sure it lands in front of everything.

    Bloo Dango's dialogs are spawned by a background tray app, so without this they
    routinely open behind whatever window has focus and look like nothing
    happened.
    """
    dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowStaysOnTopHint)
    QTimer.singleShot(0, dialog.raise_)
    QTimer.singleShot(0, dialog.activateWindow)
    return dialog.exec_()


def _format_due(due):
    """Render a stored ISO due string in the friendlier display format."""
    if not due:
        return None
    dt = QDateTime.fromString(due, QT_DT_FORMAT)
    if not dt.isValid():
        # Tolerate values written by older versions.
        dt = QDateTime.fromString(due, QT_DISPLAY_FORMAT)
    return dt.toString(QT_DISPLAY_FORMAT) if dt.isValid() else due


class TraySignals(QObject):
    quick_add_requested = pyqtSignal()
    task_list_requested = pyqtSignal()
    show_happiness_requested = pyqtSignal(int)  # Pass the done_today count
    quit_requested = pyqtSignal()


class TaskListDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Only treat the parent as the Bloo Dango widget if it actually is one.
        self.bloo = parent if hasattr(parent, 'set_mood') else None
        self.setWindowTitle("Task List")
        self.setFixedSize(250, 400)
        self.setup_ui()
        self.refresh_tasks()

    def setup_ui(self):
        layout = QVBoxLayout()
        self.task_list = QListWidget()
        layout.addWidget(self.task_list)

        # Adding from here means the whole add/view loop is reachable by
        # clicking Bloo Dango - no trip to the system tray required.
        self.add_btn = QPushButton("+ Add Task")
        layout.addWidget(self.add_btn)

        button_layout = QHBoxLayout()
        self.mark_done_btn = QPushButton("Mark Done")
        self.delete_btn = QPushButton("Delete")
        button_layout.addWidget(self.mark_done_btn)
        button_layout.addWidget(self.delete_btn)
        layout.addLayout(button_layout)

        self.setLayout(layout)

        self.add_btn.clicked.connect(self.add_task)
        self.mark_done_btn.clicked.connect(self.mark_done)
        self.delete_btn.clicked.connect(self.delete_task)

    def add_task(self):
        dialog = QuickAddDialog(self)
        if show_dialog(dialog) == QDialog.Accepted:
            title, due = dialog.get_inputs()
            if title:
                storage.add_task(title, due)
                if self.bloo is not None:
                    self.bloo.set_mood('purr')
                self.refresh_tasks()

    def refresh_tasks(self):
        self.task_list.clear()
        tasks = storage.list_pending()
        for task in tasks:
            text = task['title']
            due = _format_due(task['due'])
            if due:
                text = f"{text} (Due: {due})"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, task['id'])
            self.task_list.addItem(item)

    def mark_done(self):
        current = self.task_list.currentItem()
        if current:
            task_id = current.data(Qt.UserRole)
            storage.mark_done(task_id)
            if self.bloo is not None:
                self.bloo.set_mood('happy')
            self.refresh_tasks()

    def delete_task(self):
        current = self.task_list.currentItem()
        if current:
            task_id = current.data(Qt.UserRole)
            reply = QMessageBox.question(
                self, 'Delete Task',
                "Are you sure you want to delete this task?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                storage.delete_task(task_id)
                self.refresh_tasks()


class QuickAddDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Quick Add Task")
        self.setFixedSize(320, 160)
        self.setup_ui()

    def setup_ui(self):
        layout = QFormLayout()
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Enter task title")

        # An explicit checkbox beats guessing: the old code treated "due ==
        # right now" as "no due date", which threw away real due dates and
        # depended on the clock not ticking between two calls.
        self.due_check = QCheckBox("Set a due date")
        self.due_edit = QDateTimeEdit()
        self.due_edit.setCalendarPopup(True)
        self.due_edit.setDateTime(QDateTime.currentDateTime().addSecs(3600))
        self.due_edit.setDisplayFormat(QT_DISPLAY_FORMAT)
        self.due_edit.setEnabled(False)
        self.due_check.toggled.connect(self.due_edit.setEnabled)

        layout.addRow("Title:", self.title_edit)
        layout.addRow(self.due_check)
        layout.addRow("Due:", self.due_edit)

        button_layout = QHBoxLayout()
        self.add_btn = QPushButton("Add")
        self.cancel_btn = QPushButton("Cancel")
        button_layout.addWidget(self.add_btn)
        button_layout.addWidget(self.cancel_btn)
        layout.addRow(button_layout)

        self.setLayout(layout)

        self.add_btn.setDefault(True)
        self.add_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)

    def get_inputs(self):
        title = self.title_edit.text().strip()
        due = None
        if self.due_check.isChecked():
            # Stored in the same ISO format the scheduler parses.
            due = self.due_edit.dateTime().toString(QT_DT_FORMAT)
        return title, due


class TrayIcon:
    def __init__(self, bloo_widget, on_quit=None):
        self.bloo = bloo_widget
        self.on_quit = on_quit
        self.walk_enabled = True  # toggle for random wander
        self.signals = TraySignals()
        self.signals.quick_add_requested.connect(self._show_quick_add_dialog)
        self.signals.task_list_requested.connect(self._show_task_list_dialog)
        self.signals.show_happiness_requested.connect(self._show_happiness)
        self.signals.quit_requested.connect(self._quit_app)
        self.setup_icon()
        self.setup_menu()

    def setup_icon(self):
        # Load the icon from assets/icon.png, create if missing
        assets_dir = os.path.join(os.path.dirname(__file__), 'assets')
        os.makedirs(assets_dir, exist_ok=True)  # save() below fails without it
        icon_path = os.path.join(assets_dir, 'icon.png')
        if not os.path.exists(icon_path):
            # Create a simple placeholder icon (16x16) if missing
            image = Image.new('RGBA', (16, 16), (0, 0, 0, 0))
            # Draw a simple blue circle for now
            from PIL import ImageDraw
            draw = ImageDraw.Draw(image)
            draw.ellipse([2, 2, 14, 14], fill=(170, 220, 255, 220))
            image.save(icon_path)
        self.image = Image.open(icon_path)

    def setup_menu(self):
        menu = pystray.Menu(
            pystray.MenuItem('Quick Add Task...', self.quick_add),
            pystray.MenuItem('Open Task List', self.open_task_list),
            pystray.MenuItem('Walk around', self.toggle_walk, checked=lambda item: self.walk_enabled),
            # Text is a callable so the star rating is recomputed each time the
            # menu is opened, instead of being frozen at three stars.
            pystray.MenuItem(lambda item: f'Happiness: {self.happiness_stars()}', self.show_happiness),
            pystray.MenuItem('Quit Bloo Dango', self.quit_app)
        )
        self.icon = pystray.Icon("Bloo Dango", self.image, "Bloo Dango", menu)

    def happiness_stars(self):
        stars = min(5, storage.list_done_today())
        return '★' * stars + '☆' * (5 - stars)

    def run(self):
        import threading
        threading.Thread(target=self.icon.run, daemon=True).start()

    def stop(self):
        self.icon.stop()

    # --- Menu callbacks. These run on pystray's own thread, so anything that
    # --- touches Qt widgets has to hop to the GUI thread via a signal.

    def quick_add(self):
        self.signals.quick_add_requested.emit()

    def _show_quick_add_dialog(self):
        """Slot to show quick add dialog in GUI thread"""
        dialog = QuickAddDialog()
        if show_dialog(dialog) == QDialog.Accepted:
            title, due = dialog.get_inputs()
            if title:
                storage.add_task(title, due)
                # Trigger purr animation
                self.bloo.set_mood('purr')

    def open_task_list(self):
        self.signals.task_list_requested.emit()

    def _show_task_list_dialog(self):
        """Slot to show the task list in GUI thread"""
        show_dialog(TaskListDialog(self.bloo))

    def toggle_walk(self, item):
        self.walk_enabled = not self.walk_enabled
        # Update the menu check state
        self.icon.update_menu()

    def show_happiness(self, item):
        # Read the count here (plain sqlite, safe off-thread) and hand it to
        # the GUI thread for display.
        done_today = storage.list_done_today()
        self.signals.show_happiness_requested.emit(done_today)

    def _show_happiness(self, done_today):
        """Slot to show happiness message in GUI thread"""
        stars = min(5, done_today)
        happiness = '★' * stars + '☆' * (5 - stars)
        box = QMessageBox()
        box.setWindowTitle("Happiness")
        box.setText(f"Today's happiness: {happiness}\nTasks completed today: {done_today}")
        show_dialog(box)

    def quit_app(self):
        self.signals.quit_requested.emit()

    def _quit_app(self):
        """Slot to quit application in GUI thread"""
        self.icon.stop()
        if self.on_quit is not None:
            self.on_quit()
        # Bloo Dango widget will close when app quits
        from PyQt5.QtWidgets import QApplication
        QApplication.quit()
