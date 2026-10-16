"""Run one transactional scheduler step off the UI/reporting thread.

The simulation clock deliberately does not advance during wall-clock inference.
Only a fully completed step is published; the caller never reads worker state.
"""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from copy import deepcopy
from queue import Empty, Queue
import time

from app.llm.role_call import progress_listener


class BackgroundStepper:
    def __init__(self, scheduler, heartbeat_seconds=1.0):
        if heartbeat_seconds <= 0:
            raise ValueError("heartbeat_seconds must be positive")
        self.scheduler = scheduler
        self.interval = heartbeat_seconds
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hospital-step")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        # Running inference is bounded by the configured client timeout.
        self.pool.shutdown(wait=True, cancel_futures=True)

    def step(self, state, on_wait):
        working = deepcopy(state)
        updates = Queue()
        def execute():
            token = progress_listener.set(updates.put)
            try:
                self.scheduler.step(working)
                return working
            except Exception as exc:
                exc.failed_state = working
                raise
            finally:
                progress_listener.reset(token)
        future = self.pool.submit(execute)
        started = time.monotonic()
        progress = {}
        while True:
            try:
                return future.result(timeout=self.interval)
            except FutureTimeout:
                # A worker can itself raise TimeoutError; propagate it once done.
                if future.done():
                    return future.result()
                while True:
                    try:
                        progress = updates.get_nowait()
                    except Empty:
                        break
                on_wait({**progress, "wall_wait_seconds": round(time.monotonic() - started, 2)})
