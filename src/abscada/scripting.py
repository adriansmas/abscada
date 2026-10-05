"""Bounded sequential event/task scheduler with killable Python execution."""
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from threading import Thread, Event, Lock
from queue import Queue, Empty, Full
from collections import deque


def validate_scripts(project):
    for name, source in project.scripts.items():
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name) or not isinstance(source, str):
            raise ValueError('Nombre o contenido de script inválido')
        try:
            compile(source, f'scripts/{name}.py', 'exec')
        except SyntaxError as exc:
            raise ValueError(f'{name}, línea {exc.lineno}: {exc.msg}') from exc
    def references(items):
        if not isinstance(items, list) or any(not isinstance(n, str) or n not in project.scripts for n in items):
            raise ValueError('Referencia a script inexistente')
    references(project.automation.get('startup', []))
    timeout = project.automation.get('timeout_seconds', 10)
    if type(timeout) not in (int, float) or not 0.1 <= timeout <= 300:
        raise ValueError('El límite de ejecución debe estar entre 0,1 y 300 segundos')
    ids = set()
    for task in project.automation.get('tasks', []):
        if not isinstance(task.get('id'), str) or not task['id'].strip() or task['id'] in ids:
            raise ValueError('Nombre de tarea vacío o duplicado')
        ids.add(task['id']); references([task.get('script')])
        if type(task.get('interval_ms')) is not int or not 100 <= task['interval_ms'] <= 86400000:
            raise ValueError('El periodo de tarea debe estar entre 100 y 86400000 ms')
        if not isinstance(task.get('enabled', True), bool):
            raise ValueError('Estado de tarea inválido')
    for document in project.screens.values():
        references(document.get('on_open', []))
    for document in list(project.screens.values()) + list(project.faceplates.values()):
        for element in document['elements']:
            if element['kind'] == 'button' and element.get('action') == 'script':
                references([element.get('script')])


class ScriptService:
    def __init__(self, runtime):
        self.runtime = runtime
        self.project = runtime.project
        self.queue = Queue(maxsize=128)
        self.stop_event = Event()
        self.thread = None
        self.logs = deque(maxlen=500)
        self.lock = Lock()
        self.state = {}

    def log(self, name, status, message):
        with self.lock:
            self.logs.append(dict(time=time.time(), script=name, status=status, message=message))

    def diagnostics(self):
        with self.lock:
            return list(self.logs)

    def submit(self, name, event='manual', screen=''):
        if name not in self.project.scripts:
            raise ValueError('Script inexistente')
        if self.stop_event.is_set():
            return
        try:
            self.queue.put_nowait((name, event, screen))
        except Full:
            self.log(name, 'error', 'Cola de eventos llena; evento descartado')

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear(); self.state.clear()
        self.thread = Thread(target=self.run, name='abscada-scripts', daemon=True)
        self.thread.start()

    def stop(self, timeout=5):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout)
            if self.thread.is_alive():
                raise TimeoutError('Los scripts siguen terminando')
        while not self.queue.empty():
            try: self.queue.get_nowait()
            except Empty: break

    def run(self):
        # Initialization is a barrier: no screen event or periodic task may
        # observe a partly initialized project, even when startup takes time.
        for name in self.project.automation.get('startup', []):
            if self.stop_event.is_set(): return
            self.execute(name, 'startup', '')
        tasks = [t for t in self.project.automation.get('tasks', []) if t.get('enabled', True)]
        due = {t['id']: time.monotonic()+t['interval_ms']/1000 for t in tasks}
        while not self.stop_event.is_set():
            try:
                self.execute(*self.queue.get(timeout=.05))
            except Empty:
                pass
            for task in tasks:
                if self.stop_event.is_set(): break
                if time.monotonic() >= due[task['id']]:
                    self.execute(task['script'], 'task:'+task['id'], '')
                    due[task['id']] = time.monotonic()+task['interval_ms']/1000

    def execute(self, name, event, screen):
        request = dict(source=self.project.scripts[name], filename=f'scripts/{name}.py', event=event,
                       screen=screen, state=self.state.get(name, {}),
                       samples={n:dict(value=s.value,quality=s.quality) for n,s in self.runtime.snapshot().items()})
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        process = None
        try:
            process = subprocess.Popen([sys.executable, '-I', str(Path(__file__).with_name('script_runner.py'))],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8',
                cwd=self.project.root, creationflags=flags)
            deadline = time.monotonic()+self.project.automation.get('timeout_seconds', 10)
            payload = json.dumps(request)
            while True:
                try:
                    output, error = process.communicate(payload, timeout=.1)
                    break
                except subprocess.TimeoutExpired:
                    payload = None
                    if self.stop_event.is_set() or time.monotonic() >= deadline:
                        process.kill(); process.communicate()
                        raise TimeoutError('Ejecución cancelada' if self.stop_event.is_set() else 'Tiempo de ejecución excedido')
            result = json.loads(output) if process.returncode == 0 else dict(ok=False,error=error)
            if not result['ok']:
                raise ValueError(result.get('error', 'Error de script'))
            if self.stop_event.is_set(): return
            # Validate every requested write before applying any of them.
            from .project import coerce
            for tag, value in result['actions']:
                definition = self.runtime.tags[tag]
                if not definition.get('writable'):
                    raise ValueError(f'{tag}: solo lectura')
                coerce(value, definition['type'])
                if definition.get('binding') and self.runtime.snapshot()[tag].quality != 'good':
                    raise ValueError(f'{tag}: lectura no válida')
            for tag, value in result['actions']:
                self.runtime.write(tag, value)
            self.state[name] = result['state']
            self.log(name, 'ok', result.get('output', '') or event)
        except Exception as exc:
            self.log(name, 'error', str(exc))
        finally:
            if process and process.poll() is None:
                process.kill(); process.communicate()
