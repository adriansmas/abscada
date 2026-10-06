"""External TCP equipment for examples/showcase (S7 :1102, Modbus :1502). Never imported by Runtime."""
import argparse
import math
import struct
import time
from threading import Event, Thread


def words(fmt, value):
    data = struct.pack('>' + fmt, value)
    return list(struct.unpack('>' + 'H' * (len(data) // 2), data))


class LaboratoryPLCs:
    def __init__(self, protocol='both', s7_port=1102, modbus_port=1502):
        self.protocol, self.s7_port, self.modbus_port = protocol, s7_port, modbus_port
        self.s7 = self.modbus = self.thread = None
        self.stop_event = Event()

    def start(self):
        try:
            if self.protocol in ('s7', 'both'):
                from abscada.s7_simulator import create_server
                self.s7, self.memory = create_server(self.s7_port)
            if self.protocol in ('modbus', 'both'):
                from pyModbusTCP.server import ModbusServer
                self.modbus = ModbusServer(host='127.0.0.1', port=self.modbus_port, no_block=True)
                self.modbus.data_bank.set_holding_registers(0, words('f', 40.0) + [0])
                self.modbus.start()
                if not self.modbus.is_run:
                    raise RuntimeError('No se pudo abrir el puerto Modbus')
            self.thread = Thread(target=self._cycle, name='external-laboratory', daemon=True)
            self.thread.start()
            return self
        except BaseException:
            self.stop()
            raise

    def _cycle(self):
        start = time.monotonic()
        while not self.stop_event.is_set():
            elapsed = time.monotonic() - start
            if self.s7:
                for offset in (0, 16):
                    sp = struct.unpack_from('>f', self.memory, offset + 8)[0]
                    struct.pack_into('>f', self.memory, offset + 4, sp if self.memory[offset] & 1 else 0.0)
                struct.pack_into('>f', self.memory, 12, 50 + 35 * math.sin(elapsed / 10))
            if self.modbus:
                bank = self.modbus.data_bank
                enabled = bank.get_coils(0, 1)[0]
                registers = bank.get_holding_registers(0, 2)
                sp = struct.unpack('>f', struct.pack('>HH', *registers))[0]
                temperature = sp + 2 * math.sin(elapsed / 5) if enabled else 22.0
                bank.set_discrete_inputs(0, [enabled])
                bank.set_input_registers(0, words('f', temperature) + words('I', int(elapsed) % (2**32)))
            self.stop_event.wait(0.1)

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)
            self.thread = None
        if self.modbus:
            self.modbus.stop()
            self.modbus = None
        if self.s7:
            self.s7.stop()
            self.s7.destroy()
            self.s7 = None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol', choices=['both', 's7', 'modbus'], default='both')
    parser.add_argument('--s7-port', type=int, default=1102)
    parser.add_argument('--modbus-port', type=int, default=1502)
    args = parser.parse_args(argv)
    servers = LaboratoryPLCs(args.protocol, args.s7_port, args.modbus_port).start()
    print(f'Equipos externos activos en 127.0.0.1 ({args.protocol}). S7: {args.s7_port}; Modbus: {args.modbus_port}. Ctrl+C para detener.', flush=True)
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        servers.stop()


if __name__ == '__main__':
    main()
