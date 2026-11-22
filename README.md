# aromatech-diffuser-control

Control an **AromaTech Ambience** scent diffuser (and its many relatives) from your own
computer: on/off, mist strength and timed runs, from the command line, from cron, or as a
tile in **Apple Home** through Homebridge.

AromaTech's own app is Bluetooth-only and has no automation. It turns out the diffuser can
do much more:

- It has a **Wi-Fi radio** that AromaTech's app never uses.
- It is a rebadged factory model that speaks the factory's **Aroma-Link** protocol.
- The factory's own "Aroma-Link" phone app can put it on Wi-Fi in a couple of minutes.

Not affiliated with AromaTech, Crearoma or Aroma-Link. Everything here was worked out by
observation and can stop working if the maker changes its service. Use at your own risk.

## What's in the box

| File | What it does | Needs |
|---|---|---|
| `aromalink.py` | Wi-Fi control through the maker's internet service: on, off, status, strength, timed runs | Python 3.8+, nothing else |
| `diffuser.py` | Direct Bluetooth control: on, off, status. No internet, no account | `pip install bleak` |
| `homebridge/` | Apple Home tile: on/off, a 5-level intensity slider, a 1-5 hour run timer | Homebridge |
| `tools/probe.py` | Asks a diffuser every read-only question, for documenting a new model | `bleak` |
| `tools/decoy.py` | Pretends to be a diffuser so you can record what a phone app sends | `pip install bless` |
| `PROTOCOL.md` | Everything learned: Bluetooth commands, the internet service, the hardware | |

## Which diffusers?

Tested on one unit: an AromaTech Ambience, FCC ID `2BCCL-STARLIGHT`, which reports itself
as model `SL150_DZ` and broadcasts over Bluetooth as `Smart.A7.WIFI`.

The FCC filing for that ID is by the factory, GuangDong Crearoma Scent Tech, and declares
these models identical in circuitry: Starlight, Polaris, OY-5, G-air, ND130, OY-2, ND300,
OY-8, ND500, OS-3, PRO300, U3, U5, OS-5, Airing6L, U10, OV10, R3, OV-1. Anything that works
with the Aroma-Link phone app should work with `aromalink.py`. Reports welcome.

## Step 1: put the diffuser on Wi-Fi (once)

1. Install the **Aroma-Link** app (the factory's app, not AromaTech's) and create an account.
2. Fully close the AromaTech app first. The diffuser talks to one Bluetooth device at a time.
3. In Aroma-Link, add the device. When asked for the Bluetooth password, enter **1234**.
4. Use the app's network setup to join your home Wi-Fi. It needs a **2.4 GHz** network and
   may take more than one try.
5. The diffuser now shows as online in the app, and appears on your router (ours showed up
   with the name `wlan0`).

You can skip this step and use Bluetooth only (`diffuser.py`), if the computer is within a
few metres of the diffuser.

## Step 2: command line

```sh
python3 aromalink.py --setup        # asks for your Aroma-Link email and password, once
python3 aromalink.py --list
python3 aromalink.py --status
python3 aromalink.py --off
python3 aromalink.py --on
```

The sign-in is kept in `aromalink-creds.json` beside the script, readable only by you (the
password is stored as the MD5 hash the service expects, which is as good as the password
for this service, so keep the file private). Or set `AROMALINK_USER` and
`AROMALINK_PASSWORD` in the environment instead.

### Strength and timed runs

```sh
python3 aromalink.py --apply --power on --intensity 60 --hours 3
python3 aromalink.py --state        # run this every minute; it ends the timed run
python3 aromalink.py --apply --power off
```

`--state` is what switches the diffuser off when the hours are up, so something has to call
it regularly: a cron line (`* * * * * python3 /path/aromalink.py --state`) or the Homebridge
add-on below, which does it for you.

**Read this first:** setting a strength replaces the diffuser's stored weekly schedule with
one all-day window. After that it mists whenever it is switched on and no longer starts and
stops by itself. Note your schedule down beforehand if you want it back.

Strength is the share of time spent misting. 100% is 30 seconds of mist per 90 seconds of
rest, 60% is 16 seconds, 20% is 5 seconds; below 20% the rest period stretches to as much
as 15 minutes.

### Bluetooth, no internet

```sh
pip install bleak
python3 diffuser.py --status
python3 diffuser.py --off
python3 diffuser.py --on
```

On macOS, run it from Terminal on the Mac itself (or from a launchd job) so the Bluetooth
permission prompt can appear; over SSH it is refused.

## Step 3: Apple Home (optional)

```sh
cd homebridge && npm install -g .
```

Add to the `accessories` list in `~/.homebridge/config.json`, then restart Homebridge:

```json
{
  "accessory": "AromaTechDiffuser",
  "name": "Scent Diffuser",
  "toolDir": "/full/path/to/aromatech-diffuser-control",
  "python": "/usr/bin/python3"
}
```

Run `aromalink.py --setup` first, as the same user Homebridge runs as. You get one device
with two sliders:

| Slider | Meaning |
|---|---|
| **Intensity (5 levels)** | On/off. Snaps to 20/40/60/80/100% = level 1 to 5 |
| **Hours (20% = 1 hour)** | Length of a run, 1 to 5 hours. Off = no time limit |

Apple Home only shows percentages on sliders, so the scale is in the label. Turning the
diffuser on starts a run at that intensity for that many hours. Changes made in the phone
app show up in Home within a minute. Optional settings: `"role": "main"` or `"hours"` on two
separate entries gives two tiles instead of one; `"blePython"` is the Python that has
`bleak`, used for the Bluetooth fallback; `"pollSeconds"` (default 60).

## Good to know

- **Wi-Fi control depends on the maker's servers and your internet.** There is no local
  network control: the diffuser has no open ports. Bluetooth is the only direct route.
- **One Bluetooth connection at a time.** An open phone app blocks `diffuser.py`.
- **The service's idea of on/off** matched the diffuser within about six seconds in our tests.
- **No oil level, no light control** on this model.
- If you change your Aroma-Link password, run `--setup` again.

## Credits

The Bluetooth command format and the service calls were first published by
[mr-sparks/scent-assistant](https://github.com/mr-sparks/scent-assistant) (Home Assistant);
[dalyem/ha_aromalink](https://github.com/dalyem/ha_aromalink) documents the service too.
This project adds the AromaTech/Wi-Fi findings, a full read-only survey of one model,
stand-alone tools and a Homebridge add-on. MIT licence.
