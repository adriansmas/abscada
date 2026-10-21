"""Isolated execution process. JSON lines in and out; no Qt or PLC clients.

The Runtime sends the request as the first line. While the script runs, ``ctx.commit()`` and
``ctx.sleep()`` send a ``sync`` line (pending writes, state and output) and wait for the reply
(accepted or not, fresh samples, and whether the Runtime is stopping). The last line is the result.

A first line ``{"op": "serve"}`` keeps the process for many executions, one after another:
starting Python for every task was most of the cost of the scripts. Then requests and replies
carry ``changes`` (only the samples that changed since the previous message) instead of all
the ``samples``; each execution still runs in fresh globals.
"""
import contextlib
import io
import json
import sys
import traceback


class TailOutput(io.TextIOBase):
    """Retain a bounded tail while printing, not after building an unbounded buffer.
    ``pending`` holds what has not been sent to the Runtime yet."""
    def __init__(self, limit=16000):
        self.limit, self.tail, self.pending = limit, '', ''

    def write(self, text):
        self.tail = (self.tail + text[-self.limit:])[-self.limit:]
        self.pending = (self.pending + text[-self.limit:])[-self.limit:]
        return len(text)

    def getvalue(self):
        return self.tail

    def take(self):
        text, self.pending = self.pending, ''
        return text


class Context:
    def __init__(self, request, channel=None, output=None):
        self.event = request['event']
        self.screen = request.get('screen', '')
        self.state = request.get('state', {})
        self.samples = request['samples']
        self.actions = []
        self.language = request.get('language', 'es')
        self.languages = request.get('languages', ['es'])
        self.language_change = None
        self.stopping = False
        self._channel, self._output = channel, output

    def set_language(self, code):
        if code not in self.languages:
            raise ValueError(f'Idioma desconocido: {code}')
        self.language = self.language_change = code

    def read(self, name):
        sample = self.samples[name]
        if sample['quality'] != 'good':
            raise ValueError(f'{name}: calidad {sample["quality"]}')
        return sample['value']

    def quality(self, name):
        return self.samples[name]['quality']

    def write(self, name, value):
        if len(self.actions) >= 1000:
            raise ValueError('Máximo de 1000 operaciones por ejecución; usa ctx.commit() para aplicarlas antes')
        self.actions.append([name, value])

    def set_quality(self, name, quality, reason=''):
        """Change the quality of an internal variable and keep its value; ctx.write() makes it good again."""
        if quality not in ('good', 'uncertain', 'bad'):
            raise ValueError('Calidad desconocida: usa "good", "uncertain" o "bad"')
        if len(self.actions) >= 1000:
            raise ValueError('Máximo de 1000 operaciones por ejecución; usa ctx.commit() para aplicarlas antes')
        self.actions.append([name, None, quality, str(reason)])

    def commit(self):
        """Apply the pending writes, language and state now, and read fresh samples."""
        self._sync(0)

    def sleep(self, seconds):
        """Commit, wait and read fresh samples. Returns False when the Runtime is stopping:
        the script must finish then. Use it in loops: ``while ctx.sleep(1): ...``."""
        if type(seconds) not in (int, float) or not 0 <= seconds <= 86400:
            raise ValueError('ctx.sleep: de 0 a 86400 segundos')
        self._sync(seconds)
        return not self.stopping

    def _sync(self, seconds):
        if self._channel is None:
            raise RuntimeError('ctx.commit y ctx.sleep solo funcionan dentro del Runtime')
        actions, change = self.actions, self.language_change
        self.actions, self.language_change = [], None
        reply = self._channel(dict(op='sync', sleep=seconds, actions=actions, language_change=change,
                                   state=self.state, output=self._output.take() if self._output else ''))
        self.stopping = reply.get('stop', False)
        if 'samples' in reply:
            self.samples = reply['samples']
        if 'changes' in reply:
            self.samples = dict(self.samples, **reply['changes'])
        if not reply['ok']:
            raise ValueError(reply['error'])


def _pipe(stream, fd, mode):
    # A windowed .exe has no console streams; the Runtime's pipes are still fds 0 and 1.
    return stream if stream is not None else io.open(fd, mode, encoding='utf-8', closefd=False)


def main():
    stdin = _pipe(sys.stdin, 0, 'r')
    stdout = _pipe(sys.stdout, 1, 'w')
    request = json.loads(stdin.readline())
    if request.get('op') != 'serve':
        execute(request, stdin, stdout)
        return
    samples = {}
    while True:
        line = stdin.readline()
        if not line:
            return   # the Runtime closed the pipe: nothing more to run
        request = json.loads(line)
        if 'samples' in request:
            samples = request['samples']
        samples.update(request.get('changes', {}))
        execute(dict(request, samples=dict(samples)), stdin, stdout, samples)


def execute(request, stdin, stdout, known=None):
    """Run one script. ``known`` (serve mode) is kept up to date with the samples received."""
    output = TailOutput()

    def channel(message):
        stdout.write(json.dumps(message, allow_nan=False) + '\n')
        stdout.flush()
        line = stdin.readline()
        if not line:
            raise SystemExit('Runtime detenido')
        reply = json.loads(line)
        if known is not None and 'changes' in reply:
            known.update(reply['changes'])
        return reply

    ctx = Context(request, channel, output)
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            exec(compile(request['source'], request['filename'], 'exec'), {'ctx': ctx, '__name__': '__scada_script__'})
        response = dict(op='result', ok=True, language_change=ctx.language_change, actions=ctx.actions,
                        state=ctx.state, output=output.take()[-16000:])
        encoded = json.dumps(response, allow_nan=False)
    except BaseException:
        encoded = json.dumps(dict(op='result', ok=False, error=traceback.format_exc()[-16000:], output=output.take()[-16000:]))
    stdout.write(encoded + '\n')
    stdout.flush()


if __name__ == '__main__':
    main()
