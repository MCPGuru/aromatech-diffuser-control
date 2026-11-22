# What we know about these diffusers

Observed on one AromaTech Ambience (model string `SL150_DZ`, firmware `V2.0.20251012`) in
November 2026. Items marked *unknown* are just that.

## Hardware

- AromaTech Ambience label: FCC ID `2BCCL-STARLIGHT`, IC `31073-AMBIENCE`, 12 V 1 A.
- FCC grantee: GuangDong Crearoma Scent Tech Limited (granted 17 Aug 2023). Two transmitters:
  2402-2480 MHz at 0.0007 W (Bluetooth LE) and 2412-2462 MHz at 0.06 W (Wi-Fi 802.11 b/g/n,
  20 and 40 MHz channels). Test report 1 is the Wi-Fi report.
- The filing declares about twenty models identical in circuitry (see README).
- The radio module's hardware address has a Quectel prefix (`C4:A6:4E`). The board photo in
  the filing shows a shielded module with a printed antenna, a small push button and a
  4-pin serial header (3.3V, GND, RX, TX).
- The user manual in the filing is AromaTech's and never mentions Wi-Fi. AromaTech's app
  does not expose it; the factory's Aroma-Link app does.
- Once on Wi-Fi the diffuser answers ping and has no open TCP port (1-10000 scanned). It
  keeps an outbound connection to the maker's service.

## Bluetooth LE

Broadcast name `Smart.A7.WIFI` (family pattern `<name>.A<n>.WIFI`), manufacturer id 17750
(0x4556) with data `52 15 53 6d 61 72 74` ("R." + "Smart"). No pairing, no encryption. The
"password" the phone apps ask for (default `1234`) appears to be checked by the app.

Service `FFF0`:

| Characteristic | Properties | Use |
|---|---|---|
| `FFF2` | write | send commands (write with response) |
| `FFF1` | read, notify | replies (subscribe first) |
| `FFF3` | indicate | not needed |
| `FFF4` | write without response | not needed |

Frame: `A5 AA AC` + check byte + payload + `C5 CC CA`. The check byte is all payload bytes
XORed together. Long replies span several notifications; reassemble by the header and
trailer. Payload byte 0 is `52` query, `53` unsolicited report, `57` write. A refused query
answers `52 <code> "NACK"`; an accepted write answers `57 <code> "ACK"`.

### Writes (57)

| Payload | Meaning | Tried here |
|---|---|---|
| `57 08 01` / `57 08 00` | power on / off | yes |
| `57 03 10` / `57 03 00` | fan on / off | no |
| `57 17 YYYY MM DD hh mm ss wd` | set clock (year 2 bytes big-endian, weekday 1 = Monday) | no |
| `57 16 mask + 5 x slot` | write schedule for the weekdays in `mask` (bit 0 = Monday) | no (done via the service instead) |

A slot is 9 bytes: start hour, start minute, end hour, end minute, flag (`11` on, `10`
off), mist seconds (2 bytes big-endian), rest seconds (2 bytes big-endian).

After a power write the diffuser also sends `53 08 <state>` and often `53 09 ...`.

### Queries (52): every code 00-FF was tried; these 13 answer

| Query | Reply after `52 <code>` | Meaning |
|---|---|---|
| `01` | `"1234" + name` | app password + broadcast name |
| `02` | year(2) month day hour minute second weekday | clock |
| `03` | `10` / `00` | fan on / off |
| `04` | `00 00` | *unknown* |
| `07` | `01` | *unknown* |
| `08` | `01` / `00` | power |
| `09` | phase, mist(2), rest(2), start h, m, end h, m, enabled | current window; phase 1 = misting, 2 = resting. The two durations look like time remaining in the current phase, not the settings |
| `0A` | clock(8) + fan + power + the `09` fields | everything at once |
| `0C` | 6 bytes | hardware address (same as the Wi-Fi address) |
| `0D` | model (20 bytes, zero padded), firmware (21 bytes), `02`, serial (15 ASCII digits) | identity |
| `12` | `01` | *unknown* |
| `15` | 7 days x 5 slots x 9 bytes | whole weekly schedule, Monday first |
| `1F` | twenty ASCII `0` | *unknown* (twenty digits is the length of a SIM card number; the family has cellular models) |

`52 06 <weekday>` (one day's schedule) and `52 1E` (oil level) are documented for other
models; oil is refused on this one.

## The internet service (after Wi-Fi setup)

Base `https://www.aroma-link.com`. Its certificate was valid when we tested; other projects
report it has lapsed at times. Replies are JSON with `code` 200 on success.

| Step | Call |
|---|---|
| Sign in | `POST /v2/app/token`, form fields `userName`, `password` (MD5 hex of the password). Reply `data.accessToken`, `data.id` (user id) |
| Later calls | headers `access_token: <token>` and `Authorization: <token>` |
| Devices | `GET /v1/app/device/listAll/<userId>`: a tree of groups; devices have `"type": "device"`, `id`, `text` (name), `deviceNo` (hardware address), `netType`, `onlineStatus` |
| Status | `GET /v1/app/device/work/<deviceId>?isOpenPage=0&userId=<userId>` |
| Power | `POST /v1/app/data/newSwitch`, form `deviceId`, `userId`, `onOff` (1/0) |
| Schedule | `POST /v1/app/data/workSetApp`, JSON `{deviceId, userId, week: [1..7], workTimeList: [5 slots]}` |

A schedule slot: `{"enabled": 1, "startTime": "00:00", "endTime": "23:59", "workDuration":
15, "pauseDuration": 90, "consistenceLevel": 1, "manyPumpEnabled": 1, "selectPump": "#4#"}`.
Writing it this way was read back correctly over Bluetooth (`52 15`).

Useful status fields: `onOff` is power (1/0). `workStatus` is only the phase (1 misting,
2 resting), not power. `workRemainTime` / `pauseRemainTime` count down. `startTime` /
`endTime` are the active window. `typeCode` is the model. `workStartTime`, `workEndTime`,
`pauseStartTime`, `pauseEndTime` are the allowed ranges (5-30 s and 90-900 s on this model).
`hasFan`, `hasLamp`, `hasPump`, `hasBattery`, `hasWeight` describe the hardware.

`GET /v1/app/device/newWorkTime/<deviceId>?userId=&week=N` returned no schedule for a
device whose schedule had been set over Bluetooth.

## Getting Wi-Fi switched on

The Aroma-Link app, Bluetooth password `1234`, then its network setup. We did not capture
what the app sends to do this. A manual for a sister product describes a different route (a
temporary `Aromalink...` hotspot with password `12345678`); our unit did not show such a
hotspot before setup.
