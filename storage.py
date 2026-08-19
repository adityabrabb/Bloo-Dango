import sqlite3
import os
import sys
from datetime import datetime

# When running as a PyInstaller bundle, __file__ points to a temp extraction
# directory that is wiped on every launch.  Use the EXE's directory instead
# so the database persists across restarts.
if getattr(sys, 'frozen', False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(__file__)

DB_PATH = os.path.join(_BASE_DIR, 'data', 'tasks.db')

# Single canonical timestamp format for `due`, `created` and `completed`.
# Everything that writes a datetime into the DB must use this, otherwise the
# plain string comparisons used for due dates silently misbehave.
DT_FORMAT = '%Y-%m-%dT%H:%M:%S'


def now_str():
    return datetime.now().strftime(DT_FORMAT)


def _connect():
    return sqlite3.connect(DB_PATH)


def init_db():
    """Create the tasks table if it doesn't exist, and migrate old databases."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                due TEXT,  -- ISO datetime string, NULL ok
                priority INTEGER DEFAULT 0,  -- 0..2
                done INTEGER DEFAULT 0,
                created TEXT,
                completed TEXT  -- when it was marked done, NULL while pending
            )
        ''')
        # Databases created by earlier versions lack `completed`.
        columns = {row[1] for row in c.execute('PRAGMA table_info(tasks)')}
        if 'completed' not in columns:
            c.execute('ALTER TABLE tasks ADD COLUMN completed TEXT')
        conn.commit()
    finally:
        conn.close()


def add_task(title, due=None, priority=0):
    """Add a new task. `due` must be a DT_FORMAT string or None."""
    conn = _connect()
    try:
        c = conn.cursor()
        # `created` is written explicitly in local time; the old
        # CURRENT_TIMESTAMP default stored UTC, which broke "done today"
        # counting for anyone not on UTC.
        c.execute(
            'INSERT INTO tasks (title, due, priority, created) VALUES (?, ?, ?, ?)',
            (title, due, priority, now_str())
        )
        conn.commit()
        return c.lastrowid
    finally:
        conn.close()


def _row_to_dict(row):
    return {
        'id': row[0],
        'title': row[1],
        'due': row[2],
        'priority': row[3],
        'done': row[4],
        'created': row[5],
        'completed': row[6],
    }


def list_pending():
    """Return list of pending tasks as dicts, soonest due first."""
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(
            'SELECT id, title, due, priority, done, created, completed '
            'FROM tasks WHERE done=0 ORDER BY due IS NULL, due, id'
        )
        return [_row_to_dict(row) for row in c.fetchall()]
    finally:
        conn.close()


def list_done_today():
    """Count tasks completed today."""
    conn = _connect()
    try:
        c = conn.cursor()
        today = datetime.now().strftime('%Y-%m-%d')
        # Compare on the date prefix rather than SQLite's date(), so rows
        # written by older versions (with a space separator) still match.
        c.execute(
            'SELECT COUNT(*) FROM tasks '
            'WHERE done=1 AND completed IS NOT NULL AND substr(completed, 1, 10) = ?',
            (today,)
        )
        return c.fetchone()[0]
    finally:
        conn.close()


def mark_done(task_id):
    """Mark a task as done and record when."""
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(
            'UPDATE tasks SET done=1, completed=? WHERE id=?',
            (now_str(), task_id)
        )
        conn.commit()
    finally:
        conn.close()


def delete_task(task_id):
    """Delete a task."""
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute('DELETE FROM tasks WHERE id=?', (task_id,))
        conn.commit()
    finally:
        conn.close()
