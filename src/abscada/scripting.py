"""Event/task scheduler with killable Python execution.

Scripts with a time limit run one after another; scripts without a limit run in parallel,
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
        self.stop_event.clear(); self.state.clear(); self.background.clear()
        self.thread = Thread(target=self.run, name='abscada-scripts', daemon=True)
        self.thread.start()

    def stop(self, timeout=5):
        self.stop_event.set()
        deadline = time.monotonic() + timeout
        with self.lock:
            threads = ([self.thread] if self.thread else []) + list(self.background.values())
        for thread in threads:
            if thread.ident is not None:
                thread.join(max(0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in threads):
            raise TimeoutError(tr('Los scripts siguen terminando'))
        while not self.queue.empty():
            try: self.queue.get_nowait()
            except Empty: break

    def run(self):
        # Initialization is a barrier: no screen event or periodic task may
        # observe a partly initialized project, even when startup takes time.
        # Startup scripts without a limit are started, not awaited.
        for name in self.project.automation.get('startup', []):
            if self.stop_event.is_set(): return
            self.dispatch(name, 'startup', '')
        tasks = [t for t in self.project.automation.get('tasks', []) if t.get('enabled', True)]
        due = {t['id']: time.monotonic()+t['interval_ms']/1000 for t in tasks}
        while not self.stop_event.is_set():
            try:
                self.dispatch(*self.queue.get(timeout=.05))
            except Empty:
                pass
            for task in tasks:
                if self.stop_event.is_set(): break
                if time.monotonic() >= due[task['id']]:
                    # On a script without a limit, a task starts it again once it has ended.
                    if task['script'] not in self.running():
                        self.dispatch(task['script'], 'task:'+task['id'], '')
                    due[task['id']] = time.monotonic()+task['interval_ms']/1000

    def dispatch(self, name, event, screen):
        if script_timeout(self.project, name) is not None:
            self.execute(name, event, screen)
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

    def execute(self, name, event, screen):
        request = dict(source=self.project.scripts[name], filename=f'scripts/{name}.py', event=event,
                       language=self.runtime.language, languages=self.project.manifest.get('languages', ['es']),
                       screen=screen, state=self.state.get(name, {}), samples=self.samples())
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        limit = script_timeout(self.project, name)
        deadline = None if limit is None else time.monotonic() + limit
        process = None
        try:
            from .app_paths import script_runner_command
            process = subprocess.Popen(script_runner_command(),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8',
                cwd=self.project.root, creationflags=flags)
            lines, errors = Queue(), []
            Thread(target=_pump, args=(process.stdout, lines), daemon=True).start()
            Thread(target=lambda: errors.append(process.stderr.read()), daemon=True).start()
            process.stdin.write(json.dumps(request) + '\n'); process.stdin.flush()
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
                    break
                self.sync(name, message, process, deadline)
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
            if process and process.poll() is None:
                process.kill()
            if process:
                process.wait()

    def sync(self, name, message, process, deadline):
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
        reply.update(stop=self.stop_event.is_set(), samples=self.samples())
        try:
            process.stdin.write(json.dumps(reply) + '\n'); process.stdin.flush()
        except OSError:
            pass  # the process has already ended; its result or error follows
