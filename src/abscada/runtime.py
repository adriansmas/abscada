"""Headless acquisition, typed tag store and explicit write queue."""
from __future__ import annotations
from dataclasses import dataclass
from queue import Queue, Empty
from threading import Event, Lock, Thread
from concurrent.futures import Future
import time
from .project import coerce
from .connectors import REGISTRY


@dataclass(frozen=True)
class Sample:
    value: object
    quality: str
    timestamp: float
    error: str = ""


class Runtime:
    def __init__(self, project):
        project.validate()
        self.project = project
        self.tags = project.tags()
        self._samples = {name: Sample(t["initial"], "uncertain" if t.get("binding") else "good", time.time())
                         for name, t in self.tags.items()}
        self._lock = Lock()
        self._stop = Event()
        self._writes = {c["id"]: Queue(maxsize=1000) for c in project.connections}
        self._workers = []
        self._thread = None
        self._started = False
        from .storage import RuntimeLease, database_path
        self._lease = RuntimeLease(project.root / "runtime" / "runtime.lock")
        self._status = {}
        self._results = []
        from .scripting import ScriptService
        self.scripts = ScriptService(self)
        from .operations import Operations
        self.operations = Operations(project) if project.alarms["items"] or project.historian.get("tags") or any(f["variables"] for f in project.historian.get("files", [])) or database_path(project).exists() else None

    def snapshot(self):
        with self._lock:
            return dict(self._samples)

    def status(self):
        with self._lock:
            return dict(self._status)

    def write_results(self):
        with self._lock:
            results, self._results = self._results, []
            return results

    def write(self, name, value):
        tag = self.tags[name]
        if not tag.get("writable", False):
            raise ValueError(f"Variable de solo lectura: {name}")
        value = coerce(value, tag["type"])
        completion=Future()
        if tag.get("binding"):
            if self._stop.is_set() or not self._thread or not self._thread.is_alive():
                raise ValueError("El runtime está detenido")
            self._writes[tag["binding"]["connection"]].put_nowait((name, value,completion))
        else:
            self._set(name, value, "good")
            completion.set_result(True)
        if self.operations:
            self.operations.audit("write_requested", name, detail=str(value))
        return completion

    def _set(self, name, value, quality, error=""):
        with self._lock:
            self._samples[name] = Sample(value, quality, time.time(), error)
            sample = self._samples[name]
        if self.operations:
            self.operations.submit(name, sample)

    def start(self):
        if self._started:
            return
        if any(thread and thread.is_alive() for thread in
               (self._thread, self.scripts.thread, self.operations.thread if self.operations else None)):
            raise RuntimeError("El runtime anterior sigue terminando")
        self._lease.acquire()
        self._stop.clear()
        with self._lock:
            self._status.clear()
            for name, tag in self.tags.items():
                if tag.get('binding'):
                    self._samples[name] = Sample(self._samples[name].value, 'uncertain', time.time())
        try:
            if self.operations:
                self.operations.start()
                for name, sample in self.snapshot().items():
                    self.operations.submit(name, sample)
            self._thread = Thread(target=self._run, name="abscada-acquisition", daemon=True)
            self._thread.start()
            self.scripts.start()
            self._started = True
        except Exception:
            self.stop()
            raise

    def stop(self, timeout=5):
        self._started = False
        self._stop.set()
        errors = []
        try:
            self.scripts.stop(timeout)
        except Exception as exc:
            errors.append(exc)
        if self._thread and self._thread.ident is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                errors.append(TimeoutError("La comunicación sigue terminando; no iniciar otro runtime"))
        if not self._thread or not self._thread.is_alive():
            for name, tag in self.tags.items():
                if tag.get('binding'):
                    self._set(name, self.snapshot()[name].value, 'uncertain', 'Runtime detenido')
            with self._lock:
                self._status = {c['id']: 'Detenido' for c in self.project.connections}
        if self.operations:
            try:
                self.operations.stop(timeout)
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise TimeoutError('; '.join(str(exc) for exc in errors))
        self._lease.close()

    def _run(self):
        self._workers = [Thread(target=self._run_connection, args=(config,),
                                name="abscada-" + config["id"], daemon=True)
                         for config in self.project.connections]
        for worker in self._workers:
            worker.start()
        for worker in self._workers:
            worker.join()

    def _run_connection(self, connection):
        """One client, one queue, one independent schedule. No concurrent client access."""
        cid = connection["id"]
        tags = {name: tag for name, tag in self.tags.items()
                if tag.get("binding", {}).get("connection") == cid}
        queue = self._writes[cid]
        adapter, due = None, 0
        try:
            while not self._stop.is_set():
                now = time.monotonic()
                if now >= due:
                    due = now + connection.get("poll_ms", 250) / 1000
                    try:
                        if adapter is None:
                            adapter = REGISTRY[connection["protocol"]](connection)
                            adapter.connect()
                        for name, tag in tags.items():
                            if self._stop.is_set():
                                break
                            value = adapter.read(tag["binding"]["address"], tag["type"])
                            self._set(name, coerce(value, tag["type"]), "good")
                        with self._lock:
                            self._status[cid] = "Conectado"
                    except Exception as exc:
                        for name in tags:
                            self._set(name, self.snapshot()[name].value, "bad", str(exc))
                        with self._lock:
                            self._status[cid] = str(exc)
                        if adapter:
                            try:
                                adapter.close()
                            except Exception:
                                pass
                        adapter = None
                        due = time.monotonic() + 2
                for _ in range(100):
                    if self._stop.is_set():
                        break
                    try:
                        name, value, completion = queue.get_nowait()
                    except Empty:
                        break
                    if not completion.set_running_or_notify_cancel():
                        continue
                    tag = tags[name]
                    try:
                        if adapter is None or self.snapshot()[name].quality != "good":
                            raise ConnectionError("Conexión no disponible; escritura descartada")
                        adapter.write(tag["binding"]["address"], tag["type"], value)
                        completion.set_result(True)
                        due = 0
                        result = (name, True, "Escritura enviada; pendiente de lectura")
                    except Exception as exc:
                        completion.set_exception(exc)
                        result = (name, False, str(exc))
                    with self._lock:
                        self._results.append(result)
                        self._results = self._results[-1000:]
                    if self.operations:
                        self.operations.audit("write_sent" if result[1] else "write_failed", name, detail=result[2])
                self._stop.wait(0.01)
        finally:
            if adapter:
                try:
                    adapter.close()
                except Exception:
                    pass
            while True:
                try:
                    _,_,completion=queue.get_nowait()
                    if not completion.done():completion.set_exception(RuntimeError('Runtime detenido antes de enviar la escritura'))
                except Empty:
                    break
