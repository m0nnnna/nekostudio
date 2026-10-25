"""Single-GPU job queue: one worker thread runs jobs strictly one at a time."""
from __future__ import annotations

import logging
import queue
import threading
import time
import traceback
import uuid
from typing import Callable

log = logging.getLogger("nekostudio.jobs")


class Cancelled(Exception):
    """Raised inside a job (usually from a diffusers callback) to abort it."""


class Job:
    def __init__(self, manager: "JobManager", kind: str, fn: Callable[["Job"], None], lane: str = "gpu"):
        self.lane = lane
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.fn = fn
        self.state = "queued"
        self.progress = 0.0
        self.step = 0
        self.total = 0
        self.message = ""
        self.results: list[dict] = []
        self.info: dict = {}  # extra fields for the UI (e.g. which LoRA a training job makes)
        self.error: str | None = None
        self.cancel_event = threading.Event()
        self.proc = None  # subprocess.Popen for training, killed on cancel
        self._manager = manager

    def to_dict(self) -> dict:
        d = {"id": self.id, "kind": self.kind, "state": self.state, "progress": round(self.progress, 4),
             "step": self.step, "total": self.total, "message": self.message, "results": list(self.results)}
        if self.error:
            d["error"] = self.error
        if self.info:
            d["info"] = self.info
        return d

    def update(self, progress=None, step=None, total=None, message=None):
        if progress is not None:
            self.progress = max(0.0, min(1.0, float(progress)))
        if step is not None:
            self.step = step
        if total is not None:
            self.total = total
        if message is not None:
            self.message = message
        self._manager.notify(self)

    def add_result(self, url: str, thumb: str = "", meta: dict | None = None):
        self.results.append({"url": url, "thumb": thumb or url, "meta": meta or {}})
        self._manager.notify(self)

    def check(self):
        if self.cancel_event.is_set():
            raise Cancelled()

    def cancel(self):
        self.cancel_event.set()
        if self.proc is not None:
            try:
                self.proc.terminate()
            except OSError:
                pass
        if self.state == "queued":
            self.state = "cancelled"
            self._manager.notify(self)


class JobManager:
    def __init__(self):
        self._qs: dict[str, queue.Queue[Job]] = {}
        self._jobs: dict[str, Job] = {}
        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}
        self.current: Job | None = None  # running job of the "gpu" lane

    def start(self, lane: str = "gpu"):
        """Each lane has its own queue and worker thread: downloads never wait for (or block) GPU jobs."""
        with self._lock:
            if lane not in self._threads:
                self._qs[lane] = queue.Queue()
                t = threading.Thread(target=self._worker, args=(lane,), name=f"{lane}-worker", daemon=True)
                self._threads[lane] = t
                t.start()

    def submit(self, kind: str, fn: Callable[[Job], None], lane: str = "gpu") -> Job:
        self.start(lane)
        job = Job(self, kind, fn, lane)
        with self._lock:
            self._jobs[job.id] = job
            if len(self._jobs) > 300:  # forget the oldest finished jobs
                for jid in [j.id for j in self._jobs.values() if j.state in ("done", "error", "cancelled")][:100]:
                    self._jobs.pop(jid, None)
        self._qs[lane].put(job)
        self.notify(job)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def active(self) -> list[Job]:
        return [j for j in list(self._jobs.values()) if j.state in ("queued", "running")]

    @property
    def busy(self) -> bool:
        return self.current is not None

    @property
    def pending(self) -> int:
        return sum(1 for j in list(self._jobs.values()) if j.state == "queued" and j.lane == "gpu")

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=500)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue):
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def notify(self, job: Job):
        d = job.to_dict()
        for q in list(self._subs):
            try:
                q.put_nowait(d)
            except queue.Full:
                pass  # a stuck client must not block the GPU worker

    def _worker(self, lane: str):
        q = self._qs[lane]
        while True:
            job = q.get()
            if job.state == "cancelled":
                continue
            if lane == "gpu":
                self.current = job
            job.state = "running"
            self.notify(job)
            try:
                job.fn(job)
                job.state = "cancelled" if job.cancel_event.is_set() else "done"
                if job.state == "done":
                    job.progress = 1.0
            except Cancelled:
                job.state = "cancelled"
            except Exception as e:  # noqa: BLE001 - surfaced to the UI
                log.error("job %s failed\n%s", job.id, traceback.format_exc())
                job.state, job.error = "error", f"{type(e).__name__}: {e}"
            finally:
                job.proc = None
                if lane == "gpu":
                    self.current = None
                self.notify(job)
                time.sleep(0)


jobs = JobManager()
