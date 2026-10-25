// Stream Box : progression YouTube du compte, par l'accès « appli YouTube TV » (youtubei.js, non officiel ; l'API
// officielle ne donne ni historique ni positions). Connexion par code sur google.com/device, jeton dans
// ~/.config/stream-box/youtube-tv-token.json (600). Petit serveur local pour remote.py (127.0.0.1:8091) :
//   GET  /status    connecté ?, code en attente
//   POST /login     demande un code ;  POST /logout  oublie le jeton
//   GET  /progress  { id: pourcentage vu } d'après l'historique et le fil des abonnements (gardé 10 min ; YouTube
//                   ne met ce pourcentage à jour qu'avec beaucoup de retard : indicatif seulement)
//   POST /report    { id, position, final } : position renvoyée à YouTube (le téléphone reprend là où la TV s'arrête),
//                   comme le fait un lecteur : début de session (/player, cpn), puis segments regardés en temps réel
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import { Innertube, Log, ClientType, Constants } from 'youtubei.js';

const TOKEN = os.homedir() + '/.config/stream-box/youtube-tv-token.json';
const PORT = 8091;
const PROGRESS_CACHE = 600e3;
const SESSION_IDLE = 120e3;   // plus de signalement depuis 2 min : nouvelle session de lecture
const CLIENT = { client_name: Constants.CLIENTS.TV.NAME, client_version: Constants.CLIENTS.TV.VERSION };
Log.setLevel(Log.Level.NONE);

let yt = null, connected = false, pending = null, error = null;
let progress = { at: 0, data: {} };
const sessions = new Map();

const saveToken = ({ credentials }) => {
  fs.mkdirSync(os.homedir() + '/.config/stream-box', { recursive: true, mode: 0o700 });
  fs.writeFileSync(TOKEN, JSON.stringify(credentials), { mode: 0o600 });
};
const readToken = () => { try { return JSON.parse(fs.readFileSync(TOKEN, 'utf8')); } catch { return null; } };

async function client() {
  if (yt) return yt;
  yt = await Innertube.create({ retrieve_player: false, client_type: ClientType.TV });
  yt.session.on('auth-pending', (d) => { pending = { user_code: d.user_code, verification_uri: d.verification_url }; });
  yt.session.on('auth', (d) => { saveToken(d); connected = true; pending = null; error = null; progress.at = 0; });
  yt.session.on('update-credentials', saveToken);
  yt.session.on('auth-error', (e) => { error = e.message; pending = null; });
  return yt;
}

async function resume() {
  // Jeton déjà là (démarrage) : reconnexion sans code
  const creds = readToken();
  if (!creds) return;
  try {
    await (await client()).session.signIn(creds);
    connected = true;
  } catch (e) {
    error = e.message;
  }
}

// Vidéos d'une réponse brute avec leur pourcentage vu (cartes du client TV : percentDurationWatched dans les
// recouvrements de la miniature)
function scan(node, out, cur = null) {
  if (Array.isArray(node)) { for (const n of node) scan(n, out, cur); return; }
  if (!node || typeof node !== 'object') return;
  const id = node.videoId || node.contentId;   // cartes du client TV : contentId
  if (typeof id === 'string' && /^[\w-]{11}$/.test(id)) cur = id;
  if (cur && typeof node.percentDurationWatched === 'number' && !(cur in out)) out[cur] = node.percentDurationWatched;
  for (const v of Object.values(node)) scan(v, out, cur);
}

async function getProgress() {
  if (!connected) return {};
  if (Date.now() - progress.at < PROGRESS_CACHE) return progress.data;
  const data = {};
  for (const browseId of ['FEhistory', 'FEsubscriptions']) {
    try { scan((await yt.actions.execute('/browse', { browseId, client: 'TV' })).data, data); }
    catch (e) { console.error(`youtube_tv.js : ${browseId} :`, e.message); return progress.data; }   // réessai au prochain appel
  }
  progress = { at: Date.now(), data };
  return data;
}

async function report(id, position, final) {
  if (!connected || !/^[\w-]{11}$/.test(id) || !(position >= 0)) return false;
  const www = (u) => u.replace('https://s.', 'https://www.');
  let s = sessions.get(id);
  const now = Date.now();
  if (!s || now - s.last > SESSION_IDLE) {
    const p = await yt.actions.execute('/player', { videoId: id, client: 'TV' });
    const tr = p.data.playbackTracking;
    if (!tr?.videostatsWatchtimeUrl) return false;
    s = { cpn: Array.from({ length: 16 }, () => 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_'[Math.floor(Math.random() * 64)]).join(''),
          tr, len: Number(p.data.videoDetails?.lengthSeconds || 0), start: now, last: now, pos: position };
    sessions.set(id, s);
    await yt.actions.stats(www(tr.videostatsPlaybackUrl.baseUrl), CLIENT, { cpn: s.cpn, fmt: 251, rtn: 0, rt: 0, cmt: position, len: s.len });
    if (!final) return true;
  }
  const rt = ((now - s.start) / 1000).toFixed(3);
  const st = Math.min(s.pos, position);
  await yt.actions.stats(www(s.tr.videostatsWatchtimeUrl.baseUrl), CLIENT, {
    cpn: s.cpn, st: st.toFixed(3), et: position.toFixed(3), cmt: position.toFixed(3), rt, rtn: rt, len: s.len,
    state: final ? 'paused' : 'playing', final: final ? '1' : '0', ver: 2,
  });
  Object.assign(s, { last: now, pos: position });
  if (final) sessions.delete(id);
  if (id in progress.data && s.len) progress.data[id] = Math.round(100 * position / s.len);
  return true;
}

function body(req) {
  return new Promise((resolve) => {
    let b = '';
    req.on('data', (c) => { b += c; });
    req.on('end', () => { try { resolve(JSON.parse(b || '{}')); } catch { resolve({}); } });
  });
}

export function startYoutubeTv() {
  resume();
  http.createServer(async (req, res) => {
    const send = (code, data) => { res.writeHead(code, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(data)); };
    try {
      if (req.method === 'GET' && req.url === '/status') return send(200, { connected, pending, error });
      if (req.method === 'GET' && req.url === '/progress') return send(200, await getProgress());
      if (req.method === 'POST' && req.url === '/login') {
        error = null;
        const c = await client();
        c.session.signIn().catch((e) => { error = e.message; pending = null; });   // se termine une fois le code tapé
        for (let i = 0; i < 50 && !pending && !error; i++) await new Promise((r) => setTimeout(r, 100));
        return send(200, { connected, pending, error });
      }
      if (req.method === 'POST' && req.url === '/logout') {
        try { await yt?.session.signOut(); } catch {}
        fs.rmSync(TOKEN, { force: true });
        Object.assign(progress, { at: 0, data: {} });
        connected = false; pending = null; yt = null;
        return send(200, { connected });
      }
      if (req.method === 'POST' && req.url === '/report') {
        const b = await body(req);
        return send(200, { ok: await report(String(b.id || ''), Number(b.position), !!b.final) });
      }
      send(404, { error: 'inconnu' });
    } catch (e) {
      send(500, { error: e.message });
    }
  }).listen(PORT, '127.0.0.1');
}
