import asyncio
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from smart_automator.logging_setup import setup_logging, shutdown_logging


class TestLoggingSetup(unittest.TestCase):
    def test_intercepted_logs_use_logger_name_not_call_handlers(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "backend.log"
            with patch.dict(
                "os.environ",
                {"LOG_DIR": str(tmp), "LOG_LEVEL": "INFO"},
                clear=False,
            ):
                import smart_automator.logging_setup as logging_setup

                logging_setup._configured = False
                setup_logging()
                logging.getLogger("smart_automator.test").info("attribution check")
                asyncio.run(shutdown_logging())
                logging_setup._configured = False

            content = log_file.read_text(encoding="utf-8")
            self.assertIn("smart_automator.test", content)
            self.assertNotIn("logging:callHandlers", content)


if __name__ == "__main__":
    unittest.main()
