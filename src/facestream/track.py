import asyncio
import logging
import time
from typing import Awaitable, Callable

from aiortc import MediaStreamTrack
from av.video.frame import VideoFrame

from facestream import config

logger = logging.getLogger(__name__)


class ProcessFrameTrack(MediaStreamTrack):
    """
    A MediaStreamTrack that processes frames while trying to maintain low latency
    (by dropping frames if necessary).
    """

    kind = "video"

    def __init__(
        self,
        track: MediaStreamTrack,
        process_frame: Callable[[VideoFrame], Awaitable[VideoFrame]],
    ):
        super().__init__()
        self.track = track
        self.input_queue = asyncio.Queue(maxsize=max(config.INPUT_QUEUE_SIZE, 1))
        self.output_queue = asyncio.Queue(maxsize=1)
        self.processing_task = asyncio.create_task(self._processor())
        self.last_frame = None
        self.frame_counter = 0
        self.process_frame = process_frame

        self._processed_count = 0
        self._dropped_count = 0
        self._repeated_count = 0
        self._process_time_total = 0.0
        self._stats_started = time.perf_counter()

    async def recv(self):
        # Get original frame and feed to processor
        original_frame = await self.track.recv()
        self.frame_counter += 1

        try:
            self.input_queue.put_nowait((self.frame_counter, original_frame))
        except asyncio.QueueFull:
            # Drop oldest frame if queue full
            _ = await self.input_queue.get()
            self._dropped_count += 1
            self.input_queue.put_nowait((self.frame_counter, original_frame))

        try:
            _, processed_frame = self.output_queue.get_nowait()
            self.last_frame = processed_frame
            return processed_frame
        except asyncio.QueueEmpty:
            if self.last_frame is None:
                return original_frame
            # Re-send the previous output, but stamped as the frame it stands in
            # for. Handing the encoder a timestamp it has already seen makes the
            # receiver's jitter buffer treat the packets as a duplicate of the
            # earlier frame.
            self._repeated_count += 1
            self.last_frame.pts = original_frame.pts
            self.last_frame.time_base = original_frame.time_base
            return self.last_frame

    def _record_stats(self, elapsed: float):
        self._processed_count += 1
        self._process_time_total += elapsed

        if not config.STATS_INTERVAL:
            return
        if self._processed_count % config.STATS_INTERVAL:
            return

        window = time.perf_counter() - self._stats_started
        logger.info(
            "swap stats: %.1f fps over %d frames, %.1f ms/frame, %d repeated, %d dropped",
            self._processed_count / window if window else 0.0,
            self._processed_count,
            1000 * self._process_time_total / self._processed_count,
            self._repeated_count,
            self._dropped_count,
        )
        self._processed_count = 0
        self._repeated_count = 0
        self._dropped_count = 0
        self._process_time_total = 0.0
        self._stats_started = time.perf_counter()

    async def _processor(self):
        while True:
            try:
                frame_num, frame = await asyncio.wait_for(
                    self.input_queue.get(), timeout=0.1
                )

                started = time.perf_counter()
                processed = await self.process_frame(frame)
                self._record_stats(time.perf_counter() - started)

                if not self.output_queue.empty():
                    _ = self.output_queue.get_nowait()
                self.output_queue.put_nowait((frame_num, processed))

            except (asyncio.QueueEmpty, asyncio.TimeoutError):
                continue
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error processing frame")

    def stop(self):
        self.processing_task.cancel()
        # Clear queues
        super().stop()
