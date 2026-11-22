// Homebridge add-on for Aroma-Link family diffusers (AromaTech Ambience and relatives).
// One device in Apple Home with two sliders, both fan-style because a fan has an on/off and a slider
// (or two separate tiles: two accessory entries in config.json with "role": "main" and "role": "hours"):
//   "Intensity"  on/off, slider snaps to 5 levels: 20/40/60/80/100% = level 1-5
//   "Hours"      slider = how long a run lasts, 5 stops: 20% = 1 hour ... 100% = 5 hours; off / 0% = no limit
// Turning Diffuser on starts a run at the chosen strength for the chosen hours.
// It holds no sign-in itself: it runs aromalink.py (Wi-Fi, maker's service) from the folder given
// as "toolDir" in the config, and falls back to diffuser.py (Bluetooth) for plain on/off if that fails.
const { execFile } = require('child_process');
const path = require('path');

module.exports = (api) => api.registerAccessory('AromaTechDiffuser', Tile);

// One shared controller; each Apple Home tile is a separate accessory so it gets its own name.
let shared = null;

class Tile {
  constructor(log, config, api) {
    if (!shared) shared = new Diffuser(log, config);
    const { Service, Characteristic } = api.hap;
    const d = shared;
    d.C = Characteristic;
    this.info = new Service.AccessoryInformation()
      .setCharacteristic(Characteristic.Manufacturer, 'AromaTech')
      .setCharacteristic(Characteristic.Model, config.model || 'Aroma-Link diffuser');
    const role = config.role || 'both';
    this.services = [this.info];
    // ConfiguredName is the label Apple Home shows beside each slider inside one device.
    const fan = (label, subtype) => {
      const f = new Service.Fan(label, subtype);
      f.setCharacteristic(Characteristic.Name, label);
      f.addOptionalCharacteristic(Characteristic.ConfiguredName);
      f.setCharacteristic(Characteristic.ConfiguredName, label);
      this.services.push(f);
      return f;
    };
    if (role !== 'hours') {
      d.main = fan(role === 'both' ? 'Intensity (5 levels)' : config.name, 'main');
      d.main.setPrimaryService(true);
      d.main.getCharacteristic(Characteristic.On)
        .onGet(() => d.on).onSet((v) => { d.on = !!v; d.queue(); });
      d.main.getCharacteristic(Characteristic.RotationSpeed)
        .setProps({ minValue: 0, maxValue: 100, minStep: 20 })
        .onGet(() => d.intensity)
        .onSet((v) => { if (v > 0) { d.intensity = Math.max(20, Math.round(v / 20) * 20); } d.queue(); });
    }
    if (role !== 'main') {
      d.timer = fan(role === 'both' ? 'Hours (20% = 1 hour)' : config.name, 'hours');
      d.timer.getCharacteristic(Characteristic.On)
        .onGet(() => d.hours > 0)
        .onSet((v) => { if (!v) { d.hours = 0; } else if (!d.hours) { d.hours = 2; } d.queue(); });
      d.timer.getCharacteristic(Characteristic.RotationSpeed)
        .setProps({ minValue: 0, maxValue: 100, minStep: 20 })
        .onGet(() => Math.min(100, d.hours * 20))
        .onSet((v) => { d.hours = Math.round(v / 20); d.queue(); });
    }
  }

  getServices() { return this.services; }
}

class Diffuser {
  constructor(log, config) {
    this.log = log;
    if (!config.toolDir) log.error('set "toolDir" to the folder holding aromalink.py');
    this.dir = config.toolDir || '.';
    this.python = config.python || '/usr/bin/python3';
    this.blePython = config.blePython || this.python;
    this.pollSeconds = config.pollSeconds || 60;
    this.on = false; this.intensity = 57; this.hours = 0;
    setTimeout(() => this.poll(), 3000);
    setInterval(() => this.poll(), this.pollSeconds * 1000);
  }

  run(cmd, args, timeoutMs) {
    return new Promise((resolve) => {
      execFile(cmd, args, { timeout: timeoutMs }, (err, stdout) => {
        resolve({ ok: !err, out: String(stdout || '').trim() });
      });
    });
  }

  tool(args) { return this.run(this.python, [path.join(this.dir, 'aromalink.py'), ...args], 45000); }

  // Apple Home sends on/off and the slider as separate messages; wait for them to settle, then act once.
  queue() {
    this.busyUntil = Date.now() + 40000;
    clearTimeout(this.pending);
    this.pending = setTimeout(() => this.apply(), 1500);
  }

  async apply() {
    const want = this.on;
    const args = ['--apply', '--power', want ? 'on' : 'off',
      '--intensity', String(this.intensity), '--hours', String(this.hours)];
    let r = await this.tool(args);
    if (!r.ok) {
      this.log.warn(`Wi-Fi route failed (${r.out}); trying Bluetooth for plain ${want ? 'on' : 'off'}`);
      r = await this.run(this.blePython,
        [path.join(this.dir, 'diffuser.py'), want ? '--on' : '--off', '--minutes', '1.5'], 110000);
    }
    if (r.ok) { this.log.info(r.out); } else { this.log.error(`could not set the diffuser: ${r.out}`); }
    this.busyUntil = Date.now() + 15000;
    this.push();
  }

  push() {
    if (this.main) {
      this.main.updateCharacteristic(this.C.On, this.on);
      this.main.updateCharacteristic(this.C.RotationSpeed, this.intensity);
    }
    if (this.timer) {
      this.timer.updateCharacteristic(this.C.On, this.hours > 0);
      this.timer.updateCharacteristic(this.C.RotationSpeed, Math.min(100, this.hours * 20));
    }
  }

  // Also the timer: aromalink.py --state switches the diffuser off when a timed run is over.
  async poll() {
    if (Date.now() < (this.busyUntil || 0)) return;
    const r = await this.tool(['--state']);
    if (!r.ok) { this.log.debug(`state check failed: ${r.out}`); return; }
    if (Date.now() < (this.busyUntil || 0)) return;
    try {
      const s = JSON.parse(r.out);
      if (s.on !== this.on) this.log.info(`diffuser is now ${s.on ? 'on' : 'off'}`);
      this.on = s.on; this.intensity = Math.max(20, Math.round(s.intensity / 20) * 20); this.hours = Math.min(5, Math.round(s.hours));
      this.push();
    } catch (e) { this.log.debug(`bad state reply: ${r.out}`); }
  }

}
