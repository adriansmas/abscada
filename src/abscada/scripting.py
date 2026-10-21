"""Event/task scheduler with killable Python execution.

Scripts run in separate Python processes that stay open between executions (a pool); each
one is told only the samples that changed since its previous execution. A script that
exceeds its time or is cancelled has its process killed; the next execution gets a new one.

Scripts with a time limit run in a small pool of threads, one execution of each script at a
time, so a slow task does not delay the buttons; scripts without a limit run in parallel,
each in its own thread, and only one execution of each at a time.
"""
import json
import re
import subprocess
import sys
import time
from threading import Thread, Event, Lock
from queue import Queue, Empty, Full
from collections import deque
from .i18n import tr
from .button_actions import with_steps

MAX_LIMIT = 86400
# Threads for scripts with a time limit; processes kept waiting for the next execution.
SCRIPT_THREADS = 4
IDLE_RUNNERS = 4


def validate_scripts(project):
    for name, source in project.scripts.items():
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name) or not isinstance(source, str):
            raise ValueError(tr('Nombre o contenido de script inválido'))
        try:
            compile(source, f'scripts/{name}.py', 'exec')
        except SyntaxError as exc:
            raise ValueError(tr("{name}, línea {lineno}: {msg}", name=name, lineno=exc.lineno, msg=exc.msg)) from exc
    def references(items):
        if not isinstance(items, list) or any(not isinstance(n, str) or n not in project.scripts for n in items):
            raise ValueError(tr('Referencia a script inexistente'))
    from .script_tree import validate as validate_folders
    validate_folders(project)
    references(project.automation.get('startup', []))
    timeout = project.automation.get('timeout_seconds', 10)
    if type(timeout) not in (int, float) or not 0.1 <= timeout <= 300:
        raise ValueError(tr('El límite de ejecución debe estar entre 0,1 y 300 segundos'))
    limits = project.automation.get('limits', {})
    if not isinstance(limits, dict):
        raise ValueError(tr('Límites de scripts inválidos'))
    references(list(limits))
    for limit in limits.values():
        if limit is not None and (type(limit) not in (int, float) or not 0.1 <= limit <= MAX_LIMIT):
            raise ValueError(tr('El límite de un script debe estar entre 0,1 y {max} segundos, o no tener límite', max=MAX_LIMIT))
    ids = set()
    for task in project.automation.get('tasks', []):
        if not isinstance(task.get('id'), str) or not task['id'].strip() or task['id'] in ids:
            raise ValueError(tr('Nombre de tarea vacío o duplicado'))
        ids.add(task['id']); references([task.get('script')])
        if type(task.get('interval_ms')) is not int or not 100 <= task['interval_ms'] <= 86400000:
            raise ValueError(tr('El periodo de tarea debe estar entre 100 y 86400000 ms'))
        if not isinstance(task.get('enabled', True), bool):
            raise ValueError(tr('Estado de tarea inválido'))
    for document in project.screens.values():
        references(document.get('on_open', []))
    for document in list(project.screens.values()) + list(project.faceplates.values()):
        for element in document['elements']:
            for target in with_steps(element):
                if target.get('kind', 'button') == 'button' and target.get('action') == 'script':
                    references([target.get('script')])


def script_timeout(project, name):
    """Seconds allowed for one execution of ``name``, or None when it may run until it ends."""
    limits = project.automation.get('limits', {})
    return limits[name] if name in limits else project.automation.get('timeout_seconds', 10)


def _pump(stream, lines):
    for line in stream:
        lines.put(line)
    lines.put(None)


class Runner:
    """One script process in serve mode (see script_runner). It knows the samples up to
    ``revision`` of the Runtime, so the next request only carries what changed since."""
    def __init__(self, cwd):
        from .app_paths import script_runner_command
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        self.process = subprocess.Popen(script_runner_command(),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8',
            cwd=cwd, creationflags=flags)
        self.lines, self.errors = Queue(), []
        Thread(target=_pump, args=(self.process.stdout, self.lines), daemon=True).start()
        Thread(target=self._errors, daemon=True).start()
        self.revision = None
        self.send(dict(op='serve'))

    def _errors(self):
        for line in self.process.stderr:
            self.errors.append(line)
            del self.errors[:-200]

    def alive(self):
        return self.process.poll() is None

    def send(self, message):
        self.process.stdin.write(json.dumps(message) + '\n'); self.process.stdin.flush()

    def kill(self):
        try:
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait()
        except OSError:
            pass


class ScriptService:
    GRACE = 2  # seconds a stopping script has to end after ctx.sleep returns False

    def __init__(self, runtime):
        self.runtime = runtime
        self.project = runtime.project
        self.queue = Queue(maxsize=128)
        self.stop_event = Event()
        self.thread = None
        self.background = {}
        self.logs = deque(maxlen=500)
        self.lock = Lock()
        self.state = {}
        self.idle = []          # Runner processes waiting for the next execution
        self.limited = {}       # script -> thread running it (scripts with a time limit)
        self.pending = {}       # script -> events waiting for its running execution to end

    def log(self, name, status, message):
        with self.lock:
            self.logs.append(dict(time=time.time(), script=name, status=status, message=message))

    def diagnostics(self):
        with self.lock:
            return list(self.logs)

    def running(self):
        """Scripts without a limit that are running now."""
        with self.lock:
            return sorted(name for name, thread in self.background.items() if thread.is_alive())

    def submit(self, name, event='manual', screen=''):
        if name not in self.project.scripts:
            raise ValueError(tr('Script inexistente'))
        if self.stop_event.is_set():
            return
        try:
            self.queue.put_nowait((name, event, screen))
        except Full:
            self.log(name, 'error', tr('Cola de eventos llena; evento descartado'))

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear(); self.state.clear(); self.background.clear(); self.limited.clear()
        self.thread = Thread(target=self.run, name='abscada-scripts', daemon=True)
        self.thread.start()

    def stop(self, timeout=5):
        self.stop_event.set()
        deadline = time.monotonic() + timeout
        with self.lock:
            threads = ([self.thread] if self.thread else []) + list(self.background.values()) + list(self.limited.values())
        for thread in threads:
            if thread.ident is not None:
                thread.join(max(0, deadline - time.monotonic()))
        with self.lock:
            idle, self.idle = self.idle, []
        for runner in idle:
            runner.kill()
        if any(thread.is_alive() for thread in threads):
            raise TimeoutError(tr('Los scripts siguen terminando'))
        while not self.queue.empty():
            try: self.queue.get_nowait()
            except Empty: break

    def acquire(self):
        """A waiting runner process, or a new one."""
        with self.lock:
            while self.idle:
                runner = self.idle.pop()
                if runner.alive():
                    return runner
                runner.kill()
        return Runner(self.project.root)

    def release(self, runner):
        with self.lock:
            if not self.stop_event.is_set() and runner.alive() and len(self.idle) < IDLE_RUNNERS:
                self.idle.append(runner)
                return
        runner.kill()

    def busy(self, name):
        with self.lock:
            return any(name in group and group[name].is_alive() for group in (self.background, self.limited))

    def run(self):
        # Initialization is a barrier: no screen event or periodic task may
        # observe a partly initialized project, even when startup takes time.
        # Startup scripts without a limit are started, not awaited.
        for name in self.project.automation.get('startup', []):
            if self.stop_event.is_set(): return
            self.dispatch(name, 'startup', '')
            self.join_limited()
        tasks = [t for t in self.project.automation.get('tasks', []) if t.get('enabled', True)]
        due = {t['id']: time.monotonic()+t['interval_ms']/1000 for t in tasks}
        while not self.stop_event.is_set():
            wait = min([max(0.0, d - time.monotonic()) for d in due.values()] + [0.5])
            try:
                self.dispatch(*self.queue.get(timeout=max(0.005, wait)))
            except Empty:
                pass
            for task in tasks:
                if self.stop_event.is_set(): break
                now = time.monotonic()
                if now >= due[task['id']]:
                    # A task starts its script again once the previous execution has ended.
                    if not self.busy(task['script']):
                        self.dispatch(task['script'], 'task:'+task['id'], '')
                    # The period does not drift with the time the script takes; after a long
                    # pause (a busy PC) it starts again from now instead of catching up.
                    period = task['interval_ms']/1000
                    due[task['id']] += period
                    if due[task['id']] <= now:
                        due[task['id']] = now + period

    def join_limited(self):
        """Startup is a barrier: wait for the startup scripts that have a time limit."""
        with self.lock:
            threads = list(self.limited.values())
        for thread in threads:
            while thread.is_alive() and not self.stop_event.is_set():
                thread.join(0.05)

    def dispatch(self, name, event, screen):
        if script_timeout(self.project, name) is not None:
            # One execution of each script at a time; other scripts run meanwhile.
            with self.lock:
                running = self.limited.get(name)
                if running is not None and running.is_alive():
                    pending = self.pending.setdefault(name, deque())
                    if len(pending) < 32:
                        pending.append((event, screen))
                    else:
                        self.log(name, 'error', tr('Cola de eventos llena; evento descartado'))
                    return
                thread = Thread(target=self.execute_limited, args=(name, event, screen), name='abscada-script-'+name, daemon=True)
                self.limited[name] = thread
            thread.start()
            return
        with self.lock:
            busy = name in self.background and self.background[name].is_alive()
            if not busy:
                thread = Thread(target=self.execute, args=(name, event, screen), name='abscada-script-'+name, daemon=True)
                self.background[name] = thread
        if busy:
            self.log(name, 'error', tr('Ya está en ejecución; evento «{event}» descartado', event=event))
            return
        self.log(name, 'running', tr('En ejecución sin límite de tiempo ({event})', event=event))
        thread.start()

    def execute_limited(self, name, event, screen):
        """Run a script with a time limit, then the events that arrived for it meanwhile."""
        while True:
            self.execute(name, event, screen)
            with self.lock:
                pending = self.pending.get(name)
                if self.stop_event.is_set() or not pending:
                    self.pending.pop(name, None)
                    return
                event, screen = pending.popleft()

    def apply(self, name, actions, change, state):
        """Validate every requested write before applying any of them."""
        from .project import coerce
        for tag, value, *quality in actions:
            definition = self.runtime.tags.get(tag)
            if definition is None:
                raise ValueError(tr("{tag}: variable inexistente", tag=tag))
            if not definition.get('writable'):
                raise ValueError(tr("{tag}: solo lectura", tag=tag))
            if quality:
                if definition.get('binding'):
                    raise ValueError(tr("{tag}: solo se puede cambiar la calidad de variables internas", tag=tag))
                if quality[0] not in ('good', 'uncertain', 'bad'):
                    raise ValueError(tr("{tag}: calidad desconocida", tag=tag))
                continue
            coerce(value, definition['type'])
            if definition.get('binding') and self.runtime.snapshot()[tag].quality != 'good':
                raise ValueError(tr("{tag}: lectura no válida", tag=tag))
        if change is not None and change not in self.project.manifest.get('languages', ['es']):
            raise ValueError('Idioma de proyecto desconocido')
        for tag, value, *quality in actions:
            if quality:
                self.runtime.set_quality(tag, *quality)
            else:
                self.runtime.write(tag, value)
        if change is not None:
            self.runtime.set_language(change)
        self.state[name] = state

    def samples(self):
        return {n: dict(value=s.value, quality=s.quality) for n, s in self.runtime.snapshot().items()}

    def changes(self, runner):
        """What ``runner`` does not know yet: {'samples': all} or {'changes': changed only}."""
        revision, names = self.runtime.changes(runner.revision)
        runner.revision = revision
        if names is None:
            return dict(samples=self.samples())
        result = {}
        for name in names:
            sample = self.runtime.sample(name)
            result[name] = dict(value=sample.value, quality=sample.quality)
        return dict(changes=result)

    def execute(self, name, event, screen):
        request = dict(source=self.project.scripts[name], filename=f'scripts/{name}.py', event=event,
                       language=self.runtime.language, languages=self.project.manifest.get('languages', ['es']),
                       screen=screen, state=self.state.get(name, {}))
        limit = script_timeout(self.project, name)
        deadline = None if limit is None else time.monotonic() + limit
        runner, finished = None, False
        try:
            runner = self.acquire()
            process, lines, errors = runner.process, runner.lines, runner.errors
            request.update(self.changes(runner))
            runner.send(request)
            stopping = None
            while True:
                if self.stop_event.is_set() and stopping is None:
                    stopping = time.monotonic()
                if stopping is not None and (limit is not None or time.monotonic() - stopping > self.GRACE):
                    raise TimeoutError(tr('Ejecución cancelada'))
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError(tr('Tiempo de ejecución excedido'))
                try:
                    line = lines.get(timeout=.05)
                except Empty:
                    continue
                if line is None:
                    process.wait(1)
                    raise ValueError(''.join(errors).strip() or tr('El proceso del script terminó sin resultado'))
                message = json.loads(line)
                if message.get('op') == 'result':
                    finished = True
                    break
                self.sync(name, message, runner, deadline)
            if not message['ok']:
                raise ValueError(message.get('error', tr('Error de script')))
            if self.stop_event.is_set():
                # Writes requested while the Runtime stops are not applied.
                self.log(name, 'ok', message.get('output', '') or tr('Detenido con el runtime'))
                return
            self.apply(name, message['actions'], message.get('language_change'), message['state'])
            self.log(name, 'ok', message.get('output', '') or event)
        except Exception as exc:
            self.log(name, 'error', str(exc))
        finally:
            if runner is not None:
                # A process that answered goes back to the pool; one cut off is killed.
                self.release(runner) if finished else runner.kill()

    def sync(self, name, message, runner, deadline):
        """Answer ctx.commit()/ctx.sleep(): apply, log the output, wait, send fresh samples."""
        if message.get('output'):
            self.log(name, 'output', message['output'])
        reply = dict(ok=True)
        try:
            if not self.stop_event.is_set():
                self.apply(name, message.get('actions', []), message.get('language_change'), message.get('state', {}))
        except Exception as exc:
            reply = dict(ok=False, error=str(exc))
        wake = time.monotonic() + message.get('sleep', 0)
        if deadline is not None:
            wake = min(wake, deadline)
        self.stop_event.wait(max(0, wake - time.monotonic()))
        reply.update(stop=self.stop_event.is_set(), **self.changes(runner))
        try:
            runner.send(reply)
        except OSError:
            pass  # the process has already ended; its result or error follows
