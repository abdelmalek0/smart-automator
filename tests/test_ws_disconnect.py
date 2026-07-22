import unittest
from unittest.mock import AsyncMock, MagicMock

from smart_automator.server.app import _safe_ws_send_json


class SafeWsSendTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_false_on_disconnect(self):
        websocket = MagicMock()
        websocket.send_json = AsyncMock(side_effect=RuntimeError("disconnect"))
        sent = await _safe_ws_send_json(websocket, {"type": "ping"})
        self.assertFalse(sent)

    async def test_returns_true_on_success(self):
        websocket = MagicMock()
        websocket.send_json = AsyncMock()
        sent = await _safe_ws_send_json(websocket, {"type": "ping"})
        self.assertTrue(sent)


if __name__ == "__main__":
    unittest.main()
