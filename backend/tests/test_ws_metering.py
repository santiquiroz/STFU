import asyncio
import json
import threading
from unittest.mock import AsyncMock
from fastapi import WebSocketDisconnect

from stfu.api.ws import metering_ws


def test_metering_ws_runs_get_metrics_off_event_loop():
    """Verify get_metrics is called on a separate thread, not blocking the event loop."""
    main_thread_id = threading.get_ident()
    metrics_thread_id = None
    send_call_count = 0

    def get_metrics_tracking():
        nonlocal metrics_thread_id
        metrics_thread_id = threading.get_ident()
        return {"status": "ok", "value": 42}

    async def run_test():
        nonlocal send_call_count
        # Create a mock WebSocket
        websocket = AsyncMock()

        async def mock_send_text_impl(text):
            nonlocal send_call_count
            send_call_count += 1
            # After first send, raise WebSocketDisconnect to exit the loop
            if send_call_count == 1:
                raise WebSocketDisconnect(1000)

        websocket.send_text.side_effect = mock_send_text_impl

        # Run metering_ws
        await metering_ws(websocket, get_metrics_tracking)

        # Verify send_text was called once
        assert send_call_count == 1

        # Verify get_metrics was called
        assert metrics_thread_id is not None

        # Verify get_metrics ran on a different thread (thread pool)
        assert metrics_thread_id != main_thread_id

        # Verify the data shape was preserved
        websocket.accept.assert_called_once()
        websocket.send_text.assert_called_once()
        sent_data = json.loads(websocket.send_text.call_args[0][0])
        assert sent_data == {"status": "ok", "value": 42}

    asyncio.run(run_test())
