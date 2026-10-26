// Stream Box: YouTube Cast receiver. The box shows up as a TV in the YouTube app (Cast button, same network), thanks
// to yt-cast-receiver (unofficial YouTube protocol: may break when YouTube changes it).
// A cast video goes through remote.py (POST /api/play: loading screen, history, subtitles), the rest (pause, resume,
// seek, volume) directly through mpv (IPC). End of video: next video of the app's queue.
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
const { PLAYER_STATUSES } = Constants;

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

async function api(name, body = {}) {
  const r = await fetch(API + name, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  return r.ok;
}

// --- Player: the video being cast (id), to recognize what mpv is playing
class BoxPlayer extends Player {
  current = null;

  async doPlay(video, position) {
    this.current = video.id;
    return api('play', { url: `https://www.youtube.com/watch?v=${video.id}`, start: Math.floor(position || 0) });
  }
  async doPause() { return mpvSend(['set_property', 'pause', true]).then(() => true, () => false); }
  async doResume() { return mpvSend(['set_property', 'pause', false]).then(() => true, () => false); }
  async doStop() {
    // "Stop casting" in the app: back to the stream, if the cast video is still on screen
    const was = this.current;
    this.current = null;
    if (was && String(await mpvGet('path') || '').includes(was)) await api('twitch').catch(() => {});
    return true;
  }
  async doSeek(position) { return mpvSend(['seek', position, 'absolute']).then(() => true, () => false); }
  async doSetVolume(volume) {
    try {
      await mpvSend(['set_property', 'volume', volume.level]);
      await mpvSend(['set_property', 'mute', volume.muted]);
      return true;
    } catch { return false; }
  }
  async doGetVolume() { return { level: Math.round(await mpvGet('volume') ?? 100), muted: !!(await mpvGet('mute')) }; }
  async doGetPosition() { return (await mpvGet('time-pos')) || 0; }
  async doGetDuration() { return (await mpvGet('duration')) || 0; }
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
  device: { name: 'Stream Box', screenName: 'Stream Box', brand: 'Stream Box', model: 'Stream Box' },
  dataStore: new FileStore(),
  logLevel: Constants.LOG_LEVELS.WARN,
});

// State changed outside the app (remote, TV menu): the app is notified
listeners.push(async (m) => {
  if (!player.current) return;
  const playing = player.status === PLAYER_STATUSES.PLAYING, paused = player.status === PLAYER_STATUSES.PAUSED;
  if (m.event === 'property-change' && m.name === 'pause' && (playing || paused) && m.data !== paused) {
    await player.notifyExternalStateChange(m.data ? PLAYER_STATUSES.PAUSED : PLAYER_STATUSES.PLAYING);
  } else if (m.event === 'property-change' && m.name === 'path' && m.data && !String(m.data).includes(player.current)) {
    player.current = null;   // something else started on the TV (stream, other video): casting stops there
    await player.notifyExternalStateChange(PLAYER_STATUSES.STOPPED);
  } else if (m.event === 'end-file' && m.reason === 'eof' && playing) {
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
console.log('cast.js: YouTube Cast receiver ready ("Stream Box" in the Cast button of the YouTube app)');
