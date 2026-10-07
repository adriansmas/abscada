"""Single SQLite writer and alarm/historian service, independent of PLC workers and Qt."""
from concurrent.futures import Future
from queue import Queue, Empty, Full
from threading import Event, Thread
import time
from .alarms import AlarmEngine
from . import recording
from .storage import Repository, RuntimeLease, database_path
from .i18n import tr


class Operations:
    def __init__(self, project):
        self.project = project
        self.path = database_path(project)
        self.queue = Queue(maxsize=20000)
        self.thread = None
        self.ready, self.stopping = Event(), Event()
        self.error = ""
        self.revision = 0
        self.last_commit = None
        self.alarm_summary = dict(active=0, unacknowledged=0)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stopping.clear(); self.ready.clear(); self.error = ""
        self.thread = Thread(target=self._run, name="abscada-archive", daemon=True)
        self.thread.start()
        if not self.ready.wait(5) or self.error:
            raise RuntimeError(self.error or tr("El archivo no responde"))

    def submit(self, tag, sample):
        if self.error or self.stopping.is_set() or not self.thread or not self.thread.is_alive():
            return
        try:
            self.queue.put_nowait(("sample", tag, sample))
        except Full:
            self.error = tr("Cola de archivo llena: hay pérdida de registros; revisar carga y disco")

    def command(self, action, *args):
        if self.error or self.stopping.is_set() or not self.thread or not self.thread.is_alive():
            raise RuntimeError(self.error or tr("El archivo está detenido"))
        future = Future()
        self.queue.put_nowait((action, args, future))
        try:
            return future.result(timeout=3)
        except TimeoutError:
            future.cancel()
            raise

    def acknowledge(self, instances, actor, comment=""):
        return self.command("ack", list(instances), actor, comment)

    def audit(self, action, target, actor="", detail=""):
        if self.thread and self.thread.is_alive() and not self.error:
            try:
                self.queue.put_nowait(("audit", action, target, actor, detail))
            except Full:
                self.error = tr("Cola de auditoría llena")

    def stop(self, timeout=5):
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout)
            if self.thread.is_alive():
                raise TimeoutError(tr("El archivo sigue cerrando"))

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
            repository.audit(time.time(), "runtime_start", self.project.manifest["name"])
            self.ready.set()
            while not self.stopping.is_set() or not self.queue.empty():
                wall, mono = time.time(), time.monotonic()
                for _ in range(2000):
                    try:
                        item = self.queue.get_nowait()
                    except Empty:
                        break
                    action = item[0]
                    if action == "sample":
                        _, tag, sample = item
                        samples[tag] = sample
                        engine.observe(tag, sample, mono, wall)
                        if tag in logs and not logs[tag]["file_id"] and (tag not in previous or previous[tag].quality != sample.quality):
                            repository.sample(tag, sample, wall)
                            previous[tag] = sample
                            due[tag] = mono + logs[tag].get("interval_ms", 1000)/1000
                    elif action == "audit":
                        _, action, target, actor, detail = item
                        repository.audit(wall, action, target, actor, detail)
                    else:
                        _, args, future = item
                        if not future.set_running_or_notify_cancel():
                            continue
                        try:
                            if action == "ack":
                                result = repository.acknowledge(args[0], wall, args[1], args[2])
                            else:
                                raise ValueError(tr("Orden de archivo desconocida"))
                            repository.connection.commit()
                            self.revision += 1
                            future.set_result(result)
                        except Exception as exc:
                            future.set_exception(exc)
                            raise
                engine.tick(mono, wall)
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
                    row = repository.connection.execute("SELECT sum(returned_at IS NULL),sum(ack_required=1 AND ack_at IS NULL) FROM alarm_instances WHERE returned_at IS NULL OR (ack_required=1 AND ack_at IS NULL)").fetchone()
                    self.alarm_summary = dict(active=row[0] or 0, unacknowledged=row[1] or 0)
                    self.revision += 1
                    next_commit = mono+0.2
                self.stopping.wait(0.02)
            repository.audit(time.time(), "runtime_stop", self.project.manifest["name"])
            repository.connection.commit()
            self.revision += 1
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
