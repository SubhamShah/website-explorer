import asyncio
import tempfile
import unittest
from pathlib import Path

from app import store
from app.crawler import (
    ScanControl,
    _BACKGROUND_TASKS,
    _SCAN_CONTROLS,
    cancel_scan,
)
from app.main import pause_active_scan, resume_paused_scan


class ScanControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_db_path = store.DB_PATH
        self.temp_dir = tempfile.TemporaryDirectory()
        store.DB_PATH = Path(self.temp_dir.name) / "test-explorer.db"
        self.scan = store.create_scan("https://example.com", 25, 3)
        store.update_scan(self.scan["id"], status="running")

        resume_event = asyncio.Event()
        resume_event.set()
        self.task = asyncio.create_task(asyncio.sleep(60))
        _BACKGROUND_TASKS[self.scan["id"]] = self.task
        _SCAN_CONTROLS[self.scan["id"]] = ScanControl(resume_event=resume_event)

    async def asyncTearDown(self) -> None:
        await cancel_scan(self.scan["id"])
        store.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    async def test_pause_and_resume_keep_the_same_active_task(self) -> None:
        original_task = _BACKGROUND_TASKS[self.scan["id"]]

        paused = await pause_active_scan(self.scan["id"])

        self.assertEqual(paused["status"], "paused")
        self.assertFalse(_SCAN_CONTROLS[self.scan["id"]].resume_event.is_set())
        self.assertIs(_BACKGROUND_TASKS[self.scan["id"]], original_task)

        resumed = await resume_paused_scan(self.scan["id"])

        self.assertEqual(resumed["status"], "running")
        self.assertTrue(_SCAN_CONTROLS[self.scan["id"]].resume_event.is_set())
        self.assertIs(_BACKGROUND_TASKS[self.scan["id"]], original_task)


if __name__ == "__main__":
    unittest.main()
