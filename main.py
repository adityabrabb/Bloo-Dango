import sys

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer

from bloo_dango_widget import BlooDango
from tray import TrayIcon
from scheduler import Scheduler
from storage import init_db


def main():
    try:
        # Initialize the database
        init_db()

        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)  # Keep alive when window is closed

        # Create the Bloo Dango widget
        bloo = BlooDango()
        bloo.show()

        # Anything created here has to stay referenced for the lifetime of the
        # app - locals would be garbage collected as soon as this function
        # returned, taking the tray icon and scheduler with them.
        services = {}

        def start_tray_and_scheduler():
            scheduler = Scheduler(bloo)
            tray = TrayIcon(bloo, on_quit=scheduler.shutdown)
            bloo.tray_icon = tray
            tray.run()
            scheduler.start()
            services['tray'] = tray
            services['scheduler'] = scheduler

        def stop_services():
            scheduler = services.get('scheduler')
            if scheduler is not None:
                scheduler.shutdown()
            tray = services.get('tray')
            if tray is not None:
                tray.stop()

        # Make sure the scheduler thread and tray icon are torn down however
        # the app exits, not just via the tray's Quit item.
        app.aboutToQuit.connect(stop_services)

        # Start tray and scheduler once the event loop is running
        QTimer.singleShot(0, start_tray_and_scheduler)

        sys.exit(app.exec_())
    except Exception as e:
        print(f"Error in main: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
