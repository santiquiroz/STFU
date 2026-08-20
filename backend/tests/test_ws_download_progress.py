import asyncio
import json
from unittest.mock import AsyncMock
from stfu.api.ws import download_progress_ws


def test_download_progress_ws_streams_until_done():
    sent = []
    statuses = iter([
        {"status": "downloading", "downloaded": 0, "total": 100, "pct": 0.0, "error": None},
        {"status": "downloading", "downloaded": 50, "total": 100, "pct": 50.0, "error": None},
        {"status": "done", "downloaded": 100, "total": 100, "pct": 100.0, "error": None},
    ])

    def get_job_payload():
        return next(statuses)

    async def run_test():
        websocket = AsyncMock()

        async def mock_send_text(text):
            sent.append(json.loads(text))

        websocket.send_text.side_effect = mock_send_text

        await download_progress_ws(websocket, get_job_payload)

        websocket.accept.assert_called_once()
        websocket.close.assert_called_once()
        assert [p["status"] for p in sent] == ["downloading", "downloading", "done"]
        assert sent[-1]["pct"] == 100.0

    asyncio.run(run_test())


def test_download_progress_ws_stops_and_closes_on_error():
    sent = []
    error_payload = {"status": "error", "downloaded": 0, "total": None, "pct": None, "error": "boom"}

    def get_job_payload():
        return error_payload

    async def run_test():
        websocket = AsyncMock()

        async def mock_send_text(text):
            sent.append(json.loads(text))

        websocket.send_text.side_effect = mock_send_text

        await download_progress_ws(websocket, get_job_payload)

        assert sent == [error_payload]
        websocket.close.assert_called_once()

    asyncio.run(run_test())
