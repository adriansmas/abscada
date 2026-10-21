"""Single SQLite writer and alarm/historian service, independent of PLC workers and Qt."""
from concurrent.futures import Future
from queue import Queue, Empty, Full
from threading import Event, Lock, Thread
import time
from .alarms import AlarmEngine
from . import recording
from .storage import Repository, RuntimeLease, database_path
from .i18n import tr


# Opening the archive syncs SQLite to disk and recovers the alarm state; on a slow disk, or with
# an antivirus scanning new files, that can take several seconds without anything being wrong.
START_TIMEOUT = 30
COMMIT_SECONDS = 0.2
# How long the operator sees that samples were merged because the queue was full.
OVERFLOW_NOTICE_SECONDS = 30

class Operations:
    def __init__(self, project):
        self.project = project
        self.path = database_path(project)
        self.queue = Queue(maxsize=20000)
        self.thread = None
        self.ready, self.stopping = Event(), Event()
        self.error = ""
        self.revision = 0
        # Rises only when an alarm enters, returns or is acknowledged: viewers skip queries otherwise.
        self.alarm_revision = 0
        self.last_commit = None
        self.alarm_summary = dict(active=0, unacknowledged=0)
        # A full queue never stops the archive: the latest sample of each variable waits here
        # (intermediate values are lost and counted) until the writer catches up.
        self._overflow, self._overflow_lock = {}, Lock()
        self.dropped = 0
        self.dropped_audit = 0
        self._overflow_until = 0.0

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stopping.clear(); self.ready.clear(); self.error = ""
        self.thread = Thread(target=self._run, name="abscada-archive", daemon=True)
        self.thread.start()
        if not self.ready.wait(START_TIMEOUT) or self.error:
            raise RuntimeError(self.error or tr("El archivo no responde"))

    def running(self):
        return not self.error and not self.stopping.is_set() and self.thread is not None and self.thread.is_alive()

    def notice(self):
        """Text for the operator: a stopped archive, or samples merged recently because of load."""
        if self.error:
            return self.error
        if time.monotonic() < self._overflow_until:
            return tr("Archivo sobrecargado: {count} muestras intermedias no registradas; revisar carga y disco", count=self.dropped)
        return ""

    def submit(self, tag, sample):
        if not self.running():
            return
        with self._overflow_lock:
            # While older samples wait in the overflow, newer ones go there too: order is kept.
            if not self._overflow:
                try:
                    self.queue.put_nowait(("sample", tag, sample))
                    return
                except Full:
                    pass
            if tag in self._overflow:
                self.dropped += 1
            self._overflow[tag] = sample
            self._overflow_until = time.monotonic() + OVERFLOW_NOTICE_SECONDS

    def command(self, action, *args):
        if not self.running():
            raise RuntimeError(self.error or tr("El archivo está detenido"))
        future = Future()
        try:
            self.queue.put_nowait((action, args, future))
        except Full:
            raise RuntimeError(tr("El archivo está sobrecargado; inténtalo de nuevo en unos segundos")) from None
        try:
            return future.result(timeout=3)
        except TimeoutError:
            if future.cancel():
                raise TimeoutError(tr("El archivo no responde; la orden no se ha aplicado")) from None
            # Already being applied: its real outcome is what the operator must see.
            return future.result(timeout=30)

    def acknowledge(self, instances, actor, comment=""):
        return self.command("ack", list(instances), actor, comment)

    def audit(self, action, target, actor="", detail=""):
        if self.running():
            try:
                self.queue.put_nowait(("audit", action, target, actor, detail))
            except Full:
                with self._overflow_lock:
                    self.dropped_audit += 1
                    self._overflow_until = time.monotonic() + OVERFLOW_NOTICE_SECONDS

    def stop(self, timeout=5):
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout)
            if self.thread.is_alive():
                raise TimeoutError(tr("El archivo sigue cerrando"))

    def _take_overflow(self):
        with self._overflow_lock:
            overflow, self._overflow = self._overflow, {}
            return overflow

    def _run(self):
        lease = RuntimeLease(self.path.with_suffix(".lock"))
        repository = None
        archives = {}
        try:
            lease.acquire()
            repository = Repository(self.path)
            engine = AlarmEngine(self.project.alarms["items"], repository)
            logs = {item["tag"]: item for item in recording.logs(self.project)}
            repository.connection.executemany("INSERT OR IGNORE INTO recording_sources(tag,file_id) VALUES(?,?)",
                [(tag, log["file_id"]) for tag, log in logs.items() if log["file_id"]])
            repository.connection.commit()
            archives = {f["id"]: recording.DailyArchive(self.project, f["id"]) for f in recording.files(self.project)} if "files" in self.project.historian else {}
            def sample_repository(log):
                return archives.get(log["file_id"], repository)
            samples, due, previous = {}, {}, {}
            next_commit, next_prune = 0, 0
            reported_drops = reported_audit_drops = 0
            seen_alarms = engine.revision
            repository.audit(time.time(), "runtime_start", self.project.manifest["name"])
            self.alarm_summary = engine.summary()
            self.ready.set()

            def observe(tag, sample, mono):
                samples[tag] = sample
                # Alarms carry the time the value changed, not the time the archive got to it.
                engine.observe(tag, sample, mono, sample.timestamp)
                if tag in logs and not logs[tag]["file_id"] and (tag not in previous or previous[tag].quality != sample.quality):
                    repository.sample(tag, sample, time.time())
                    previous[tag] = sample
                    due[tag] = mono + logs[tag].get("interval_ms", 1000)/1000

            while not self.stopping.is_set() or not self.queue.empty() or self._overflow:
                wakeup = min([next_commit] + list(due.values()) + engine.next_deadline()) - time.monotonic()
                try:
                    first = self.queue.get(timeout=max(0.005, min(COMMIT_SECONDS, wakeup)))
                except Empty:
                    first = None
                wall, mono = time.time(), time.monotonic()
                for index in range(2000):
                    if index == 0 and first is not None:
                        item = first
                    else:
                        try:
                            item = self.queue.get_nowait()
                        except Empty:
                            break
                    action = item[0]
                    if action == "sample":
                        observe(item[1], item[2], mono)
                    elif action == "audit":
                        _, action, target, actor, detail = item
                        repository.audit(wall, action, target, actor, detail)
                    else:
                        _, args, future = item
                        if not future.set_running_or_notify_cancel():
                            continue
                        # A failed command (database locked, missing operator) affects only itself:
                        # the archive goes on recording.
                        repository.connection.execute("SAVEPOINT command")
                        try:
                            if action == "ack":
                                result = repository.acknowledge(args[0], wall, args[1], args[2])
                                engine.acknowledged(args[0])
                            else:
                                raise ValueError(tr("Orden de archivo desconocida"))
                            repository.connection.execute("RELEASE command")
                            repository.connection.commit()
                            self.revision += 1
                            future.set_result(result)
                        except Exception as exc:
                            try:
                                repository.connection.execute("ROLLBACK TO command")
                                repository.connection.execute("RELEASE command")
                            except Exception:
                                pass
                            future.set_exception(exc)
                if self.queue.empty():
                    for tag, sample in self._take_overflow().items():
                        observe(tag, sample, mono)
                engine.tick(mono, wall)
                if self.dropped != reported_drops or self.dropped_audit != reported_audit_drops:
                    repository.audit(wall, "archive_overflow", self.project.manifest["name"],
                                     detail=f"samples={self.dropped - reported_drops}; audit={self.dropped_audit - reported_audit_drops}")
                    reported_drops, reported_audit_drops = self.dropped, self.dropped_audit
                group_due = {key: mono >= value for key, value in due.items()}
                incomplete = {log["file_id"] for tag, log in logs.items() if log["file_id"] and tag not in samples}
                for tag, log in logs.items():
                    cycle_key = log["file_id"] or tag
                    sample = samples.get(tag)
                    if sample is None or cycle_key in incomplete or not group_due.get(cycle_key, True):
                        continue
                    due[cycle_key] = mono + log.get("interval_ms", 1000)/1000
                    last = previous.get(tag)
                    changed = last is None or last.quality != sample.quality
                    if last is not None and not changed:
                        if isinstance(sample.value, (int, float)) and not isinstance(sample.value, bool):
                            changed = abs(sample.value-last.value) > log.get("deadband", 0)
                        else:
                            changed = sample.value != last.value
                    if log.get("mode", "cyclic") == "cyclic" or changed:
                        sample_repository(log).sample(tag, sample, wall)
                        previous[tag] = sample
                if mono >= next_prune:
                    repository.prune(wall, self.project.historian.get("retention_days", 90), self.project.alarms.get("retention_days", 365))
                    for archive in archives.values():
                        archive.prune(wall, self.project.historian.get("retention_days", 90))
                    next_prune = mono+3600
                if mono >= next_commit:
                    repository.connection.commit()
                    for archive in archives.values():
                        archive.commit()
                    self.last_commit = wall
                    self.alarm_summary = engine.summary()
                    if engine.revision != seen_alarms:
                        seen_alarms = engine.revision
                        self.alarm_revision += 1
                    self.revision += 1
                    next_commit = mono+COMMIT_SECONDS
            repository.audit(time.time(), "runtime_stop", self.project.manifest["name"])
            repository.connection.commit()
            self.revision += 1
            self.alarm_revision += 1
        except Exception as exc:
            self.error = tr("Archivo SQLite: {exc}", exc=exc)
        finally:
            self.ready.set()
            for archive in archives.values():
                try:
                    archive.close()
                except Exception as exc:
                    self.error = tr("Archivo SQLite: {exc}", exc=exc)
            try:
                if repository:
                    repository.close()
            except Exception as exc:
                self.error = tr("Archivo SQLite: {exc}", exc=exc)
            finally:
                lease.close()
            while True:
                try:
                    item = self.queue.get_nowait()
                except Empty:
                    break
                if len(item) == 3 and isinstance(item[2], Future) and not item[2].done():
                    item[2].set_exception(RuntimeError(self.error or tr("Archivo cerrado")))
