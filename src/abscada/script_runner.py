"""Isolated execution process. JSON input/output; no Qt or PLC clients."""
import contextlib
import io
import json
import sys
import traceback


class TailOutput(io.TextIOBase):
    """Retain a bounded tail while printing, not after building an unbounded buffer."""
    def __init__(self, limit=16000):
        self.limit, self.tail = limit, ''

    def write(self, text):
        self.tail = (self.tail + text[-self.limit:])[-self.limit:]
        return len(text)

    def getvalue(self):
        return self.tail


class Context:
    def __init__(self, request):
        self.event = request['event']
        self.screen = request.get('screen', '')
        self.state = request.get('state', {})
        self.samples = request['samples']
        self.actions = []

    def read(self, name):
        sample = self.samples[name]
        if sample['quality'] != 'good':
            raise ValueError(f'{name}: calidad {sample["quality"]}')
        return sample['value']

    def quality(self, name):
        return self.samples[name]['quality']

    def write(self, name, value):
        if len(self.actions) >= 1000:
            raise ValueError('Máximo de 1000 operaciones por ejecución')
        self.actions.append([name, value])


def _pipe(stream, fd, mode):
    # A windowed .exe has no console streams; the Runtime's pipes are still fds 0 and 1.
    return stream if stream is not None else io.open(fd, mode, encoding='utf-8', closefd=False)


def main():
    sys.stdin = _pipe(sys.stdin, 0, 'r')
    sys.stdout = _pipe(sys.stdout, 1, 'w')
    request = json.load(sys.stdin)
    ctx = Context(request)
    output = TailOutput()
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            exec(compile(request['source'], request['filename'], 'exec'), {'ctx': ctx, '__name__': '__scada_script__'})
        response = dict(ok=True, actions=ctx.actions, state=ctx.state, output=output.getvalue()[-16000:])
        encoded = json.dumps(response, allow_nan=False)
    except BaseException:
        encoded = json.dumps(dict(ok=False, error=traceback.format_exc()[-16000:], output=output.getvalue()[-16000:]))
    sys.stdout.write(encoded)
    sys.stdout.flush()


if __name__ == '__main__':
    main()
