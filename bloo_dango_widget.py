import os
import random
import math
from PyQt5.QtWidgets import QWidget, QLabel, QApplication, QMenu
from PyQt5.QtGui import QMovie, QCursor
from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, QPoint
from PIL import Image, ImageDraw

# Bump this whenever generate_sprite() changes so existing (stale) GIFs on disk
# get regenerated instead of silently keeping the old artwork.
SPRITE_VERSION = 4

# Milliseconds per animation frame - must match the duration passed to _save_gif.
FRAME_MS = 120

# Moods that play a single pass and then fall back to idle.
ONE_SHOT_MOODS = ('blink', 'remind', 'purr')

# How far the pointer must travel before a left click counts as a drag rather
# than a click that opens the task list.
DRAG_THRESHOLD_PX = 5


def _mix(color_a, color_b, t):
    """Blend two RGB(A) colors, keeping color_a's alpha.

    Glow and pulse effects have to be expressed as color changes, not alpha
    changes: ImageDraw does not alpha-blend when it draws onto an RGBA image
    (it overwrites the destination pixels, alpha included), and GIF only
    stores 1-bit alpha anyway. Lowering alpha therefore punched transparent
    holes through the character instead of fading anything.
    """
    return tuple(
        int(a + (b - a) * t) for a, b in zip(color_a[:3], color_b[:3])
    ) + (color_a[3] if len(color_a) > 3 else 255,)


def _save_gif(frames, path, duration=100, loop=0, alpha_threshold=80):
    """
    Save RGBA frames as an animated GIF.

    GIF only supports 1-bit alpha (a pixel is either fully opaque or fully
    transparent — never partially see-through) and, if you let Pillow pick
    a palette per frame automatically, each frame can end up with a
    DIFFERENT color-to-index mapping. Combined, those two facts were
    causing a real bug: our soft blurred glow halo (which fades gradually
    to transparent) was getting flattened into a solid, hard-edged grey
    block that changed slightly frame to frame — visible as a stray dark
    box artifact on top of the character.

    The fix has two parts:
      1. Binarize alpha ourselves (threshold it to 0 or 255) so we control
         exactly which pixels vanish, instead of leaving Pillow to guess.
      2. Build ONE shared color palette from every frame combined, and
         reserve a single dedicated palette index purely for "transparent"
         — every frame then agrees on exactly what "transparent" means.
    """
    TRANSPARENT_INDEX = 255

    # binarize alpha on every frame first
    flattened = []
    for f in frames:
        alpha_bin = f.split()[3].point(lambda a: 255 if a > alpha_threshold else 0)
        rgb = f.convert("RGB")
        flattened.append((rgb, alpha_bin))

    # build one shared palette from all frames' RGB content combined
    w, h = flattened[0][0].size
    strip = Image.new("RGB", (w, h * len(flattened)))
    for i, (rgb, _) in enumerate(flattened):
        strip.paste(rgb, (0, i * h))
    palette_source = strip.quantize(colors=TRANSPARENT_INDEX, method=Image.MEDIANCUT)

    # Quantize every frame to that shared palette, then rewrite the index
    # buffer directly: opaque pixels are pushed off the reserved index (the
    # quantizer can otherwise land an ordinary colour on index 255 and punch
    # a stray transparent pixel through the artwork), and transparent pixels
    # are set to it.
    gif_frames = []
    for rgb, alpha_bin in flattened:
        quantized = rgb.quantize(palette=palette_source, dither=Image.NONE)
        indices = bytearray(quantized.tobytes())
        opaque = alpha_bin.tobytes()
        for i in range(len(indices)):
            if opaque[i]:
                if indices[i] == TRANSPARENT_INDEX:
                    indices[i] = TRANSPARENT_INDEX - 1
            else:
                indices[i] = TRANSPARENT_INDEX
        quantized.frombytes(bytes(indices))
        gif_frames.append(quantized)

    gif_frames[0].save(
        path, "GIF", save_all=True, append_images=gif_frames[1:],
        duration=duration, loop=loop, disposal=2,
        transparency=TRANSPARENT_INDEX,
    )


class BlooDango(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bloo Dango")
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool  # No taskbar entry
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)

        # Label to display the animation
        self.label = QLabel(self)
        self.label.setFixedSize(128, 128)
        self.label.move(0, 0)  # Top-left of the widget

        # Current movie and mood
        self.movie = None
        self.current_mood = None
        self._pending_one_shot = None

        # State for wandering. One long-lived animation is reused for every
        # move: a local QPropertyAnimation is garbage collected as soon as the
        # method returns (killing the animation mid-flight), while starting it
        # with DeleteWhenStopped destroys the C++ object the moment it
        # finishes and leaves this attribute dangling - touching it afterwards
        # raised "wrapped C/C++ object ... has been deleted".
        self._anim = QPropertyAnimation(self, b"pos", self)
        self._anim.setDuration(2000)
        self.home_pos = None
        self.wander_timer = QTimer(self)
        self.wander_timer.timeout.connect(self.start_wander)
        self.wander_timer.start(30000)  # 30 seconds

        # Tray icon reference (set by main.py after tray creation)
        self.tray_icon = None

        # Mouse drag variables
        self.dragging = False
        self.drag_moved = False
        self.drag_position = QPoint()
        self.press_position = QPoint()

        # Guards against opening a second dialog on top of an open one
        self._dialog_open = False

        # Generate sprites if missing
        self.generate_sprites_if_missing()

        # Start with idle animation
        self.set_mood('idle')

        # Set widget size to match label
        self.setFixedSize(128, 128)

        # Position at bottom-right of primary screen
        self.position_bottom_right()
        # Ensure window is visible and on top
        self.raise_()

        # Kick off the blink cycle (each blink schedules the next one).
        QTimer.singleShot(random.randint(4000, 9000), self.do_blink)

    def _available_geometry(self):
        """Available desktop rect for the screen Bloo Dango is currently on."""
        screen = self.screen() if hasattr(self, 'screen') else None
        if screen is None:
            screen = QApplication.primaryScreen()
        return screen.availableGeometry()

    def position_bottom_right(self):
        # availableGeometry() is in virtual-desktop coordinates, so on a
        # multi-monitor setup its origin is not necessarily (0, 0) - using
        # width()/height() alone would place Bloo Dango on the wrong screen.
        geo = QApplication.primaryScreen().availableGeometry()
        x = geo.right() - self.width() - 20
        y = geo.bottom() - self.height() - 20
        self.move(x, y)
        self.home_pos = QPoint(x, y)

    def _clamp_to_screen(self, point):
        """Keep the whole widget inside the visible desktop area."""
        geo = self._available_geometry()
        x = max(geo.left(), min(point.x(), geo.right() - self.width()))
        y = max(geo.top(), min(point.y(), geo.bottom() - self.height()))
        return QPoint(x, y)

    def generate_sprites_if_missing(self):
        """Generate all sprite GIFs if they don't exist (or are out of date)."""
        sprites_dir = os.path.join(os.path.dirname(__file__), 'sprites')
        os.makedirs(sprites_dir, exist_ok=True)

        version_path = os.path.join(sprites_dir, '.version')
        try:
            with open(version_path) as f:
                current_version = int(f.read().strip())
        except (OSError, ValueError):
            current_version = 0
        stale = current_version != SPRITE_VERSION

        moods = {
            'idle': 4,
            'blink': 2,
            'happy': 4,
            'remind': 4,
            'sleep': 2,
            'purr': 3
        }

        for mood, frame_count in moods.items():
            path = os.path.join(sprites_dir, f"{mood}.gif")
            if stale or not os.path.exists(path):
                self.generate_sprite(mood, frame_count, path)

        if stale:
            try:
                with open(version_path, 'w') as f:
                    f.write(str(SPRITE_VERSION))
            except OSError:
                pass

    def generate_sprite(self, mood, frame_count, output_path):
        """Generate a sprite GIF for the given mood using PIL."""
        width = height = 128
        frames = []

        # Base colors
        body_color = (170, 220, 255, 220)  # icy blue translucent
        belly_color = (120, 230, 255, 240)  # glowing cyan
        eye_color = (10, 26, 58, 255)  # dark navy
        eye_highlight = (255, 255, 255, 255)  # white
        fang_color = (255, 255, 255, 200)  # off-white
        plate_color = (150, 200, 255, 220)  # slightly brighter blue
        # Frost specks are opaque: at alpha 80 they fell below the GIF alpha
        # threshold and became transparent pinholes in the body.
        frost_color = (236, 250, 255, 255)  # tiny frost particles
        glow_color_bright = (235, 255, 255)  # what glows fade towards

        # Deterministic sparkle placement so regenerating sprites is stable
        # and so we don't disturb the global RNG used for wandering.
        rng = random.Random(mood)

        for i in range(frame_count):
            # One full sine cycle spread across the frames. (Using
            # sin(i * pi) here is always ~0 for integer i, which made every
            # per-frame motion below a no-op - the animations never moved.)
            phase = 2 * math.pi * i / frame_count

            # Mood-driven adjustments to the BASE body, computed up front.
            # Previously these were painted after the eyes, so the redrawn
            # body covered the face completely.
            body_shift_x = 0
            body_fill = body_color
            if mood == 'purr':
                body_shift_x = int(3 * math.sin(phase))
            elif mood == 'remind':
                body_shift_x = int(6 * math.sin(phase))
            elif mood == 'sleep':
                # Soft breathing glow, as a brightness shift.
                body_fill = _mix(body_color, glow_color_bright, 0.15 * (1 + math.sin(phase)))

            eye_style = 'open'
            if mood == 'blink' and i == 1:
                eye_style = 'closed'
            elif mood == 'sleep':
                eye_style = 'closed'
            elif mood == 'purr' and i < 2:
                eye_style = 'squint'

            img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img, 'RGBA')

            # Draw body (chubby oval). The base size is chosen so that the
            # body, its dorsal plates, the tail (including its wag) and the
            # mouth all fit inside the 128px canvas - the previous 100x120
            # body ran 30px off the bottom edge, which clipped the character
            # and pushed the fang and mouth outside the image entirely.
            body_width = int(88 * (1.0 + 0.03 * math.sin(phase)))  # breathing
            body_height = int(82 * (1.0 + 0.03 * math.sin(phase)))
            body_x = (width - body_width) // 2 + body_shift_x
            body_y = int(height * 0.26)  # slightly above center
            draw.ellipse(
                [body_x, body_y, body_x + body_width, body_y + body_height],
                fill=body_fill
            )

            # Belly patch (oval)
            belly_width = int(body_width * 0.8)
            belly_height = int(body_height * 0.6)
            belly_x = body_x + (body_width - belly_width) // 2
            belly_y = body_y + int(body_height * 0.2)
            # Radial glow: rings fading from the belly colour out to the body
            # colour (fading via alpha would just cut holes instead).
            for j in range(3):
                ring_color = _mix(belly_color, body_color, 0.3 * (j + 1))
                draw.ellipse(
                    [belly_x - j*2, belly_y - j*2, belly_x + belly_width + j*2, belly_y + belly_height + j*2],
                    outline=ring_color
                )
            # Fill belly - 'happy' pulses the glow brighter
            belly_fill = belly_color
            if mood == 'happy':
                belly_fill = _mix(belly_color, glow_color_bright, 0.5 * (1 + math.sin(phase)))
            draw.ellipse(
                [belly_x, belly_y, belly_x + belly_width, belly_y + belly_height],
                fill=belly_fill
            )

            # Dorsal plates (3 triangles on the back)
            for k in range(3):
                plate_x = body_x + int(body_width * (0.2 + k * 0.3))
                plate_y = body_y - 10
                plate_size = 15 - k*3
                points = [
                    (plate_x, plate_y),
                    (plate_x - plate_size//2, plate_y + plate_size),
                    (plate_x + plate_size//2, plate_y + plate_size)
                ]
                draw.polygon(points, fill=plate_color)

            # Tail (small with crystal tip) - 'happy' wags it side to side
            wag_offset = int(6 * math.sin(phase)) if mood == 'happy' else 0
            tail_start_x = body_x + body_width - 8 + wag_offset
            tail_start_y = body_y + int(body_height * 0.7)
            tail_end_x = tail_start_x + 12
            tail_end_y = tail_start_y - 10
            draw.line(
                [tail_start_x, tail_start_y, tail_end_x, tail_end_y],
                fill=body_color, width=6
            )
            # Crystal tip. Its base is a little wider than the tail stroke so
            # the two shapes overlap - butting them exactly together left a
            # single transparent pixel at the join, which shows the desktop
            # through the tail.
            draw.polygon(
                [(tail_end_x, tail_end_y), (tail_end_x - 6, tail_end_y + 9), (tail_end_x + 6, tail_end_y + 9)],
                fill=plate_color
            )

            # Frost particles (tiny white circles)
            for _ in range(5):
                fx = rng.randint(body_x, body_x + body_width)
                fy = rng.randint(body_y, body_y + body_height)
                draw.ellipse(
                    [fx-1, fy-1, fx+1, fy+1],
                    fill=frost_color
                )

            # Eyes (large, sparkly) - drawn once, in the right style, so
            # nothing paints over them afterwards.
            # 0.15/0.5 with a 26px eye leaves a gap between the eyes; at the
            # old 0.2/0.5 spacing the two eyes touched (and overlapped once
            # the body narrowed while breathing).
            eye_size = 26
            eye_y = body_y + int(body_height * 0.3)
            left_eye_x = body_x + int(body_width * 0.15)
            right_eye_x = body_x + int(body_width * 0.5)
            for eye_x in (left_eye_x, right_eye_x):
                if eye_style == 'closed':
                    draw.line(
                        [eye_x, eye_y + eye_size // 2, eye_x + eye_size, eye_y + eye_size // 2],
                        fill=eye_color, width=2
                    )
                elif eye_style == 'squint':
                    draw.ellipse(
                        [eye_x, eye_y + 7, eye_x + eye_size, eye_y + eye_size - 7],
                        fill=eye_color
                    )
                    draw.ellipse(
                        [eye_x + 7, eye_y + 11, eye_x + 12, eye_y + 16],
                        fill=eye_highlight
                    )
                else:
                    draw.ellipse(
                        [eye_x, eye_y, eye_x + eye_size, eye_y + eye_size],
                        fill=eye_color
                    )
                    # The highlight is a small dot; the old 'purr' branch sized
                    # it as eye_y..eye_y + eye_size, which blew it up to cover
                    # the whole eye.
                    draw.ellipse(
                        [eye_x + 7, eye_y + 7, eye_x + 12, eye_y + 12],
                        fill=eye_highlight
                    )

            # Tiny fang (peeking out of the mouth, just off to one side)
            fang_y = body_y + int(body_height * 0.78)
            fang_x = body_x + int(body_width * 0.5) - 8
            draw.polygon(
                [(fang_x, fang_y), (fang_x - 4, fang_y + 7), (fang_x + 4, fang_y + 7)],
                fill=fang_color
            )

            if mood == 'remind':
                # Open mouth (small roar) on the first half of the animation
                mouth_open = i < frame_count // 2
                mouth_y = body_y + int(body_height * 0.85)
                mouth_width = 20
                mouth_height = 10 if mouth_open else 2
                mouth_x = body_x + int(body_width * 0.5) - mouth_width//2
                if mouth_open:
                    draw.arc(
                        [mouth_x, mouth_y, mouth_x + mouth_width, mouth_y + mouth_height],
                        start=0, end=180, fill=eye_color, width=2
                    )
                else:
                    draw.line(
                        [mouth_x, mouth_y + mouth_height//2, mouth_x + mouth_width, mouth_y + mouth_height//2],
                        fill=eye_color, width=2
                    )

            frames.append(img)

        # Save as GIF using our custom function to handle transparency correctly
        _save_gif(frames, output_path, duration=FRAME_MS, loop=0)

    def set_mood(self, mood):
        """Change the current animation mood."""
        # Re-entering a looping mood would otherwise restart it from frame 0
        # every time the scheduler ticks.
        if mood == self.current_mood and mood not in ONE_SHOT_MOODS and self.movie is not None:
            return

        sprite_path = os.path.join(os.path.dirname(__file__), 'sprites', f"{mood}.gif")
        if not os.path.exists(sprite_path):
            return

        if self.movie is not None:
            try:
                self.movie.frameChanged.disconnect(self._on_one_shot_frame)
            except TypeError:
                pass
            self.movie.stop()

        movie = QMovie(sprite_path)
        if not movie.isValid():
            return

        self.movie = movie
        self.current_mood = mood
        self.label.setMovie(movie)

        # The sprites are saved as infinitely looping GIFs, so QMovie never
        # emits finished() - watching frameChanged is the only reliable way to
        # notice a one-shot animation has played through.
        if mood in ONE_SHOT_MOODS:
            self._pending_one_shot = mood
            movie.frameChanged.connect(self._on_one_shot_frame)
        else:
            self._pending_one_shot = None

        movie.start()

    def _on_one_shot_frame(self, frame_number):
        if self.movie is None or frame_number < self.movie.frameCount() - 1:
            return
        try:
            self.movie.frameChanged.disconnect(self._on_one_shot_frame)
        except TypeError:
            pass
        # Let the last frame stay up for its full duration before reverting.
        QTimer.singleShot(FRAME_MS, self._return_to_idle)

    def _return_to_idle(self):
        if self.current_mood == self._pending_one_shot:
            self._pending_one_shot = None
            self.set_mood('idle')

    def do_blink(self):
        """Trigger a single blink from idle state."""
        if self.current_mood == 'idle':
            self.set_mood('blink')
        # Always schedule the next attempt, otherwise a single blink landing
        # during another mood would end the blink cycle permanently.
        QTimer.singleShot(random.randint(8000, 15000), self.do_blink)

    def start_wander(self):
        """Wander a short random distance away from home."""
        if self.tray_icon is not None and not self.tray_icon.walk_enabled:
            return
        if self.dragging:
            return
        if self._anim.state() == QPropertyAnimation.Running:
            return
        offset = QPoint(random.randint(-80, 80), random.randint(-80, 80))
        self._animate_to(self.pos() + offset)
        # Head back home once the outbound move has finished.
        QTimer.singleShot(4000, self.wander_back)

    def wander_back(self):
        """Animate back to the home position."""
        if self.dragging or self.home_pos is None:
            return
        self._animate_to(self.home_pos)

    def _animate_to(self, target):
        # Starting from self.pos() (rather than a recomputed offset) avoids the
        # widget teleporting before the animation begins.
        self._anim.stop()
        self._anim.setStartValue(self.pos())
        self._anim.setEndValue(self._clamp_to_screen(target))
        self._anim.start()

    # Mouse event handlers for dragging
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.drag_moved = False
            self.press_position = event.globalPos()
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            if self._anim.state() == QPropertyAnimation.Running:
                self._anim.stop()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.dragging:
            # Only count it as a drag once the pointer has actually travelled,
            # so a click with a shaky hand still opens the task list.
            if (event.globalPos() - self.press_position).manhattanLength() > DRAG_THRESHOLD_PX:
                self.drag_moved = True
            if self.drag_moved:
                self.move(event.globalPos() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            was_drag = self.drag_moved
            self.dragging = False
            self.drag_moved = False
            # Wherever the user parks Bloo Dango becomes the new home base.
            self.home_pos = self.pos()
            if not was_drag:
                # A plain left click opens the task list. Deferred so the
                # modal dialog does not run inside this event handler.
                QTimer.singleShot(0, self.open_task_list)
            event.accept()

    def mouseDoubleClickEvent(self, event):
        # The single-click handler already opened the list; swallow this so a
        # fast double click does not queue a second dialog.
        event.accept()

    def contextMenuEvent(self, event):
        """Right-click menu, so the tray icon is never needed for daily use."""
        from tray import TaskListDialog, QuickAddDialog, show_dialog  # noqa: F401
        import storage

        menu = QMenu(self)
        add_action = menu.addAction("Quick Add Task...")
        list_action = menu.addAction("Open Task List")
        menu.addSeparator()
        walk_action = menu.addAction("Walk around")
        walk_action.setCheckable(True)
        if self.tray_icon is not None:
            walk_action.setChecked(self.tray_icon.walk_enabled)
        else:
            walk_action.setEnabled(False)
        happiness_action = menu.addAction(
            f"Happiness: {self._happiness_stars()}"
        )
        menu.addSeparator()
        quit_action = menu.addAction("Quit Bloo Dango")

        chosen = menu.exec_(event.globalPos())
        if chosen is None:
            return
        if chosen is add_action:
            self.quick_add_task()
        elif chosen is list_action:
            self.open_task_list()
        elif chosen is walk_action and self.tray_icon is not None:
            self.tray_icon.walk_enabled = walk_action.isChecked()
            self.tray_icon.icon.update_menu()
        elif chosen is happiness_action:
            if self.tray_icon is not None:
                self.tray_icon._show_happiness(storage.list_done_today())
        elif chosen is quit_action:
            self.quit_app()
        event.accept()

    def _happiness_stars(self):
        import storage
        stars = min(5, storage.list_done_today())
        return '★' * stars + '☆' * (5 - stars)

    def open_task_list(self):
        """Show the task list, guarding against stacking up dialogs."""
        if self._dialog_open:
            return
        from tray import TaskListDialog, show_dialog
        self._dialog_open = True
        try:
            show_dialog(TaskListDialog(self))
        except Exception as e:
            print(f"Error opening task list: {e}")
        finally:
            self._dialog_open = False

    def quick_add_task(self):
        """Show the quick add dialog straight from the character."""
        if self._dialog_open:
            return
        from PyQt5.QtWidgets import QDialog
        from tray import QuickAddDialog, show_dialog
        import storage
        self._dialog_open = True
        try:
            dialog = QuickAddDialog(self)
            if show_dialog(dialog) == QDialog.Accepted:
                title, due = dialog.get_inputs()
                if title:
                    storage.add_task(title, due)
                    self.set_mood('purr')
        except Exception as e:
            print(f"Error adding task: {e}")
        finally:
            self._dialog_open = False

    def quit_app(self):
        if self.tray_icon is not None:
            self.tray_icon.quit_app()
        else:
            QApplication.quit()

    def enterEvent(self, event):
        # Change cursor to pointing hand when hovered
        self.setCursor(QCursor(Qt.PointingHandCursor))

    def leaveEvent(self, event):
        self.setCursor(QCursor(Qt.ArrowCursor))

