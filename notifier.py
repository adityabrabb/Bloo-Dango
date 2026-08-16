from plyer import notification


def show_reminder(task_title):
    """Show a Windows toast notification."""
    try:
        notification.notify(
            # The old title held a mangled byte sequence where an emoji used to
            # be, which rendered as garbage in the toast.
            title="Bloo Dango says...",
            message=task_title,
            app_name="Bloo Dango",
            timeout=8  # seconds
        )
    except Exception as e:
        # A failing toast backend must not take down the scheduler job.
        print(f"Could not show notification: {e}")
