#!/usr/bin/env python3
"""Control an Aroma-Link family scent diffuser over Wi-Fi, through the maker's internet service.

Works with diffusers that can be added to the factory "Aroma-Link" phone app - including
units sold under other brands (AromaTech Ambience, Crearoma/Ouwave Starlight, PRO300, ...).
Once on Wi-Fi these diffusers take no commands on the local network; they only listen to
www.aroma-link.com. This talks to that service the way the phone app does.

  --setup     ask for your Aroma-Link email and password and keep them (password as the
              MD5 hash the service expects) in aromalink-creds.json, readable only by you.
              Or set AROMALINK_USER and AROMALINK_PASSWORD in the environment instead.
  --list      show the diffusers on the account
  --status    print on or off (as the service last heard it)
  --on | --off
  --apply --power on|off [--intensity 1-100] [--hours H]
              set the mist strength, switch on, and remember to switch off after H hours
              (0 = no limit). Needs --state to be called regularly (see below).
  --state     print {"on", "intensity", "hours", "minutes_left"} as JSON, and switch the
              diffuser off if its timed run is over. Call it every minute from cron or
              from the Homebridge add-on in homebridge/.
  --device X  pick a diffuser by name, id or hardware address when the account has several
  --dry-run   say what would be sent only

Strength: the diffuser mists for some seconds, then rests. 100% = 30 s mist / 90 s rest,
57% = 15 s / 90 s, 20% = 5 s / 90 s, below that the rest gets longer, down to 5 s / 900 s.
These limits (5-30 s, 90-900 s) are what the service reports for model SL150_DZ; check
workStartTime/workEndTime/pauseStartTime/pauseEndTime in --raw-status for your model.

WARNING: setting a strength REPLACES the diffuser's stored weekly schedule with one
all-day, every-day window, so from then on it mists whenever it is switched on, and the
timer here (not the diffuser) ends a run. Write your schedule down first if you want it.

Standard library only (Python 3.8+). For a direct route that needs no internet, see
diffuser.py (Bluetooth).
"""
import argparse
import hashlib
import json
import os
import pathlib
import sys
import time
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
CREDS = HERE / "aromalink-creds.json"
BASE = "https://www.aroma-link.com"
UA = "Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
TIMEOUT = 15


STATE = HERE / "diffuser-state.json"


def call(path, form=None, token=None, body=None):
    headers = {"User-Agent": UA, "Accept": "application/json, text/plain, */*"}
    if token:
        headers["access_token"] = token
        headers["Authorization"] = token
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json;charset=UTF-8"
    req = urllib.request.Request(BASE + path, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        body = r.read().decode("utf-8", "replace")
    try:
        return json.loads(body)
    except ValueError:
        raise RuntimeError(f"unexpected reply from the service: {body[:120]}")


def ok(d):
    return isinstance(d, dict) and d.get("code") in (0, "0", 200, "200")


def setup():
    import getpass
    user = input("Aroma-Link email: ").strip()
    pw = getpass.getpass("Aroma-Link password: ")
    creds = {"userName": user, "passwordMd5": hashlib.md5(pw.encode()).hexdigest()}
    fd = os.open(CREDS, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(creds, fh)
    login()
    print("sign-in works - saved")
    return 0


def credentials():
    if os.environ.get("AROMALINK_USER") and os.environ.get("AROMALINK_PASSWORD"):
        return {"userName": os.environ["AROMALINK_USER"],
                "passwordMd5": hashlib.md5(os.environ["AROMALINK_PASSWORD"].encode()).hexdigest()}
    if not CREDS.exists():
        sys.exit("no Aroma-Link sign-in yet - run: aromalink.py --setup")
    return json.loads(CREDS.read_text())


def login():
    c = credentials()
    d = call("/v2/app/token", {"userName": c["userName"], "password": c["passwordMd5"]})
    if not ok(d):
        raise RuntimeError(f"sign-in refused: code {d.get('code')} {d.get('msg')}")
    inner = d.get("data") or {}
    token = inner.get("accessToken") or inner.get("access_token") or inner.get("token")
    uid = str(inner.get("id") or inner.get("userId") or "")
    if not token or not uid:
        raise RuntimeError("sign-in reply had no token")
    return token, uid


def flatten(x):
    """Every dict that looks like a device, wherever the service nests it."""
    if isinstance(x, dict):
        if x.get("type") == "device":
            yield x
        for v in x.values():
            yield from flatten(v)
    elif isinstance(x, list):
        for v in x:
            yield from flatten(v)


def devices(token, uid):
    d = call(f"/v1/app/device/listAll/{uid}", token=token)
    if not ok(d):
        raise RuntimeError(f"device list refused: code {d.get('code')} {d.get('msg')}")
    return list(flatten(d.get("data")))


def dev_id(dev):
    return str(dev.get("deviceId") or dev.get("id"))


WANT = None  # set from --device


def pick(devs):
    if not devs:
        raise RuntimeError("no diffuser on the Aroma-Link account")
    if not WANT:
        return dev_id(devs[0])
    w = WANT.lower().replace(":", "")
    for d in devs:
        if w in (dev_id(d), str(d.get("text", "")).lower(), str(d.get("deviceNo", "")).lower()):
            return dev_id(d)
    raise RuntimeError(f"no diffuser matching {WANT!r} on the account")


def mist_seconds(pct):
    """Strength percent -> (seconds misting, seconds resting). Limits: 5-30 s and 90-900 s."""
    pct = max(1, min(100, int(pct)))
    duty = 0.25 * pct / 100
    work = round(90 * duty / (1 - duty))
    if work >= 5:
        return min(30, work), 90
    return 5, max(90, min(900, round(5 * (1 - duty) / duty)))


def load_state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {"intensity": 57, "hours": 0, "until": None}


def save_state(st):
    STATE.write_text(json.dumps(st))


def write_strength(token, uid, did, pct):
    work, pause = mist_seconds(pct)
    off = {"consistenceLevel": 1, "enabled": 0, "endTime": "24:00", "manyPumpEnabled": 0,
           "pauseDuration": 900, "selectPump": "#4#", "startTime": "00:00", "workDuration": 10}
    slot = dict(off, enabled=1, manyPumpEnabled=1, startTime="00:00", endTime="23:59",
                workDuration=work, pauseDuration=pause)
    d = call("/v1/app/data/workSetApp", token=token, body={
        "deviceId": int(did), "userId": int(uid), "week": [1, 2, 3, 4, 5, 6, 7],
        "workTimeList": [slot, off, off, off, off]})
    if not ok(d):
        raise RuntimeError(f"strength refused: code {d.get('code')} {d.get('msg')}")
    return work, pause


def switch(token, uid, did, on):
    d = call("/v1/app/data/newSwitch", {"deviceId": did, "userId": uid, "onOff": "1" if on else "0"}, token)
    if not ok(d):
        raise RuntimeError(f"switch refused: code {d.get('code')} {d.get('msg')}")


def is_on(token, uid, did):
    d = call(f"/v1/app/device/work/{did}?isOpenPage=0&userId={uid}", token=token)
    if not ok(d):
        raise RuntimeError(f"status refused: code {d.get('code')} {d.get('msg')}")
    return str((d.get("data") or {}).get("onOff")) == "1"


def apply(a):
    st = load_state()
    if a.intensity is not None:
        st["intensity"] = max(1, min(100, a.intensity))
    if a.hours is not None:
        st["hours"] = max(0, a.hours)
    token, uid = login()
    did = pick(devices(token, uid))
    if a.power == "on":
        work, pause = write_strength(token, uid, did, st["intensity"])
        switch(token, uid, did, True)
        st["until"] = time.time() + st["hours"] * 3600 if st["hours"] else None
        print(f"diffuser on at {st['intensity']}% ({work} s mist / {pause} s rest), "
              + (f"for {st['hours']:g} h" if st["hours"] else "no time limit"))
    else:
        switch(token, uid, did, False)
        st["until"] = None
        print("diffuser off")
    save_state(st)
    return 0


def state():
    st = load_state()
    token, uid = login()
    did = pick(devices(token, uid))
    on = is_on(token, uid, did)
    if on and st.get("until") and time.time() >= st["until"]:
        switch(token, uid, did, False)
        on = False
    if not on and st.get("until"):
        st["until"] = None
        save_state(st)
    left = round((st["until"] - time.time()) / 60) if on and st.get("until") else None
    print(json.dumps({"on": on, "intensity": st["intensity"], "hours": st["hours"], "minutes_left": left}))
    return 0


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    for f in ("setup", "list", "status", "on", "off", "raw", "raw-status", "apply", "state"):
        g.add_argument("--" + f, action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--power", choices=["on", "off"])
    ap.add_argument("--intensity", type=int)
    ap.add_argument("--hours", type=float)
    ap.add_argument("--device")
    a = ap.parse_args()
    global WANT
    WANT = a.device
    try:
        if a.setup:
            return setup()
        if a.apply and not a.power:
            sys.exit("--apply needs --power on or --power off")
        if a.dry_run and a.apply:
            print(f"DRY-RUN: diffuser -> {a.power}, intensity {a.intensity} -> {mist_seconds(a.intensity or load_state()['intensity'])}, hours {a.hours}")
            return 0
        if a.apply:
            return apply(a)
        if a.state:
            return state()
        if a.dry_run:
            print(f"DRY-RUN: diffuser (Wi-Fi) -> {'on' if a.on else 'off' if a.off else 'read only'}")
            return 0
        token, uid = login()
        devs = devices(token, uid)
        if a.raw:
            print(json.dumps(devs, indent=1)[:3000])
            return 0
        if a.list:
            for d in devs:
                print(f"  {dev_id(d):>8}  {d.get('text')}  {d.get('deviceNo')}  {d.get('netType')}  online={d.get('onlineStatus')}")
            print(f"{len(devs)} diffuser(s) on the account")
            return 0
        did = pick(devs)
        if a.on or a.off:
            d = call("/v1/app/data/newSwitch", {"deviceId": did, "userId": uid, "onOff": "1" if a.on else "0"}, token)
            if not ok(d):
                raise RuntimeError(f"switch refused: code {d.get('code')} {d.get('msg')}")
            print(f"diffuser {'on' if a.on else 'off'} (sent over Wi-Fi)")
            return 0
        d = call(f"/v1/app/device/work/{did}?isOpenPage=0&userId={uid}", token=token)
        if not ok(d):
            raise RuntimeError(f"status refused: code {d.get('code')} {d.get('msg')}")
        inner = d.get("data") or {}
        if a.raw_status:
            print(json.dumps(inner, indent=1)[:2500])
            return 0
        power = inner.get("onOff")
        print("diffuser is " + ("on" if str(power) == "1" else "off" if str(power) == "0" else f"unknown ({json.dumps(inner)[:300]})"))
        return 0
    except Exception as e:
        print(f"FAILED: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
