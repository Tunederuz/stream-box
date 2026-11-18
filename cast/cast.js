// Inlet: YouTube Cast receiver. The box shows up as a TV in the YouTube app (Cast button, same network), thanks
// to yt-cast-receiver (unofficial YouTube protocol: may break when YouTube changes it).
// A cast video goes through remote.py (POST /api/play: loading screen, history, subtitles), the rest (pause, resume,
// seek, volume) directly through mpv (IPC). End of video: next video of the app's queue. "Stop casting": the video
// left, back to the menu. A YouTube video started on the box (TV menu, history) is taken as the one playing: a phone
// that connects sees it and drives it.
// Started by start.sh if the modules are installed (npm install in this directory). Same process: YouTube account
// progress through the "TV app" access (youtube_tv.js).
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import YouTubeCastReceiver, { Player, DataStore, Constants } from 'yt-cast-receiver';
import { startYoutubeTv } from './youtube_tv.js';

const API = 'http://127.0.0.1:8080/api/';
const MPV_SOCKET = '/tmp/stream-box-mpv.sock';
const STORE = path.join(os.homedir(), '.config/stream-box/cast-receiver.json');
const { PLAYER_STATUSES, CLIENTS, RESET_PLAYER_ON_DISCONNECT_POLICIES } = Constants;
const youtubeId = (url) => (String(url || '').match(/youtube\.com\/watch\?(?:.*&)?v=([\w-]{11})|youtu\.be\/([\w-]{11})/) || []).slice(1).find(Boolean);

// Text shown on the TV in the interface language (same files as i18n.py: ~/.config/stream-box/language,
// ../locales/<lang>.json, English text as the key)
function tr(text, values = {}) {
  let out = text;
  try {
    const lang = fs.readFileSync(path.join(os.homedir(), '.config/stream-box/language'), 'utf8').trim();
    if (/^[a-z]{2}$/.test(lang) && lang !== 'en') {
      const file = path.join(path.dirname(new URL(import.meta.url).pathname), '..', 'locales', `${lang}.json`);
      out = JSON.parse(fs.readFileSync(file, 'utf8'))[text] || text;
    }
  } catch {}
  for (const [k, v] of Object.entries(values)) out = out.replaceAll(`{${k}}`, String(v));
  return out;
}

// --- mpv: requests (request_id) and events on an IPC connection, reopened if the player restarts
let sock = null, nextId = 1, buf = '';
const waiting = new Map(), listeners = [];
function mpvConnect() {
  sock = net.createConnection(MPV_SOCKET);
  sock.on('connect', () => {
    buf = '';
    for (const [i, prop] of ['pause', 'path'].entries()) mpvSend(['observe_property', i + 1, prop]).catch(() => {});
  });
  sock.on('data', (data) => {
    const lines = (buf + data).split('\n');
    buf = lines.pop();
    for (const line of lines) {
      let m;
      try { m = JSON.parse(line); } catch { continue; }
      if (m.request_id && waiting.has(m.request_id)) {
        waiting.get(m.request_id)(m);
        waiting.delete(m.request_id);
      } else if (m.event) listeners.forEach((fn) => fn(m));
    }
  });
  sock.on('error', () => {});
  sock.on('close', () => { sock = null; setTimeout(mpvConnect, 2000); });
}
function mpvSend(command) {
  return new Promise((resolve, reject) => {
    if (!sock || sock.connecting) return reject(new Error('mpv unreachable'));
    const id = nextId++;
    const timer = setTimeout(() => { waiting.delete(id); reject(new Error('mpv not responding')); }, 3000);
    waiting.set(id, (m) => { clearTimeout(timer); m.error === 'success' ? resolve(m.data) : reject(new Error(m.error)); });
    sock.write(JSON.stringify({ command, request_id: id }) + '\n');
  });
}
const mpvGet = (prop) => mpvSend(['get_property', prop]).catch(() => null);

// What mpv plays (observed): the cast video is recognized by its id in it
let mpvPath = '';
listeners.push((m) => { if (m.event === 'property-change' && m.name === 'path') mpvPath = String(m.data || ''); });

// Resolves once mpv shows the picture of the video `id` (playback-restart: its first frame, or after a seek): true;
// false when it fails (an error not followed by another try within 5 s: stream-box.lua may reload it with another
// YouTube client) or when something else is played; true after `ms` all the same (slow, the app is not left loading)
function shown(id, ms) {
  return new Promise((resolve) => {
    let failing = null;
    const finish = (ok) => {
      clearTimeout(timer);
      clearTimeout(failing);
      const i = listeners.indexOf(watch);
      if (i >= 0) listeners.splice(i, 1);
      resolve(ok);
    };
    const watch = (m) => {
      const ours = mpvPath.includes(id);
      if (m.event === 'playback-restart' && ours) finish(true);
      else if (m.event === 'start-file') { clearTimeout(failing); failing = null; }
      else if (m.event === 'end-file' && m.reason === 'error' && ours) failing = setTimeout(() => finish(false), 5000);
      else if (m.event === 'property-change' && m.name === 'path' && m.data && !ours) finish(false);
    };
    const timer = setTimeout(() => finish(true), ms);
    listeners.push(watch);
  });
}

async function api(name, body = {}) {
  const r = await fetch(API + name, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  return r.ok;
}

// --- Player: the video being cast (id), to recognize what mpv is playing. The app shows "loading" until doPlay /
// doSeek resolve, then counts the time itself: they resolve once the picture is there (the box loads a video in a few
// seconds; resolved at once, the app's time ran ahead of the TV's), its position meanwhile the one asked for
class BoxPlayer extends Player {
  current = null;
  loadingAt = null;
  leaving = null;
  // Its last position and duration while mpv plays it (read every second): what the app is told once the video is
  // left on the box (Back, another video), mpv then on something else: read there, 0 of 0 or a live stream's
  // position, the app took it as watched to the end
  last = { position: 0, duration: 0 };
  tracking = setInterval(() => this.track(), 1000);

  ours() { return !!this.current && mpvPath.includes(this.current); }
  async track() {
    if (!this.ours() || this.loadingAt !== null) return;
    const [position, duration] = [await mpvGet('time-pos'), await mpvGet('duration')];
    if (this.ours() && position !== null) this.last = { position, duration: duration || this.last.duration };
  }

  async doPlay(video, position) {
    clearTimeout(this.leaving);   // (the app stops the previous video before playing the next one)
    this.current = video.id;
    this.loadingAt = Math.floor(position || 0);
    this.last = { position: this.loadingAt, duration: 0 };
    const done = shown(video.id, 45000);
    try {
      if (!await api('play', { url: `https://www.youtube.com/watch?v=${video.id}`, start: this.loadingAt })) return false;
      return await done;
    } catch {
      return false;
    } finally {
      this.loadingAt = null;
    }
  }
  async doPause() { return mpvSend(['set_property', 'pause', true]).then(() => true, () => false); }
  async doResume() { return mpvSend(['set_property', 'pause', false]).then(() => true, () => false); }
  async doStop() {
    // "Stop casting" in the app: the video left (back to the menu, the box's main page), if it is still on screen;
    // a moment later: the app also stops a video right before playing the next one
    const was = this.current;
    this.current = null;
    clearTimeout(this.leaving);
    this.leaving = setTimeout(async () => {
      if (was && !this.current && mpvPath.includes(was)) await api('home').catch(() => {});
    }, 1500);
    return true;
  }
  // A YouTube video started on the box itself: taken as the one playing, for a phone that connects (or is connected)
  async adopt(id) {
    this.current = id;
    this.last = { position: (await mpvGet('time-pos')) || 0, duration: (await mpvGet('duration')) || 0 };
    try {
      this.queue.setAsCurrent({ id, client: CLIENTS.YT });
      await this.notifyExternalStateChange(await mpvGet('pause') ? PLAYER_STATUSES.PAUSED : PLAYER_STATUSES.PLAYING);
    } catch (e) { console.error('cast.js: adopting', id, e); }
  }
  async doSeek(position) {
    const done = this.current ? shown(this.current, 15000) : Promise.resolve(true);
    try { await mpvSend(['seek', position, 'absolute']); } catch { return false; }
    return done;
  }
  async doSetVolume(volume) {
    try {
      await mpvSend(['set_property', 'volume', volume.level]);
      await mpvSend(['set_property', 'mute', volume.muted]);
      return true;
    } catch { return false; }
  }
  async doGetVolume() { return { level: Math.round(await mpvGet('volume') ?? 100), muted: !!(await mpvGet('mute')) }; }
  // Loading: the position asked for (mpv may still be on the previous video); left: where it was
  async doGetPosition() {
    if (this.loadingAt !== null) return this.loadingAt;
    if (!this.ours()) return this.last.position;
    return (await mpvGet('time-pos')) ?? this.last.position;
  }
  async doGetDuration() {
    if (this.loadingAt !== null) return 0;
    if (!this.ours()) return this.last.duration;
    return (await mpvGet('duration')) || this.last.duration;
  }
}

// --- Pairings kept from one boot to the next (the app finds the box again without redoing everything)
class FileStore extends DataStore {
  read() { try { return JSON.parse(fs.readFileSync(STORE, 'utf8')); } catch { return {}; } }
  async set(key, value) {
    const all = this.read();
    all[key] = value;
    fs.mkdirSync(path.dirname(STORE), { recursive: true, mode: 0o700 });
    fs.writeFileSync(STORE, JSON.stringify(all), { mode: 0o600 });
  }
  async get(key) { return this.read()[key] ?? null; }
}

const player = new BoxPlayer();
const receiver = new YouTubeCastReceiver(player, {
  device: { name: 'Inlet', screenName: 'Inlet', brand: 'Inlet', model: 'Inlet' },
  dataStore: new FileStore(),
  logLevel: Constants.LOG_LEVELS.WARN,
  // The phone asleep or the app closed (implicit) leaves the video playing; "Stop casting" stops it
  app: { resetPlayerOnDisconnectPolicy: RESET_PLAYER_ON_DISCONNECT_POLICIES.ALL_EXPLICITLY_DISCONNECTED },
});

// State changed outside the app (remote, TV menu): the app is notified
listeners.push(async (m) => {
  // A YouTube video of the box's own: adopted at its first frame (the app's clock starts with the picture)
  if (m.event === 'playback-restart') {
    const id = youtubeId(mpvPath);
    if (id && id !== player.current && player.status !== PLAYER_STATUSES.LOADING) return player.adopt(id);
  }
  if (!player.current) return;
  const playing = player.status === PLAYER_STATUSES.PLAYING, paused = player.status === PLAYER_STATUSES.PAUSED;
  if (m.event === 'property-change' && m.name === 'pause' && (playing || paused) && m.data !== paused) {
    await player.notifyExternalStateChange(m.data ? PLAYER_STATUSES.PAUSED : PLAYER_STATUSES.PLAYING);
  } else if (m.event === 'property-change' && m.name === 'path' && m.data && !String(m.data).includes(player.current)) {
    player.current = null;   // something else started on the TV (stream, other video): casting stops there
    await player.notifyExternalStateChange(PLAYER_STATUSES.STOPPED);
  } else if (m.event === 'end-file' && m.reason === 'stop' && (playing || paused)) {
    // left on the box (Back, the menu, another file): the app keeps where it was
    player.current = null;
    await player.notifyExternalStateChange(PLAYER_STATUSES.STOPPED);
  } else if (m.event === 'end-file' && m.reason === 'eof' && playing) {
    if (!receiver.getConnectedSenders().length) {   // (a video of the box's own, no phone: nothing comes next here)
      player.current = null;
      return player.notifyExternalStateChange(PLAYER_STATUSES.STOPPED);
    }
    await player.pause();
    await player.next();   // app queue, or autoplay
  }
});

receiver.on('senderConnect', (sender) => {
  console.log(`cast.js: ${sender.name} connected`);
  mpvSend(['show-text', tr('{name} is casting YouTube to the box', { name: sender.user?.name || sender.name }), 4000]).catch(() => {});
});
receiver.on('senderDisconnect', (sender) => console.log(`cast.js: ${sender.name} disconnected`));
receiver.on('error', (error) => console.error('cast.js:', error));

mpvConnect();
startYoutubeTv();
await receiver.start();
console.log('cast.js: YouTube Cast receiver ready ("Inlet" in the Cast button of the YouTube app)');
