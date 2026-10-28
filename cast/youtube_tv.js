// Stream Box: YouTube account progress, through the "YouTube TV app" access (youtubei.js, unofficial; the official
// API gives neither history nor positions). Sign-in with a code on google.com/device, token in
// ~/.config/stream-box/youtube-tv-token.json (600). Small local server for remote.py (127.0.0.1:8091):
//   GET  /status    connected?, pending code
//   POST /login     requests a code;  POST /logout  forgets the token
//   GET  /progress  { id: percentage watched } from the history and the subscriptions feed (kept 10 min; YouTube
//                   only updates this percentage with a long delay: indicative only)
//   POST /report    { id, position, final }: position sent back to YouTube (the phone resumes where the TV stopped),
//                   like a player does: session start (/player, cpn), then segments watched in real time
//   GET  /recommended  videos of the account's YouTube home (the TV app's: FEwhat_to_watch, its first two pages: the
//                   shelves "Recommended", "Recently uploaded", topics…), without duplicates (kept 30 min: two
//                   requests, as the TV app makes when it opens and scrolls)
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import { Innertube, Log, ClientType, Constants } from 'youtubei.js';

const TOKEN = os.homedir() + '/.config/stream-box/youtube-tv-token.json';
const PORT = 8091;
const PROGRESS_CACHE = 600e3;
const RECOMMENDED_CACHE = 1800e3, RECOMMENDED_MAX = 30, RECOMMENDED_PAGES = 2;
const PAGES_HISTORY = 8, PAGES_SUBS = 2;   // ~15 videos per page
const SESSION_IDLE = 120e3;   // no report for 2 min: new playback session
const CLIENT = { client_name: Constants.CLIENTS.TV.NAME, client_version: Constants.CLIENTS.TV.VERSION };
Log.setLevel(Log.Level.NONE);

let yt = null, connected = false, pending = null, error = null;
let progress = { at: 0, data: {} };
let recommended = { at: 0, data: [] };
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
  // Token already there (startup): sign in again without a code
  const creds = readToken();
  if (!creds) return;
  try {
    await (await client()).session.signIn(creds);
    connected = true;
  } catch (e) {
    error = e.message;
  }
}

// Videos of a raw response with their watched percentage (TV client cards: percentDurationWatched in the thumbnail
// overlays)
function scan(node, out, cur = null) {
  if (Array.isArray(node)) { for (const n of node) scan(n, out, cur); return; }
  if (!node || typeof node !== 'object') return;
  const id = node.videoId || node.contentId;   // TV client cards: contentId
  if (typeof id === 'string' && /^[\w-]{11}$/.test(id)) cur = id;
  if (cur && typeof node.percentDurationWatched === 'number' && !(cur in out)) out[cur] = node.percentDurationWatched;
  for (const v of Object.values(node)) scan(v, out, cur);
}

// Next page token of a raw response
const nextPage = (raw) => (raw.match(/"(?:nextContinuationData|continuationCommand|reloadContinuationData)":\{[^}]*?"(?:continuation|token)":"([^"]+)"/) || [])[1];

async function getProgress() {
  if (!connected) return {};
  if (Date.now() - progress.at < PROGRESS_CACHE) return progress.data;
  const data = {};
  // The history holds almost all the progress (the subscriptions feed very little): several pages
  for (const [browseId, pages] of [['FEhistory', PAGES_HISTORY], ['FEsubscriptions', PAGES_SUBS]]) {
    try {
      let r = await yt.actions.execute('/browse', { browseId, client: 'TV' });
      for (let n = 1; ; n++) {
        scan(r.data, data);
        const token = n < pages && nextPage(JSON.stringify(r.data));
        if (!token) break;
        r = await yt.actions.execute('/browse', { continuation: token, client: 'TV' });
      }
    } catch (e) {
      console.error(`youtube_tv.js: ${browseId}:`, e.message);
      if (!Object.keys(data).length) return progress.data;   // retry at the next call
    }
  }
  progress = { at: Date.now(), data };
  return data;
}

// Text of a TV client text node (simpleText or runs)
const text = (t) => t?.simpleText ?? (t?.runs || []).map((r) => r.text).join('') ?? '';
// "1:14:35" → 4475; "1.8K views" → 1800 (the TV client answers in English)
const seconds = (s) => (/^\d+(:\d+)+$/.test(s || '') ? s.split(':').reduce((a, n) => a * 60 + Number(n), 0) : null);
function count(s) {
  const m = (s || '').replace(/,/g, '').match(/([\d.]+)\s*([KMB]?)\s+views?/i);
  return m ? Math.round(Number(m[1]) * ({ K: 1e3, M: 1e6, B: 1e9 }[m[2].toUpperCase()] || 1)) : null;
}

// Videos of a TV home response (FEwhat_to_watch): its video tiles, without duplicates, in order
export function recommendedVideos(data) {
  const out = [], seen = new Set();
  (function walk(n) {
    if (Array.isArray(n)) return n.forEach(walk);
    if (!n || typeof n !== 'object') return;
    const t = n.tileRenderer;
    if (t && t.contentType === 'TILE_CONTENT_TYPE_VIDEO' && /^[\w-]{11}$/.test(t.contentId || '') && !seen.has(t.contentId)) {
      seen.add(t.contentId);
      const head = t.header?.tileHeaderRenderer || {}, meta = t.metadata?.tileMetadataRenderer || {};
      const lines = (meta.lines || []).map((l) => (l.lineRenderer?.items || []).map((i) => text(i.lineItemRenderer?.text)));
      const overlay = (head.thumbnailOverlays || []).map((o) => text(o.thumbnailOverlayTimeStatusRenderer?.text)).find(Boolean);
      out.push({ id: t.contentId, title: text(meta.title), channel: lines[0]?.[0] || '',
                 thumb: `https://i.ytimg.com/vi/${t.contentId}/mqdefault.jpg`, url: `https://www.youtube.com/watch?v=${t.contentId}`,
                 seconds: seconds(overlay), live: overlay === 'LIVE', views: count(lines.flat().join(' ')) });
    }
    for (const v of Object.values(n)) walk(v);
  })(data);
  return out.slice(0, RECOMMENDED_MAX);
}

async function getRecommended() {
  if (!connected) return [];
  if (Date.now() - recommended.at < RECOMMENDED_CACHE) return recommended.data;
  try {
    const pages = [];
    let r = await yt.actions.execute('/browse', { browseId: 'FEwhat_to_watch', client: 'TV' });
    for (let n = 1; ; n++) {
      pages.push(r.data);
      const token = n < RECOMMENDED_PAGES && nextPage(JSON.stringify(r.data));
      if (!token) break;
      r = await yt.actions.execute('/browse', { continuation: token, client: 'TV' });
    }
    recommended = { at: Date.now(), data: recommendedVideos(pages) };
  } catch (e) {
    console.error('youtube_tv.js: FEwhat_to_watch:', e.message);   // the previous list, retried at the next call
  }
  return recommended.data;
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
      if (req.method === 'GET' && req.url === '/recommended') return send(200, await getRecommended());
      if (req.method === 'POST' && req.url === '/login') {
        error = null;
        const c = await client();
        c.session.signIn().catch((e) => { error = e.message; pending = null; });   // ends once the code is entered
        for (let i = 0; i < 50 && !pending && !error; i++) await new Promise((r) => setTimeout(r, 100));
        return send(200, { connected, pending, error });
      }
      if (req.method === 'POST' && req.url === '/logout') {
        try { await yt?.session.signOut(); } catch {}
        fs.rmSync(TOKEN, { force: true });
        Object.assign(progress, { at: 0, data: {} });
        Object.assign(recommended, { at: 0, data: [] });
        connected = false; pending = null; yt = null;
        return send(200, { connected });
      }
      if (req.method === 'POST' && req.url === '/report') {
        const b = await body(req);
        return send(200, { ok: await report(String(b.id || ''), Number(b.position), !!b.final) });
      }
      send(404, { error: 'unknown' });
    } catch (e) {
      send(500, { error: e.message });
    }
  }).listen(PORT, '127.0.0.1');
}
