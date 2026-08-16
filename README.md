# Bloo Dango Desktop Buddy

A cute, floating desktop companion named Bloo Dango that helps you manage tasks with reminders and a system tray interface.
This app displays an animated, translucent character on your desktop.

## Features

- **Floating Character**: Bloo Dango appears as a transparent, frameless window on your desktop.
- **Task Management**: Add, view, mark as done, and delete tasks by clicking Bloo Dango directly (left-click for the list, right-click for the menu). The system tray offers the same menu as a backup.
- **Reminders**: Get notified when tasks are due with Windows toast notifications and animation.
- **System Tray**: Control the app with a right-click menu (Quick Add, Task List, Walk Around toggle, Happiness indicator, Quit).
- **Animations**: Multiple moods (idle, blink, happy, remind, sleep, purr) with smooth transitions.
- **Interactive**: Drag to move, left-click for the task list, right-click for the menu.
- **Auto-generated Sprites**: All character animations are generated on first run using Pillow - no external assets needed. They are regenerated automatically whenever the sprite code changes (tracked by `sprites/.version`).

## Requirements

- Windows 10/11
- Python 3.8+

## Installation

1. Clone or download this repository.
2. Create a virtual environment (optional but recommended):
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```
3. Install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

Run the application:
```bash
python main.py
```

- Your buddy will appear in the bottom-right of your primary screen.
- **Left-click the buddy** to open the task list, where you can add, complete and delete tasks.
- **Right-click the buddy** for the full menu (Quick Add, Task List, Walk Around, Happiness, Quit).
- Drag the buddy to move it; that spot becomes its new home base.
- The system tray icon offers the same menu, but you never need it.
- The character will wander randomly (if enabled) and blink periodically.
- When a task is due, your buddy will show a reminder animation and a toast notification. Each task only reminds you once.
- Sleep mode is currently disabled, so your buddy stays awake around the clock.

## Project Structure

```
desktop_buddy/
├── main.py                 # Entry point
├── bloo_dango_widget.py     # The transparent floating character
├── tray.py                 # System tray icon + right-click menu
├── storage.py              # SQLite task CRUD
├── scheduler.py            # APScheduler periodic check
├── notifier.py             # Windows toast notifications
├── sprites/                # Auto-generated animation frames
│   ├── idle.gif
│   ├── blink.gif
│   ├── happy.gif
│   ├── remind.gif
│   ├── sleep.gif
│   └── purr.gif
├── assets/
│   └── icon.png            # Tray icon (auto-generated if missing)
└── data/
    └── tasks.db            # SQLite database (auto-created)
```

## How It Works

- **main.py**: Initializes the app, database, desktop buddy widget, tray icon, and scheduler.
- **bloo_dango_widget.py**: Handles the visual display, animations, mouse interactions, and mood state machine.
- **tray.py**: Manages the system tray icon and menu using pystray.
- **storage.py**: SQLite database for task persistence.
- **scheduler.py**: Uses APScheduler to check for due tasks and manage sleep/wake cycles.
- **notifier.py**: Sends Windows toast notifications via plyer.

## Customization

- Adjust sprite generation in `bloo_dango_widget.py` if you want to change the appearance.
- Modify animation durations or behavior in the same file.
- Change check intervals in `scheduler.py`.

## License

MIT