"""Headless acquisition, typed tag store and explicit write queue."""
from __future__ import annotations
from dataclasses import dataclass
import logging
from queue import Queue, Empty, Full
from threading import Event, Lock, Thread
from concurrent.futures import Future
import time
from .project import coerce
from .connectors import create, read_groups
from .protocol_definition import AddressError, GroupError, Uncertain
from .security import SecurityService
from .i18n import tr

log = logging.getLogger("abscada.runtime")

# Reconnection waits 2, 4, 8, 16 and then 30 s between attempts.
RECONNECT_FIRST, RECONNECT_MAX = 2, 30
# Changes kept for ``changes(since)``; a consumer further behind refreshes everything.
CHANGE_LOG = 100_000
# Seconds between performance lines in the log, per connection.
TELEMETRY_SECONDS = 300
_KEEP = object()   # keep the current value, change only quality and error


@dataclass(frozen=True)
class Sample:
    value: object
    quality: str
    timestamp: float
    error: str = ""


def same_value(a, b):
    """Equal and of the same type: 1, 1.0 and True are different readings."""
    return type(a) is type(b) and a == b


class Runtime:
    def __init__(self, project):
        project.validate()
        self.project = project
        from .project_languages import default_language, languages
        from .i18n import _read_settings
        self.language = default_language(project)
        if project.manifest.get('initial_language', 'project') in {'station', 'user'}:
            station = _read_settings().get('project_station_languages', {}).get(str(project.root.resolve()), default_language(project))
            if station in languages(project):
                self.language = station
        self.tags = project.tags()
        self._samples = {name: Sample(t["initial"], "uncertain" if t.get("binding") else "good", time.time())
                         for name, t in self.tags.items()}
        self._lock = Lock()
        self._stop = Event()
        self._writes = {c["id"]: Queue(maxsize=1000) for c in project.connections}
        # Connections whose worker no longer takes orders (stopping or stopped).
        self._closed = set()
        # Names changed since revision ``_log_base`` (see ``changes``).
        self._log, self._log_base = [], 0
        self._workers = []
        self._thread = None
        self._started = False
        from .storage import RuntimeLease, database_path
        self._lease = RuntimeLease(project.root / "runtime" / "runtime.lock")
        self._status = {}
        self._diagnostics = {}
        self._results = []
        from .scripting import ScriptService
        self.scripts = ScriptService(self)
        self.security = SecurityService(project)
        # Operator session of this station (HMI windows). OPC UA clients get their own.
        self.session = None
        from .operations import Operations
        # With security or the OPC UA server on, the audit trail is required even without alarms.
        audited = self.security.enabled or project.opcua_server.get("enabled", False)
        self.operations = Operations(project) if audited or project.alarms["items"] or project.historian.get("tags") or any(f["variables"] for f in project.historian.get("files", [])) or database_path(project).exists() else None
        self.opcua = None

    def set_language(self, code, *, persist=True):
        from .project_languages import languages
        if code not in languages(self.project):
            raise ValueError(f'Idioma de proyecto desconocido: {code}')
        self.language = code
        if persist and self.project.manifest.get('initial_language') in {'station', 'user'}:
            from .i18n import _read_settings, settings_path
            import json
            settings = _read_settings()
            settings.setdefault('project_station_languages', {})[str(self.project.root.resolve())] = code
            path = settings_path(); path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')

    def snapshot(self):
        with self._lock:
            return dict(self._samples)

    def sample(self, name):
        """The current sample of one variable, without copying the whole store."""
        with self._lock:
            return self._samples[name]

    @property
    def revision(self):
        with self._lock:
            return self._log_base + len(self._log)

    def changes(self, since):
        """``(revision, names)``: the variables whose value, quality or error changed after
        revision ``since``. ``names`` is None when ``since`` is None or too old to know:
        the caller then refreshes everything."""
        with self._lock:
            revision = self._log_base + len(self._log)
            if since is None or since < self._log_base:
                return revision, None
            return revision, set(self._log[since - self._log_base:])

    def status(self):
        with self._lock:
            return dict(self._status)

    def diagnostics(self):
        """Per connection: real cycle against ``poll_ms``, requests per cycle, errors and reconnections."""
        with self._lock:
            return {cid: dict(values) for cid, values in self._diagnostics.items()}

    def write_results(self):
        with self._lock:
            results, self._results = self._results, []
            return results

    def command(self, name, value, session, permission="operate", origin="hmi"):
        """Write requested by a person (HMI or OPC UA client): checks the permission of
        their session and records who asked for it. Scripts call ``write`` directly."""
        if not self.security.permits(session, permission):
            self.audit("write_denied", name, session, f"{origin}: {value}")
            raise PermissionError(tr("Sin permiso para esta orden: inicia sesión con un usuario autorizado"))
        self.security.touch(session)
        return self.write(name, value, actor=self.security.actor(session), origin=origin)

    def audit(self, action, target, session=None, detail=""):
        if self.operations:
            self.operations.audit(action, target, actor=self.security.actor(session), detail=detail)

    def login(self, name, password):
        try:
            session = self.security.login(name, password)
        except PermissionError as exc:
            if self.operations:
                self.operations.audit("login_failed", name or "", actor=name or "", detail=str(exc))
            raise
        self.session = session
        if self.project.manifest.get('initial_language') == 'user':
            account = self.security.store.find(session.user)
            preferred = (account or {}).get('language')
            if preferred in self.project.manifest.get('languages', ['es']):
                self.set_language(preferred, persist=False)
        self.audit("login", session.user, session)
        return session

    def logout(self, reason="logout"):
        session, self.session = self.session, None
        if session is not None:
            self.audit(reason, session.user, session)

    def accepts_writes(self, name):
        """The connection of ``name`` takes orders now (always true for internal variables)."""
        binding = self.tags[name].get("binding")
        if not binding:
            return True
        with self._lock:
            return (binding["connection"] not in self._closed and not self._stop.is_set()
                    and self._thread is not None and self._thread.is_alive()
                    and not self._writes[binding["connection"]].full())

    def write(self, name, value, actor="", origin="script"):
        tag = self.tags[name]
        if not tag.get("writable", False):
            raise ValueError(tr("Variable de solo lectura: {name}", name=name))
        value = coerce(value, tag["type"])
        completion=Future()
        if tag.get("binding"):
            connection = tag["binding"]["connection"]
            # Under the lock the worker cannot close its queue between the check and the put.
            with self._lock:
                if connection in self._closed or self._stop.is_set() or not self._thread or not self._thread.is_alive():
                    raise ValueError(tr("El runtime está detenido"))
                try:
                    self._writes[connection].put_nowait((name, value, completion))
                except Full:
                    raise ValueError(tr("Cola de órdenes llena: la conexión {connection} no da abasto; inténtalo de nuevo", connection=connection)) from None
        else:
            self._set(name, value, "good")
            completion.set_result(True)
        if self.operations:
            self.operations.audit("write_requested", name, actor=actor, detail=f"{origin}: {value}")
        return completion

    def set_quality(self, name, quality, reason=""):
        """Quality of an internal variable, keeping its value, until the next write (which is good).
        Bound variables get their quality from their connection."""
        if self.tags[name].get("binding"):
            raise ValueError(tr("{name}: solo se puede cambiar la calidad de variables internas", name=name))
        if quality not in ("good", "uncertain", "bad"):
            raise ValueError(tr("Calidad desconocida: {quality}", quality=quality))
        self._set(name, _KEEP, quality, reason)

    def _set(self, name, value, quality, error=""):
        return self._set_many([(name, value, quality, error)])

    def _set_many(self, updates):
        """Store several readings under one lock. A reading equal to the current one (value,
        quality and error) keeps the current sample: nothing changed, nobody is told."""
        changed = []
        now = time.time()
        with self._lock:
            for name, value, quality, error in updates:
                current = self._samples[name]
                if value is _KEEP:
                    value = current.value
                if current.quality == quality and current.error == error and same_value(current.value, value):
                    continue
                sample = Sample(value, quality, now, error)
                self._samples[name] = sample
                self._log.append(name)
                changed.append((name, sample))
            if len(self._log) > CHANGE_LOG:
                self._log_base += len(self._log)
                self._log = []
        if self.operations:
            for name, sample in changed:
                self.operations.submit(name, sample)
        return bool(changed)

    def start(self):
        if self._started:
            return
        if any(thread and thread.is_alive() for thread in
               (self._thread, self.scripts.thread, self.operations.thread if self.operations else None)):
            raise RuntimeError(tr("El runtime anterior sigue terminando"))
        self._lease.acquire()
        self._stop.clear()
        with self._lock:
            self._status.clear()
            self._diagnostics.clear()
            self._closed.clear()
        self._set_many([(name, _KEEP, 'uncertain', '') for name, tag in self.tags.items() if tag.get('binding')])
        try:
            if self.operations:
                self.operations.start()
                for name, sample in self.snapshot().items():
                    self.operations.submit(name, sample)
            self._thread = Thread(target=self._run, name="abscada-acquisition", daemon=True)
            self._thread.start()
            self.scripts.start()
            if self.project.opcua_server.get("enabled"):
                from .opcua_server import OpcUaServer
                self.opcua = OpcUaServer(self)
                self.opcua.start()
            self._started = True
        except Exception:
            self.stop()
            raise

    def stop(self, timeout=5):
        self._started = False
        self._stop.set()
        for queue in self._writes.values():
            try:
                queue.put_nowait(None)  # wake the worker waiting for orders
            except Full:
                pass
        errors = []
        try:
            if self.opcua:
                try:
                    self.opcua.stop(timeout)
                except Exception as exc:
                    errors.append(exc)
                self.opcua = None
            self.logout("runtime_stop_logout")
            try:
                self.scripts.stop(timeout)
            except Exception as exc:
                errors.append(exc)
            if self._thread and self._thread.ident is not None:
                self._thread.join(timeout)
                if self._thread.is_alive():
                    errors.append(TimeoutError(tr("La comunicación sigue terminando; no iniciar otro runtime")))
            if not self._thread or not self._thread.is_alive():
                self._set_many([(name, _KEEP, 'uncertain', tr('Runtime detenido'))
                                for name, tag in self.tags.items() if tag.get('binding')])
                with self._lock:
                    self._status = {c['id']: tr('Detenido') for c in self.project.connections}
            if self.operations:
                try:
                    self.operations.stop(timeout)
                except Exception as exc:
                    errors.append(exc)
            if errors:
                raise TimeoutError('; '.join(str(exc) for exc in errors))
        finally:
            # Always give the project back: a worker that takes long to finish must not keep
            # the next start out until the application restarts. A new start still waits
            # for the old threads (see ``start``).
            self._lease.close()

    def _run(self):
        self._workers = [Thread(target=self._run_connection, args=(config,),
                                name="abscada-" + config["id"], daemon=True)
                         for config in self.project.connections]
        for worker in self._workers:
            worker.start()
        for worker in self._workers:
            worker.join()

    def _diagnose(self, cid, **values):
        with self._lock:
            self._diagnostics.setdefault(cid, {}).update(values)

    def _run_connection(self, connection):
        """One client, one queue, one independent schedule. No concurrent client access.

        Orders are served between read groups, and only the groups holding a written
        variable are read again right after it; the full cycle keeps its own schedule."""
        cid = connection["id"]
        tags = {name: tag for name, tag in self.tags.items()
                if tag.get("binding", {}).get("connection") == cid}
        names = list(tags)
        position = {name: index for index, name in enumerate(names)}
        queue = self._writes[cid]
        poll = connection.get("poll_ms", 250) / 1000
        state = dict(adapter=None, groups=[], failures=0)
        group_of = {}         # request index -> group number, learnt from the answers
        urgent = set()        # groups to read again because a variable in them was written
        address_errors = {}   # variables whose own address fails: name -> error
        due = 0
        stats = dict(cycles=0, busy=0.0, worst=0.0, requests=0, errors=0, reconnects=0, since=time.monotonic())
        self._diagnose(cid, poll_ms=round(poll * 1000), cycle_ms=None, requests=0, errors=0, reconnects=0,
                       last_read=None, connected=False)

        def read_group(number):
            read = state["groups"][number]
            try:
                values = read()
            except GroupError as exc:
                for index in exc.indices:
                    group_of[index] = number
                    address_errors[names[index]] = str(exc)
                self._set_many([(names[index], _KEEP, "bad", str(exc)) for index in exc.indices])
                return len(exc.indices)
            updates, errors = [], 0
            for index, value in values.items():
                group_of[index] = number
                name = names[index]
                if isinstance(value, Exception):
                    address_errors[name] = str(value)
                    updates.append((name, _KEEP, "bad", str(value))); errors += 1
                    continue
                address_errors.pop(name, None)
                quality, error = "good", ""
                if isinstance(value, Uncertain):
                    quality, error, value = "uncertain", value.reason, value.value
                try:
                    value = coerce(value, tags[name]["type"])
                except (ValueError, TypeError) as exc:
                    # NaN, an uninitialised REAL, a BOOL read as 2...: this variable only.
                    updates.append((name, _KEEP, "bad", str(exc))); errors += 1
                    continue
                updates.append((name, value, quality, error))
            self._set_many(updates)
            return errors

        def serve(first=None, limit=100):
            nonlocal due
            for count in range(limit):
                if count == 0 and first is not None:
                    item = first
                else:
                    try:
                        item = queue.get_nowait()
                    except Empty:
                        return
                if item is None or self._stop.is_set():
                    if item is not None:
                        try:
                            queue.put_nowait(item)  # answered by the shutdown below
                        except Full:
                            item[2].set_exception(RuntimeError(tr('Runtime detenido antes de enviar la escritura')))
                    return
                name, value, completion = item
                if not completion.set_running_or_notify_cancel():
                    continue
                tag = tags[name]
                try:
                    adapter = state["adapter"]
                    if adapter is None:
                        raise ConnectionError(tr("Conexión no disponible; escritura descartada"))
                    if name in address_errors:
                        raise ValueError(tr("Dirección con error; escritura descartada: {error}", error=address_errors[name]))
                    adapter.write(tag["binding"]["address"], tag["type"], value)
                    completion.set_result(True)
                    group = group_of.get(position[name])
                    if group is None:
                        due = 0          # its group is not known yet: read everything
                    else:
                        urgent.add(group)
                    result = (name, True, tr("Escritura enviada; pendiente de lectura"))
                except Exception as exc:
                    completion.set_exception(exc)
                    result = (name, False, str(exc))
                with self._lock:
                    self._results.append(result)
                    self._results = self._results[-1000:]
                if self.operations:
                    self.operations.audit("write_sent" if result[1] else "write_failed", name, detail=result[2])

        try:
            while not self._stop.is_set():
                now = time.monotonic()
                full = now >= due
                if full or (urgent and state["adapter"] is not None):
                    if full:
                        due = now + poll
                    try:
                        if state["adapter"] is None:
                            adapter = create(connection, self.project.root)
                            try:
                                adapter.connect()
                                groups = read_groups(adapter, [(tags[n]["binding"]["address"], tags[n]["type"]) for n in names])
                            except BaseException:
                                try:
                                    adapter.close()
                                except Exception:
                                    pass
                                raise
                            state.update(adapter=adapter, groups=groups)
                            group_of.clear(); urgent.clear()
                            if state["failures"]:
                                stats["reconnects"] += 1
                            self._diagnose(cid, connected=True)
                        selected = range(len(state["groups"])) if full else sorted(urgent)
                        urgent.clear()
                        started, errors = time.monotonic(), 0
                        for number in selected:
                            if self._stop.is_set():
                                break
                            errors += read_group(number)
                            serve()
                        state["failures"] = 0
                        with self._lock:
                            self._status[cid] = tr("Conectado")
                        if full:
                            elapsed = time.monotonic() - started
                            stats.update(cycles=stats["cycles"] + 1, busy=stats["busy"] + elapsed,
                                         worst=max(stats["worst"], elapsed), requests=stats["requests"] + len(selected),
                                         errors=stats["errors"] + errors)
                            self._diagnose(cid, cycle_ms=round(elapsed * 1000, 1), requests=len(selected), errors=errors,
                                           reconnects=stats["reconnects"], last_read=time.time())
                    except Exception as exc:
                        self._set_many([(name, _KEEP, "bad", str(exc)) for name in tags])
                        with self._lock:
                            self._status[cid] = str(exc)
                        if state["adapter"] is not None:
                            try:
                                state["adapter"].close()
                            except Exception:
                                pass
                        state.update(adapter=None, groups=[])
                        state["failures"] += 1
                        due = time.monotonic() + min(RECONNECT_MAX, RECONNECT_FIRST * 2 ** (state["failures"] - 1))
                        self._diagnose(cid, connected=False, reconnects=stats["reconnects"])
                serve()
                now = time.monotonic()
                if now - stats["since"] >= TELEMETRY_SECONDS and stats["cycles"]:
                    log.info("Conexión %s: %d ciclos, medio %.0f ms, peor %.0f ms (poll %d ms), %.1f peticiones/ciclo, %d errores, %d reconexiones",
                             cid, stats["cycles"], stats["busy"] / stats["cycles"] * 1000, stats["worst"] * 1000, poll * 1000,
                             stats["requests"] / stats["cycles"], stats["errors"], stats["reconnects"])
                    stats.update(cycles=0, busy=0.0, worst=0.0, requests=0, errors=0, since=now)
                if urgent and state["adapter"] is not None:
                    continue
                # Sleep until the next cycle or the next order, whichever comes first.
                try:
                    item = queue.get(timeout=max(0.0, min(due - time.monotonic(), 0.5)))
                except Empty:
                    continue
                serve(item)
        finally:
            if state["adapter"] is not None:
                try:
                    state["adapter"].close()
                except Exception:
                    pass
            with self._lock:
                self._closed.add(cid)
            while True:
                try:
                    item = queue.get_nowait()
                except Empty:
                    break
                if item is not None and not item[2].done():
                    item[2].set_exception(RuntimeError(tr('Runtime detenido antes de enviar la escritura')))
