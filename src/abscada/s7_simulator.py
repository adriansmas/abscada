"""Small TCP S7 PLC simulator for integration development (DB1)."""
import argparse
import math
import struct
import time


def create_server(port=1102):
    from snap7.server import Server
    from snap7.type import SrvArea
    memory = bytearray(32)
    struct.pack_into(">f", memory, 8, 60.0)
    struct.pack_into(">f", memory, 24, 45.0)
    server = Server(log=False)
    server.host = "127.0.0.1"
    server.register_area(SrvArea.DB, 1, memory)
    server.start(tcp_port=port)
    return server, memory


def main(argv=None):
    parser = argparse.ArgumentParser(description="PLC Siemens S7 simulado · DB1")
    parser.add_argument("--port", type=int, default=1102)
    args = parser.parse_args(argv)
    server, memory = create_server(args.port)
    print(f"PLC simulado en puerto {args.port}: DB1.X0.0 marcha, DB1.R4 caudal, DB1.R8 consigna, DB1.R12 nivel", flush=True)
    try:
        while True:
            for offset in (0, 16):
                enabled = bool(memory[offset] & 1)
                setpoint = struct.unpack_from(">f", memory, offset + 8)[0]
                struct.pack_into(">f", memory, offset + 4, setpoint if enabled else 0.0)
            struct.pack_into(">f", memory, 12, 50 + 35 * math.sin(time.monotonic() / 5))
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        server.destroy()


if __name__ == "__main__":
    main()
