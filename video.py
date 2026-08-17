from __future__ import annotations

import asyncio
import logging

from livekit import rtc

logger = logging.getLogger("speech.video")


class FrameBuffer:
    """Holds the most recently received frame from one subscribed video track.

    Populated continuously in the background, but nothing is sent anywhere
    until a tool explicitly reads latest_frame on demand — no continuous
    sampling into the realtime model.
    """

    def __init__(self) -> None:
        self.latest_frame: rtc.VideoFrame | None = None
        self._stream: rtc.VideoStream | None = None
        self._task: asyncio.Task | None = None

    def attach(self, track: rtc.Track) -> None:
        if self._task is not None:
            self._task.cancel()
        self._stream = rtc.VideoStream(track)
        self._task = asyncio.create_task(self._consume(), name="video-frame-buffer")

    async def _consume(self) -> None:
        assert self._stream is not None
        try:
            async for event in self._stream:
                self.latest_frame = event.frame
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("video frame buffer stream ended unexpectedly")

    def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
