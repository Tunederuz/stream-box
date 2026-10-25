// Stream Box : récepteur YouTube Cast. La box apparaît comme une TV dans l'appli YouTube (bouton Caster, même réseau),
// grâce à yt-cast-receiver (protocole non officiel de YouTube : peut casser quand YouTube le change).
// Une vidéo castée passe par remote.py (POST /api/play : écran de chargement, historique, sous-titres), le reste
// (pause, reprise, avance, volume) directement par mpv (IPC). Fin de vidéo : vidéo suivante de la file de l'appli.
// Lancé par start.sh si les modules sont installés (npm install dans ce dossier).
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import YouTubeCastReceiver, { Player, DataStore, Constants } from 'yt-cast-receiver';

const API = 'http://127.0.0.1:8080/api/';
const MPV_SOCKET = '/tmp/stream-box-mpv.sock';
const STORE = path.join(os.homedir(), '.config/stream-box/cast-receiver.json');
const { PLAYER_STATUSES } = Constants;

// --- mpv : requêtes (request_id) et évènements sur une connexion IPC, rouverte si le lecteur redémarre
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
    if (!sock || sock.connecting) return reject(new Error('mpv injoignable'));
    const id = nextId++;
    const timer = setTimeout(() => { waiting.delete(id); reject(new Error('mpv ne répond pas')); }, 3000);
    waiting.set(id, (m) => { clearTimeout(timer); m.error === 'success' ? resolve(m.data) : reject(new Error(m.error)); });
    sock.write(JSON.stringify({ command, request_id: id }) + '\n');
  });
}
const mpvGet = (prop) => mpvSend(['get_property', prop]).catch(() => null);

async function api(name, body = {}) {
  const r = await fetch(API + name, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  return r.ok;
}

// --- Lecteur : la vidéo castée en cours (identifiant), pour reconnaître ce que mpv lit
class BoxPlayer extends Player {
  current = null;

  async doPlay(video, position) {
    this.current = video.id;
    return api('play', { url: `https://www.youtube.com/watch?v=${video.id}`, start: Math.floor(position || 0) });
  }
  async doPause() { return mpvSend(['set_property', 'pause', true]).then(() => true, () => false); }
  async doResume() { return mpvSend(['set_property', 'pause', false]).then(() => true, () => false); }
  async doStop() {
    // « Arrêter la diffusion » dans l'appli : retour au stream, si la vidéo castée est encore à l'écran
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

// --- Appairages gardés d'un démarrage à l'autre (l'appli retrouve la box sans tout refaire)
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

// État changé hors de l'appli (télécommande, menu de la TV) : l'appli est prévenue
listeners.push(async (m) => {
  if (!player.current) return;
  const playing = player.status === PLAYER_STATUSES.PLAYING, paused = player.status === PLAYER_STATUSES.PAUSED;
  if (m.event === 'property-change' && m.name === 'pause' && (playing || paused) && m.data !== paused) {
    await player.notifyExternalStateChange(m.data ? PLAYER_STATUSES.PAUSED : PLAYER_STATUSES.PLAYING);
  } else if (m.event === 'property-change' && m.name === 'path' && m.data && !String(m.data).includes(player.current)) {
    player.current = null;   // autre chose lancé sur la TV (stream, autre vidéo) : la diffusion s'arrête là
    await player.notifyExternalStateChange(PLAYER_STATUSES.STOPPED);
  } else if (m.event === 'end-file' && m.reason === 'eof' && playing) {
    await player.pause();
    await player.next();   // file de l'appli, ou lecture automatique
  }
});

receiver.on('senderConnect', (sender) => {
  console.log(`cast.js : ${sender.name} connecté`);
  mpvSend(['show-text', `${sender.user?.name || sender.name} diffuse YouTube sur la box`, 4000]).catch(() => {});
});
receiver.on('senderDisconnect', (sender) => console.log(`cast.js : ${sender.name} déconnecté`));
receiver.on('error', (error) => console.error('cast.js :', error));

mpvConnect();
await receiver.start();
console.log('cast.js : récepteur YouTube Cast prêt (« Stream Box » dans le bouton Caster de l\'appli YouTube)');
