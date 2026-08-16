from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from PyQt5.QtCore import QObject, pyqtSignal
from datetime import datetime
import storage

# How often to look for due tasks. The old 30 minute interval meant a reminder
# could land half an hour after the task was actually due.
CHECK_INTERVAL_MINUTES = 1


class SchedulerSignals(QObject):
    remind_requested = pyqtSignal(str)


def parse_due(due):
    """Parse a stored due string, tolerating the older 'YYYY-MM-DD HH:MM' form."""
    if not due:
        return None
    try:
        return datetime.fromisoformat(due)
    except ValueError:
        for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
            try:
                return datetime.strptime(due, fmt)
            except ValueError:
                continue
    return None


class Scheduler:
    def __init__(self, bloo_widget):
        self.bloo = bloo_widget
        self.signals = SchedulerSignals()
        self.signals.remind_requested.connect(self.bloo.set_mood)
        self.scheduler = BackgroundScheduler()
        self.sleep_mode = False
        # Task ids already reminded about, so an overdue task doesn't fire a
        # toast on every single check.
        self._reminded = set()

        # Job 1: look for due tasks
        self.scheduler.add_job(
            self.check_due,
            IntervalTrigger(minutes=CHECK_INTERVAL_MINUTES),
            id='check_due',
            replace_existing=True
        )

        # Job 2: sleep_check every 5 minutes
        self.scheduler.add_job(
            self.sleep_check,
            IntervalTrigger(minutes=5),
            id='sleep_check',
            replace_existing=True
        )

    def start(self):
        self.scheduler.start()

    def shutdown(self):
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def check_due(self):
        """Find the oldest pending task that is due now or overdue."""
        try:
            pending = storage.list_pending()
        except Exception as e:
            print(f"check_due: could not read tasks: {e}")
            return

        now = datetime.now()
        # Comparing real datetimes, not strings: the stored format and
        # datetime.isoformat() differ in their date/time separator, which made
        # every same-day task look overdue.
        due_tasks = []
        for task in pending:
            due = parse_due(task['due'])
            if due is not None and due <= now:
                due_tasks.append((due, task))

        pending_ids = {task['id'] for task in pending}
        # Forget tasks that were completed or deleted so they can remind again
        # if they ever come back.
        self._reminded &= pending_ids

        if not due_tasks:
            return

        due_tasks.sort(key=lambda pair: pair[0])
        for _, task in due_tasks:
            if task['id'] in self._reminded:
                continue
            self._reminded.add(task['id'])
            # Emit signal so the mood change happens on the GUI thread
            self.signals.remind_requested.emit('remind')
            from notifier import show_reminder
            show_reminder(task['title'])
            break  # one reminder per check

    def sleep_check(self):
        """Check if we should be in sleep mode based on time.
        Disabled to keep Bloo Dango awake at all times."""
        # Keep Bloo Dango awake: always idle, never sleep
        if self.sleep_mode:
            self.sleep_mode = False
            self.signals.remind_requested.emit('idle')
