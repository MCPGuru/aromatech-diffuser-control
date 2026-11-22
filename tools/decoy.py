#!/usr/bin/env python3
"""Stand-in diffuser: this computer pretends to be the diffuser over Bluetooth.

Purpose: learn what a phone app sends to the diffuser. It answers the app's questions
with answers recorded from a real unit (serial and address replaced with dummies) and
writes down every message the app sends, in decoy.log beside this file. Nothing here
touches a real diffuser - unplug the real one while this runs so the app cannot pick it
by mistake. Built for macOS; untested against a real phone app so far.

  pip install bless
  python tools/decoy.py [--name Smart.A7.WIFI] [--minutes 30]
"""
import asyncio, pathlib, sys, time
from bless import BlessServer, GATTCharacteristicProperties as P, GATTAttributePermissions as A

HERE = pathlib.Path(__file__).resolve().parent
LOG = HERE / "decoy.log"
NAME = sys.argv[sys.argv.index("--name") + 1] if "--name" in sys.argv else "Smart.A7.WIFI"
MINUTES = float(sys.argv[sys.argv.index("--minutes") + 1]) if "--minutes" in sys.argv else 30
SVC = "0000fff0-0000-1000-8000-00805f9b34fb"
F1, F2, F3, F4 = (f"0000fff{i}-0000-1000-8000-00805f9b34fb" for i in (1, 2, 3, 4))
SCHED = bytes.fromhex("0800 0b00 10 000a 0078  0c00 1605 11 000f 005a".replace(" ", "")) + bytes.fromhex("0000000010000000 00".replace(" ", "")) * 3
state = {"power": 1, "fan": 0x10}


def log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


def frame(p):
    x = 0
    for b in p:
        x ^= b
    return bytes([0xA5, 0xAA, 0xAC, x]) + bytes(p) + bytes([0xC5, 0xCC, 0xCA])


def clock():
    t = time.localtime()
    return bytes([t.tm_year >> 8, t.tm_year & 255, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec, t.tm_wday + 1])


CYCLE = bytes.fromhex("01000f005a0c00160501")


def answers(p):
    """Replies (list of payloads) to one payload from the app."""
    if p[0] == 0x52 and len(p) >= 2:
        q = p[1]
        table = {
            0x01: b"1234" + NAME.encode(), 0x02: clock(), 0x03: bytes([state["fan"]]), 0x04: b"\x00\x00",
            0x07: b"\x01", 0x08: bytes([state["power"]]), 0x09: CYCLE,
            0x0A: clock() + bytes([state["fan"], state["power"]]) + CYCLE,
            0x0C: bytes.fromhex("001122334455"),
            0x0D: b"SL150_DZ".ljust(20, b"\0") + b"V2.0.20251012".ljust(21, b"\0") + b"\x02" + b"000000000000000",
            0x12: b"\x01", 0x15: SCHED * 7, 0x06: SCHED, 0x1F: b"0" * 20,
        }
        if q in table:
            return [bytes([0x52, q]) + table[q]]
        return [bytes([0x52, q]) + b"NACK"]
    if p[0] == 0x57 and len(p) >= 2:
        out = [bytes([0x57, p[1]]) + b"ACK"]
        if p[1] == 0x08 and len(p) > 2:
            state["power"] = p[2]; out.append(bytes([0x53, 0x08, p[2]]))
        if p[1] == 0x03 and len(p) > 2:
            state["fan"] = p[2]; out.append(bytes([0x53, 0x03, p[2]]))
        if p[1] == 0x17:
            out.append(bytes([0x53, 0x0A]) + clock() + bytes([state["fan"], state["power"]]) + CYCLE)
        return out
    return []


async def main():
    server = BlessServer(name=NAME)
    buf = bytearray()

    def on_read(ch, **kw):
        log(f"READ  {str(ch.uuid)[4:8]}")
        return ch.value or bytearray(b"\x56\x78\x90")

    def on_write(ch, value, **kw):
        v = bytes(value)
        txt = "".join(chr(b) if 32 <= b < 127 else "." for b in v)
        log(f"WRITE {str(ch.uuid)[4:8]} {v.hex(' ')}  |{txt}|")
        buf.extend(v)
        while True:
            s = buf.find(b"\xA5\xAA\xAC"); e = buf.find(b"\xC5\xCC\xCA", s + 4) if s >= 0 else -1
            if s < 0 or e < 0:
                break
            p = bytes(buf[s + 4:e]); del buf[:e + 3]
            for a in answers(p):
                f = frame(a)
                log(f"   reply {a[:24].hex(' ')}{' ...' if len(a) > 24 else ''}")
                for i in range(0, len(f), 180):
                    c = server.get_characteristic(F1); c.value = bytearray(f[i:i + 180]); server.update_value(SVC, F1)

    server.read_request_func = on_read
    server.write_request_func = on_write
    await server.add_new_service(SVC)
    await server.add_new_characteristic(SVC, F2, P.write, None, A.writeable)
    await server.add_new_characteristic(SVC, F3, P.indicate, None, A.readable)
    await server.add_new_characteristic(SVC, F1, P.read | P.notify, None, A.readable)
    await server.add_new_characteristic(SVC, F4, P.write_without_response, None, A.writeable)
    await server.start()
    log(f"DECOY UP as {NAME} for {MINUTES} min")
    await asyncio.sleep(MINUTES * 60)
    await server.stop()
    log("DECOY STOPPED")

asyncio.run(main())
