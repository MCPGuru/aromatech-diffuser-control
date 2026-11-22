#!/usr/bin/env python3
"""Control an Aroma-Link family scent diffuser directly over Bluetooth - no internet, no account.

Tested on an AromaTech Ambience (factory model Starlight, firmware name SL150_DZ), which
broadcasts as "Smart.A7.WIFI". Other diffusers of the family broadcast "<name>.A<n>.WIFI";
change NAME_ENDS / MAKER_ID below if yours differs. Protocol: see PROTOCOL.md.

  --status       print on or off
  --on | --off   switch misting on or off (read back from the diffuser before reporting)
  --dry-run      say what would be sent only
  --minutes N    how long to keep trying to connect (default 4)

Things to know:
- The diffuser talks to ONE Bluetooth device at a time. While a phone app is connected
  it stops broadcasting and this script cannot reach it. Close the app.
- Range is short. Through a couple of walls, connections mostly time out.
- macOS only lets a script use Bluetooth when it is started from Terminal on the Mac
  itself or by launchd (it shows a permission prompt once), not from an SSH session.

Needs the bleak package:  pip install bleak
"""
import argparse
import asyncio
import sys
import time

WRITE = "0000fff2-0000-1000-8000-00805f9b34fb"
NOTIFY = "0000fff1-0000-1000-8000-00805f9b34fb"
NAME_ENDS = ".WIFI"
MAKER_ID = 17750  # in the diffuser's broadcast; guards against another ".WIFI" gadget


def frame(payload):
    x = 0
    for b in payload:
        x ^= b
    return bytes([0xA5, 0xAA, 0xAC, x]) + bytes(payload) + bytes([0xC5, 0xCC, 0xCA])


def payloads(buf):
    """Split whatever has arrived into the payloads of complete frames."""
    out = []
    while True:
        s = buf.find(b"\xA5\xAA\xAC")
        e = buf.find(b"\xC5\xCC\xCA", s + 4) if s >= 0 else -1
        if s < 0 or e < 0:
            return out
        out.append(bytes(buf[s + 4:e]))
        del buf[:e + 3]


async def connect(minutes):
    from bleak import BleakClient, BleakScanner

    def ours(d, a):
        return (a.local_name or d.name or "").endswith(NAME_ENDS) and MAKER_ID in a.manufacturer_data

    end = time.time() + minutes * 60
    tries = 0
    while time.time() < end:
        dev = await BleakScanner.find_device_by_filter(ours, timeout=30)
        if not dev:
            continue
        tries += 1
        try:
            c = BleakClient(dev, timeout=12)
            await c.connect()
            return c, tries
        except Exception:
            pass
    raise RuntimeError(f"could not connect to the diffuser in {minutes} min ({tries} tries) - "
                       "too far away, or the phone app is holding it")


async def run(action, minutes):
    c, tries = await connect(minutes)
    buf = bytearray()
    got = []
    try:
        await c.start_notify(NOTIFY, lambda _, d: buf.extend(d))

        async def ask(payload, want, wait=4):
            await c.write_gatt_char(WRITE, frame(payload), response=True)
            end = time.time() + wait
            while time.time() < end:
                got.extend(payloads(buf))
                for p in got:
                    if want(p):
                        return p
                await asyncio.sleep(0.1)
            return None

        if action in ("on", "off"):
            v = 1 if action == "on" else 0
            for _ in range(3):
                got.clear()
                await ask([0x57, 0x08, v], lambda p: p[:2] == b"\x57\x08", wait=3)
                got.clear()
                st = await ask([0x52, 0x08], lambda p: len(p) == 3 and p[:2] == b"\x52\x08")
                if st and st[2] == v:
                    return f"diffuser {action} (confirmed, connect tries {tries})"
            raise RuntimeError(f"sent {action} but the diffuser did not confirm it")
        st = await ask([0x52, 0x08], lambda p: len(p) == 3 and p[:2] == b"\x52\x08")
        if not st:
            raise RuntimeError("connected but got no answer")
        return "diffuser is " + ("on" if st[2] else "off")
    finally:
        try:
            await c.disconnect()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true")
    g.add_argument("--on", action="store_true")
    g.add_argument("--off", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--minutes", type=float, default=4)
    a = ap.parse_args()
    action = "on" if a.on else "off" if a.off else "status"
    if a.dry_run:
        print(f"DRY-RUN: diffuser -> {action}")
        return 0
    try:
        print(asyncio.run(run(action, a.minutes)))
        return 0
    except Exception as e:
        print(f"FAILED: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
