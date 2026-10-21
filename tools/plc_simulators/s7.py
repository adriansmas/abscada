"""Small TCP S7 PLC simulator for integration development (DB1)."""
import argparse
import math
import struct
import time


def s7_server():
    """A python-snap7 server that writes single bits like a real CPU (WordLen.Bit).

    python-snap7's own server drops the bit number of the address and writes the whole byte,
    which would clear the neighbouring bits that abSCADA now leaves alone.
    """
    from snap7.server import Server

    class BitServer(Server):
        def _parse_address_specification(self, addr_spec):
            parsed = super()._parse_address_specification(addr_spec)
            if parsed and len(addr_spec) >= 12 and parsed.get("word_len") == 1:
                parsed["bit"] = addr_spec[11] & 7
            return parsed

        def _handle_write_area(self, request, client_address):
            spec = request.get("parameters", {}).get("address_spec", {})
            data = request.get("data", {})
            if spec.get("word_len") == 1 and data.get("data"):
                key = (spec["area"], spec["db_number"])
                memory = self.memory_areas.get(key)
                if memory is not None and spec["start"] < len(memory):
                    mask = 1 << spec.get("bit", 0)
                    current = memory[spec["start"]]
                    data["data"] = bytes([current | mask if data["data"][0] & 1 else current & ~mask & 0xFF])
            return super()._handle_write_area(request, client_address)

    return BitServer(log=False)


def create_server(port=1102):
    from snap7.type import SrvArea
    memory = bytearray(32)
    struct.pack_into(">f", memory, 8, 60.0)
    struct.pack_into(">f", memory, 24, 45.0)
    server = s7_server()
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
