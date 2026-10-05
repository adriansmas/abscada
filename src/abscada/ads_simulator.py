"""Small TwinCAT ADS PLC simulator for development and tests (pure Python).

Serves AMS/TCP with a symbol table (read/write by handle), %M/%I/%Q memory
areas and the PLC state. It is not a TwinCAT runtime: no routing, no
notifications, no sum commands.

    python -m abscada.ads_simulator            # demo test bench on 127.0.0.1:48898
"""
import argparse
import math
import socket
import struct
import threading
import time

from .ads import (CMD_READ, CMD_READ_DEVICE_INFO, CMD_READ_STATE, CMD_READ_WRITE, CMD_WRITE,
                  IG_SYM_HANDLE_BY_NAME, IG_SYM_RELEASE_HANDLE, IG_SYM_VALUE_BY_HANDLE, STATE_RESPONSE, TYPES)

AREAS = {0x4020: "M", 0xF020: "I", 0xF030: "Q"}


class Symbol:
    def __init__(self, encoding, value, length=80):
        self.encoding, self.length = encoding, length
        size = length + 1 if encoding == "STRING" else TYPES[encoding][1]
        self.data = bytearray(size)
        self.set(value)

    def set(self, value):
        if self.encoding == "STRING":
            raw = str(value).encode("cp1252")[: self.length]
            self.data[:] = raw + b"\x00" * (len(self.data) - len(raw))
        else:
            self.data[:] = struct.pack("<" + TYPES[self.encoding][0], value)

    def get(self):
        if self.encoding == "STRING":
            return bytes(self.data).split(b"\x00", 1)[0].decode("cp1252")
        return struct.unpack("<" + TYPES[self.encoding][0], self.data)[0]


class AdsSimulator:
    def __init__(self, symbols=None, host="127.0.0.1", port=48898, ams_port=851):
        self.host, self.port, self.ams_port = host, port, ams_port
        self.symbols = {}
        self.areas = {group: bytearray(4096) for group in AREAS}
        self.handles = {}
        self.next_handle = 0x1000
        self.lock = threading.RLock()
        self.running = True  # PLC in RUN
        self.server = None
        self.threads = []
        self.stop_event = threading.Event()
        for name, spec in (symbols or {}).items():
            self.add(name, *spec)

    # -- symbol table ----------------------------------------------------------
    def add(self, name, encoding, value, length=80):
        with self.lock:
            self.symbols[name.lower()] = Symbol(encoding, value, length)

    def get(self, name):
        with self.lock:
            return self.symbols[name.lower()].get()

    def set(self, name, value):
        with self.lock:
            self.symbols[name.lower()].set(value)

    def online_change(self):
        """Simulate a new PLC program: every handle becomes invalid."""
        with self.lock:
            self.handles.clear()

    # -- server ----------------------------------------------------------------
    def start(self):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind((self.host, self.port))
        self.port = self.server.getsockname()[1]
        self.server.listen()
        self.server.settimeout(0.2)
        thread = threading.Thread(target=self._accept, name="ads-sim", daemon=True)
        thread.start()
        self.threads.append(thread)
        return self

    def stop(self):
        self.stop_event.set()
        if self.server:
            self.server.close()
        for thread in self.threads:
            thread.join(timeout=2)

    def _accept(self):
        while not self.stop_event.is_set():
            try:
                client, _ = self.server.accept()
            except (socket.timeout, OSError):
                continue
            thread = threading.Thread(target=self._serve, args=(client,), daemon=True)
            thread.start()
            self.threads.append(thread)

    def _serve(self, client):
        client.settimeout(0.5)
        buffer = b""
        with client:
            while not self.stop_event.is_set():
                try:
                    chunk = client.recv(65536)
                except socket.timeout:
                    continue
                except OSError:
                    return
                if not chunk:
                    return
                buffer += chunk
                while len(buffer) >= 6:
                    length = struct.unpack_from("<I", buffer, 2)[0]
                    if len(buffer) < 6 + length:
                        break
                    frame, buffer = buffer[6:6 + length], buffer[6 + length:]
                    client.sendall(self._answer(frame))

    def _answer(self, frame):
        target, tport, source, sport, cmd, _, length, _, invoke = struct.unpack("<6sH6sHHHIII", frame[:32])
        payload = frame[32:32 + length]
        error, data = 0, b""
        if tport != self.ams_port:
            error = 0x6
        else:
            with self.lock:
                data = self._command(cmd, payload)
        header = struct.pack("<6sH6sHHHIII", source, sport, target, tport, cmd, STATE_RESPONSE, len(data), error, invoke)
        return struct.pack("<HI", 0, len(header) + len(data)) + header + data

    def _command(self, cmd, payload):
        ok = struct.pack("<I", 0)

        def fail(code):
            return struct.pack("<I", code) + (b"" if cmd == CMD_WRITE else struct.pack("<I", 0))

        if cmd == CMD_READ_STATE:
            return ok + struct.pack("<HH", 5 if self.running else 6, 0)
        if cmd == CMD_READ_DEVICE_INFO:
            return ok + struct.pack("<BBH", 3, 1, 4024) + b"abSCADA ADS sim".ljust(16, b"\x00")
        if cmd == CMD_READ:
            group, offset, size = struct.unpack_from("<III", payload)
            buffer = self._buffer(group, offset)
            if isinstance(buffer, int):
                return fail(buffer)
            data, start = buffer
            if start + size > len(data):
                return fail(0x705)
            return ok + struct.pack("<I", size) + bytes(data[start:start + size])
        if cmd == CMD_WRITE:
            group, offset, size = struct.unpack_from("<III", payload)
            body = payload[12:12 + size]
            if group == IG_SYM_RELEASE_HANDLE:
                self.handles.pop(struct.unpack("<I", body)[0], None)
                return ok
            buffer = self._buffer(group, offset)
            if isinstance(buffer, int):
                return fail(buffer)
            data, start = buffer
            if start + size > len(data):
                return fail(0x705)
            data[start:start + size] = body
            return ok
        if cmd == CMD_READ_WRITE:
            group, offset, read_size, write_size = struct.unpack_from("<IIII", payload)
            body = payload[16:16 + write_size]
            if group != IG_SYM_HANDLE_BY_NAME:
                return fail(0x701)
            name = body.split(b"\x00", 1)[0].decode("cp1252").strip().lower()
            if name not in self.symbols:
                return fail(0x710)
            handle = self.next_handle
            self.next_handle += 1
            self.handles[handle] = name
            return ok + struct.pack("<I", 4) + struct.pack("<I", handle)
        return fail(0x701)

    def _buffer(self, group, offset):
        if group == IG_SYM_VALUE_BY_HANDLE:
            name = self.handles.get(offset)
            return 0x710 if name is None else (self.symbols[name].data, 0)
        if group in self.areas:
            return self.areas[group], offset
        return 0x702


# --------------------------------------------------------------------------
# Demo: motor test bench used by examples/beckhoff
# --------------------------------------------------------------------------
DEMO_SYMBOLS = {
    "MAIN.bMarcha": ("BOOL", False),
    "MAIN.nModo": ("INT", 1),
    "MAIN.rConsignaVelocidad": ("REAL", 1500.0),
    "MAIN.rVelocidad": ("REAL", 0.0),
    "MAIN.rTemperatura": ("REAL", 22.0),
    "MAIN.rPresion": ("REAL", 1.0),
    "MAIN.nCiclos": ("DINT", 0),
    "MAIN.sEstado": ("STRING", "PARADO", 40),
    "GVL.bAlarmaTemperatura": ("BOOL", False),
}


def run_demo(sim, stop):
    """PLC logic of the demo bench: speed ramp, heating, oil pressure and cycle counter."""
    last = time.monotonic()
    second = 0.0
    while not stop.is_set():
        now = time.monotonic()
        dt, last = now - last, now
        with sim.lock:
            running = sim.get("MAIN.bMarcha")
            target = max(0.0, min(3000.0, sim.get("MAIN.rConsignaVelocidad"))) if running else 0.0
            speed = sim.get("MAIN.rVelocidad")
            step = 250.0 * dt
            speed = target if abs(target - speed) <= step else speed + math.copysign(step, target - speed)
            sim.set("MAIN.rVelocidad", speed)
            temperature = sim.get("MAIN.rTemperatura")
            heat_target = 22.0 + 70.0 * (speed / 3000.0) ** 1.5
            sim.set("MAIN.rTemperatura", temperature + (heat_target - temperature) * min(1.0, dt / 20.0))
            sim.set("MAIN.rPresion", 1.0 + 5.0 * speed / 3000.0 + 0.05 * math.sin(now * 3))
            sim.set("GVL.bAlarmaTemperatura", sim.get("MAIN.rTemperatura") > 85.0)
            state = "PARADO" if speed < 1 and not running else "EN MARCHA" if abs(speed - target) < 1 else "ACELERANDO" if speed < target else "DECELERANDO"
            sim.set("MAIN.sEstado", state)
            second += dt
            if second >= 1.0:
                second -= 1.0
                if running:
                    sim.set("MAIN.nCiclos", sim.get("MAIN.nCiclos") + 1)
        stop.wait(0.1)


def main():
    parser = argparse.ArgumentParser(description="PLC Beckhoff TwinCAT ADS simulado (banco de ensayo)")
    parser.add_argument("--port", type=int, default=48898, help="Puerto TCP AMS (48898 por defecto)")
    parser.add_argument("--ams-port", type=int, default=851, help="Puerto ADS del runtime PLC (851 TC3, 801 TC2)")
    args = parser.parse_args()
    try:
        sim = AdsSimulator(DEMO_SYMBOLS, port=args.port, ams_port=args.ams_port).start()
    except OSError as error:
        raise SystemExit(f"No se pudo abrir el puerto {args.port}: {error}. Si TwinCAT está instalado, usa --port 48899") from None
    stop = threading.Event()
    threading.Thread(target=run_demo, args=(sim, stop), daemon=True).start()
    print(f"PLC ADS simulado en 127.0.0.1:{sim.port}, puerto ADS {args.ams_port}. Símbolos: {', '.join(DEMO_SYMBOLS)}. Ctrl+C para detener.", flush=True)
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        sim.stop()


if __name__ == "__main__":
    main()
