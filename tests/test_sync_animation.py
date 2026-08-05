"""Tests for the startup sync spinner's thread lifetime.

The spinner runs on its own thread while main_loop pulls from Google. Two
things must hold, or a failed sync leaves the app hung instead of erroring:

- the thread must be a daemon, so the interpreter can always exit
- the spinner must be stopped even when the wrapped work raises

Before this was fixed, main_loop called start_sync_animation(), then
sync_from_google(), then stop_sync_animation() as three bare statements. A
raising sync skipped the stop, `syncing` stayed True, the non-daemon thread
looped forever, and the process never exited — the app looked frozen.

The curses calls the animation touches are stubbed out so these run headless.
"""

import threading
import unittest

import tasks_tui.ui_manager as um


class _AnimationCase(unittest.TestCase):
    """Builds a UIManager with curses stubbed and guarantees thread cleanup."""

    def setUp(self):
        self._real = {
            name: getattr(um, name)
            for name in ("getmaxyx", "mvwaddstr", "refresh", "nodelay")
        }
        um.getmaxyx = lambda stdscr: (40, 120)
        um.mvwaddstr = lambda *a, **k: None
        um.refresh = lambda *a, **k: None
        um.nodelay = lambda *a, **k: None
        self.addCleanup(self._restore)

        self.ui = um.UIManager.__new__(um.UIManager)  # skip the curses init
        self.ui.stdscr = None
        self.ui.syncing = False
        self.addCleanup(self._stop_thread)

    def _restore(self):
        for name, fn in self._real.items():
            setattr(um, name, fn)

    def _stop_thread(self):
        """Never leave a live spinner behind, even if a test fails."""
        self.ui.syncing = False
        thread = getattr(self.ui, "animation_thread", None)
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)


class TestAnimationThreadIsDaemon(_AnimationCase):
    def test_thread_does_not_block_interpreter_exit(self):
        self.ui.start_sync_animation()
        self.assertTrue(
            self.ui.animation_thread.daemon,
            "a non-daemon spinner thread keeps the process alive forever",
        )


class TestSyncAnimationContextManager(_AnimationCase):
    def test_spinner_stops_when_the_block_completes(self):
        with self.ui.sync_animation():
            self.assertTrue(self.ui.syncing)
        self.assertFalse(self.ui.syncing)
        self.assertFalse(self.ui.animation_thread.is_alive())

    def test_spinner_stops_when_the_block_raises(self):
        with self.assertRaises(RuntimeError):
            with self.ui.sync_animation():
                raise RuntimeError("simulated sync failure")

        self.assertFalse(
            self.ui.syncing, "syncing flag survived an exception in the block"
        )
        self.assertFalse(
            self.ui.animation_thread.is_alive(),
            "spinner thread survived an exception in the block",
        )

    def test_exception_from_the_block_still_propagates(self):
        with self.assertRaises(ValueError):
            with self.ui.sync_animation():
                raise ValueError("must reach the caller")

    def test_no_spinner_thread_outlives_the_block(self):
        before = threading.active_count()
        with self.ui.sync_animation():
            pass
        self.assertEqual(threading.active_count(), before)


if __name__ == "__main__":
    unittest.main()
