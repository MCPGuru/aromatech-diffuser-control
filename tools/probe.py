#!/usr/bin/env python3
"""Ask a diffuser every read-only question (payload 52 00 .. 52 FF) and print the answers.

Queries only - nothing is changed. Useful for a model nobody has documented yet.
  pip install bleak ;  python tools/probe.py
"""
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from diffuser import connect, frame, payloads, WRITE, NOTIFY


async def main():
    c, _ = await connect(4)
    buf = bytearray()
    try:
        for ch in c.services.characteristics.values():
            print("characteristic", ch.uuid[4:8], ch.properties)
        await c.start_notify(NOTIFY, lambda _, d: buf.extend(d))
        for code in range(0x100):
            await c.write_gatt_char(WRITE, frame([0x52, code]), response=True)
            await asyncio.sleep(0.35)
            for p in payloads(buf):
                if p[2:] == b"NACK":
                    continue
                txt = "".join(chr(b) if 32 <= b < 127 else "." for b in p)
                print(f"query {code:02x}: {p.hex(' ')}  |{txt}|", flush=True)
    finally:
        await c.disconnect()

asyncio.run(main())
