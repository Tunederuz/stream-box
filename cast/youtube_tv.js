// Inlet: YouTube account progress, through the "YouTube TV app" access (youtubei.js, unofficial; the official
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
//   GET  /meta?id=  { title, seconds } of a video (/player, as the TV app asks before playing it)
//   GET  /subscriptions  latest videos of the subscribed channels (the TV app's FEsubscriptions, its "All" tab, two
//                   pages), newest first, lives at the top, without Shorts (kept 15 min; ?fresh=1: read again)
//   GET  /recommended?offset=N, /subscriptions?offset=N  "Load more": { items (30 from N on), more }, reading the
//                   feed's next pages when needed
//   GET  /rating?id=  { status: LIKE | DISLIKE | INDIFFERENT } of the account on a video (the TV /next)
//   POST /rate      { id, rating: like | dislike | none }: rates it as the TV app does (the like endpoints of the TV
//                   /next with their params; youtubei.js's interact.like is refused), { status } after
//   GET  /comments?id=&hl=&token=  { items, next } a page of the video's comments (20, by relevance): anonymous web
//                   session, raw /next (the comments section's continuation, then its pages; getComments fails on
//                   YouTube's current format); token: the next page's, or a comment's replies_token (its replies, 10
//                   at a time, the same shape), from a previous answer
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import { Innertube, Log, ClientType, Constants } from 'youtubei.js';

const TOKEN = os.homedir() + '/.config/stream-box/youtube-tv-token.json';
const PORT = 8091;
const PROGRESS_CACHE = 600e3;
const RECOMMENDED_CACHE = 1800e3, RECOMMENDED_MAX = 30, RECOMMENDED_PAGES = 2;
const PAGES_HISTORY = 8, PAGES_SUBS = 2;   // ~15 videos per page
const SUBS_CACHE = 900e3, SUBS_MAX = 60, SUBS_PAGES = 2;
const SESSION_IDLE = 120e3;   // no report for 2 min: new playback session
const CLIENT = { client_name: Constants.CLIENTS.TV.NAME, client_version: Constants.CLIENTS.TV.VERSION };
Log.setLevel(Log.Level.NONE);

let yt = null, connected = false, pending = null, error = null;
let progress = { at: 0, data: {} };
let recommended = { at: 0, data: [] };
let subscriptions = { at: 0, data: [] };
// "Load more" (TV menu): every video read so far of each feed, past the first page shown, and its next page's token
const feeds = { rec: { all: [], token: null }, subs: { all: [], token: null } };
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
  yt.session.on('auth', (d) => { saveToken(d); connected = true; pending = null; error = null; progress.at = 0; subscriptions.at = 0; });
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
export function recommendedVideos(data, max = RECOMMENDED_MAX) {
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
      const channel = (JSON.stringify(t.onLongPressCommand || {}).match(/"browseId":"(UC[\w-]{22})"/) || [])[1] || '';
      out.push({ id: t.contentId, title: text(meta.title), channel: lines[0]?.[0] || '', channel_id: channel,
                 thumb: `https://i.ytimg.com/vi/${t.contentId}/mqdefault.jpg`, url: `https://www.youtube.com/watch?v=${t.contentId}`,
                 seconds: seconds(overlay), live: overlay === 'LIVE', views: count(lines.flat().join(' ')) });
    }
    for (const v of Object.values(n)) walk(v);
  })(data);
  return out.slice(0, max);
}

async function getRecommended() {
  if (!connected) return [];
  if (Date.now() - recommended.at < RECOMMENDED_CACHE) return recommended.data;
  try {
    const pages = [];
    let r = await yt.actions.execute('/browse', { browseId: 'FEwhat_to_watch', client: 'TV' });
    let token = null;
    for (let n = 1; ; n++) {
      pages.push(r.data);
      token = nextPage(JSON.stringify(r.data));
      if (!token || n >= RECOMMENDED_PAGES) break;
      r = await yt.actions.execute('/browse', { continuation: token, client: 'TV' });
    }
    recommended = { at: Date.now(), data: recommendedVideos(pages) };
    feeds.rec = { all: recommendedVideos(pages, Infinity), token };
  } catch (e) {
    console.error('youtube_tv.js: FEwhat_to_watch:', e.message);   // the previous list, retried at the next call
  }
  return recommended.data;
}

// "2 hours ago", "Streamed 4 days ago" → seconds; null without (upcoming premiere…)
const UNITS = { second: 1, minute: 60, hour: 3600, day: 86400, week: 604800, month: 2629800, year: 31557600 };
function age(s) {
  const m = (s || '').match(/(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago/);
  return m ? Number(m[1]) * UNITS[m[2]] : null;
}

// Videos of the subscriptions feed (FEsubscriptions pages): video tiles only (the Shorts shelf has its own type),
// with the channel (its UC… id, from the tile's menu) and a date worked out from "… ago"; lives ("… watching") first
export function subscriptionVideos(pages, now = Date.now(), max = SUBS_MAX) {
  const out = [], seen = new Set();
  (function walk(n) {
    if (Array.isArray(n)) return n.forEach(walk);
    if (!n || typeof n !== 'object') return;
    const t = n.tileRenderer;
    if (t) {
      if (t.contentType === 'TILE_CONTENT_TYPE_VIDEO' && /^[\w-]{11}$/.test(t.contentId || '') && !seen.has(t.contentId)) {
        seen.add(t.contentId);
        const head = t.header?.tileHeaderRenderer || {}, meta = t.metadata?.tileMetadataRenderer || {};
        const lines = (meta.lines || []).map((l) => (l.lineRenderer?.items || []).map((i) => text(i.lineItemRenderer?.text)));
        const info = lines.slice(1).flat().join(' ');
        const overlay = (head.thumbnailOverlays || []).map((o) => text(o.thumbnailOverlayTimeStatusRenderer?.text)).find(Boolean);
        const live = /\bwatching\b/.test(info) || overlay === 'LIVE', secs = age(info);
        const channel = (JSON.stringify(t.onLongPressCommand || {}).match(/"browseId":"(UC[\w-]{22})"/) || [])[1] || '';
        if (live || secs !== null)
          out.push({ id: t.contentId, title: text(meta.title), channel: lines[0]?.[0] || '', channel_id: channel,
                     thumb: `https://i.ytimg.com/vi/${t.contentId}/mqdefault.jpg`, url: `https://www.youtube.com/watch?v=${t.contentId}`,
                     seconds: live ? null : seconds(overlay), live, views: count(info),
                     date: new Date(now - 1000 * (secs || 0)).toISOString(), age: live ? -1 : secs });
      }
      return;
    }
    for (const v of Object.values(n)) walk(v);
  })(pages);
  out.sort((a, b) => a.age - b.age);
  return out.slice(0, max).map(({ age: _, ...v }) => v);
}

// Next page of the feed itself (its section list), not of one of its rows
function feedNext(data) {
  let token = null;
  (function walk(n) {
    if (token || !n || typeof n !== 'object') return;
    const list = n.sectionListRenderer || n.sectionListContinuation;
    if (list) { token = list.continuations?.[0]?.nextContinuationData?.continuation || null; return; }
    for (const v of Object.values(n)) walk(v);
  })(data);
  return token;
}

async function getSubscriptions() {
  if (!connected) return [];
  if (Date.now() - subscriptions.at < SUBS_CACHE) return subscriptions.data;
  try {
    let r = await yt.actions.execute('/browse', { browseId: 'FEsubscriptions', client: 'TV' });
    // Its first tab ("All"; the others: one per channel)
    const pages = [r.data.contents?.tvBrowseRenderer?.content?.tvSecondaryNavRenderer?.sections?.[0]
      ?.tvSecondaryNavSectionRenderer?.tabs?.[0] || r.data];
    let token = feedNext(pages[0]);
    for (let n = 1; n < SUBS_PAGES && token; n++) {
      r = await yt.actions.execute('/browse', { continuation: token, client: 'TV' });
      pages.push(r.data);
      token = feedNext(r.data);
    }
    subscriptions = { at: Date.now(), data: subscriptionVideos(pages) };
    feeds.subs = { all: subscriptionVideos(pages, Date.now(), Infinity), token };
  } catch (e) {
    console.error('youtube_tv.js: FEsubscriptions:', e.message);   // the previous list, retried at the next call
  }
  return subscriptions.data;
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

// "Load more": the feed's videos from offset on (count of them), reading its next pages when the ones already read run
// out (at most 4 more pages per call); more: there may be others after
// Rating of the account on a video, and the params of the three like endpoints offered by the TV /next
async function rating(id) {
  const raw = JSON.stringify((await yt.actions.execute('/next', { videoId: id, client: 'TV' })).data);
  const param = (k) => decodeURIComponent((raw.match(new RegExp(`"${k}":"([^"]+)"`)) || [])[1] || '');
  return { status: (raw.match(/"likeStatus":"(\w+)"/) || [])[1] || 'INDIFFERENT',
           like: param('likeParams'), dislike: param('dislikeParams'), none: param('removeLikeParams') };
}

const RATE_PATH = { like: '/like/like', dislike: '/like/dislike', none: '/like/removelike' };
const RATED = { like: 'LIKE', dislike: 'DISLIKE', none: 'INDIFFERENT' };
async function rate(id, how) {
  const r = await rating(id);   // fresh params (they carry a time)
  await yt.actions.execute(RATE_PATH[how], { target: { videoId: id }, params: r[how] || undefined, client: 'TV' });
  return { status: RATED[how] };
}

// Comments: anonymous web sessions (one per language: the dates, "2 days ago", come translated)
const webs = new Map();
async function web(hl) {
  if (!webs.has(hl)) webs.set(hl, Innertube.create({ retrieve_player: false, lang: hl }));
  return webs.get(hl);
}
const continuations = (raw) => [...raw.matchAll(/"continuationCommand":\{"token":"([^"]+)"/g)];
async function comments(id, hl, token) {
  const w = await web(hl);
  if (!token) {   // the first page's token: the continuation of the comments section of the watch page
    const raw = JSON.stringify((await w.actions.execute('/next', { videoId: id, client: 'WEB' })).data);
    const sec = raw.indexOf('"comment-item-section"');
    if (sec < 0) return { items: [], next: null };   // comments turned off
    const found = continuations(raw).find((m) => Math.abs(m.index - sec) < 4000);
    if (!found) return { items: [], next: null };
    token = found[1];
  }
  return commentPage((await w.actions.execute('/next', { continuation: token, client: 'WEB' })).data);
}

// A page of comments, or of a comment's replies (same shape): its items (comment threads, or replies), in order; the
// texts are in the entities (commentEntityPayload) found by the item's commentKey. replies: the token of a thread's
// replies; next: the token of the page's last item, "more comments" / "show more replies"
const tokenIn = (node) => (JSON.stringify(node || {}).match(/"continuationCommand":\{"token":"([^"]+)"/) || [])[1] || null;
function commentPage(data) {
  const byKey = new Map();
  for (const m of data.frameworkUpdates?.entityBatchUpdate?.mutations || []) {
    const c = m.payload?.commentEntityPayload;
    if (c) byKey.set(c.key || m.entityKey, c);
  }
  const list = (data.onResponseReceivedEndpoints || [])
    .flatMap((e) => (e.reloadContinuationItemsCommand || e.appendContinuationItemsAction)?.continuationItems || []);
  const items = [];
  for (const it of list) {
    const thread = it.commentThreadRenderer;
    const c = byKey.get((thread || it).commentViewModel?.commentViewModel?.commentKey
                        || it.commentViewModel?.commentKey);
    if (!c) continue;
    items.push({
      author: c.author?.displayName || '', avatar: c.author?.avatarThumbnailUrl || '',
      date: c.properties?.publishedTime || '', likes: c.toolbar?.likeCountNotliked?.trim() || '',
      replies: c.toolbar?.replyCount || '', text: (c.properties?.content?.content || '').slice(0, 2000),
      replies_token: thread ? tokenIn(thread.replies) : null,
    });
  }
  const last = list[list.length - 1];
  return { items, next: items.length && last?.continuationItemRenderer ? tokenIn(last) : null };
}

async function feedMore(kind, offset, count = 30) {
  if (!connected) return { items: [], more: false };
  if (!feeds[kind].all.length) await (kind === 'rec' ? getRecommended() : getSubscriptions());
  const f = feeds[kind], seen = new Set(f.all.map((v) => v.id));
  for (let n = 0; n < 4 && f.all.length < offset + count && f.token; n++) {
    try {
      const r = await yt.actions.execute('/browse', { continuation: f.token, client: 'TV' });
      f.token = kind === 'rec' ? nextPage(JSON.stringify(r.data)) : feedNext(r.data);
      const page = kind === 'rec' ? recommendedVideos(r.data, Infinity) : subscriptionVideos([r.data], Date.now(), Infinity);
      for (const v of page) if (!seen.has(v.id)) { seen.add(v.id); f.all.push(v); }
    } catch (e) {
      console.error(`youtube_tv.js: next page (${kind}):`, e.message);
      f.token = null;
    }
  }
  return { items: f.all.slice(offset, offset + count), more: f.all.length > offset + count || !!f.token };
}

export function startYoutubeTv() {
  resume();
  http.createServer(async (req, res) => {
    const send = (code, data) => { res.writeHead(code, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(data)); };
    try {
      if (req.method === 'GET' && req.url === '/status') return send(200, { connected, pending, error });
      if (req.method === 'GET' && req.url === '/progress') return send(200, await getProgress());
      if (req.method === 'GET' && req.url === '/recommended') return send(200, await getRecommended());
      const more = req.method === 'GET' && req.url.match(/^\/(recommended|subscriptions)\?offset=(\d+)$/);
      if (more) return send(200, await feedMore(more[1] === 'recommended' ? 'rec' : 'subs', Number(more[2])));
      if (req.method === 'GET' && req.url.startsWith('/meta?id=')) {
        const id = decodeURIComponent(req.url.slice(9));
        if (!connected || !/^[\w-]{11}$/.test(id)) return send(404, { error: 'unknown' });
        const d = (await yt.actions.execute('/player', { videoId: id, client: 'TV' })).data.videoDetails || {};
        return send(200, { title: d.title || null, seconds: Number(d.lengthSeconds) || null });
      }
      if (req.method === 'GET' && req.url.startsWith('/rating?id=')) {
        const id = decodeURIComponent(req.url.slice(11));
        if (!connected || !/^[\w-]{11}$/.test(id)) return send(404, { error: 'unknown' });
        return send(200, { status: (await rating(id)).status });
      }
      if (req.method === 'POST' && req.url === '/rate') {
        const b = await body(req);
        const id = String(b.id || '');
        if (!connected || !/^[\w-]{11}$/.test(id) || !RATE_PATH[b.rating]) return send(400, { error: 'bad request' });
        return send(200, await rate(id, b.rating));
      }
      if (req.method === 'GET' && req.url.startsWith('/comments?')) {
        const q = new URL(req.url, 'http://x').searchParams;
        const id = q.get('id') || '', hl = /^[a-z]{2}$/.test(q.get('hl') || '') ? q.get('hl') : 'en';
        if (!/^[\w-]{11}$/.test(id)) return send(400, { error: 'bad request' });
        return send(200, await comments(id, hl, q.get('token') || null));
      }
      if (req.method === 'GET' && req.url.startsWith('/subscriptions')) {
        if (req.url.endsWith('fresh=1')) subscriptions.at = 0;
        return send(200, await getSubscriptions());
      }
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
        Object.assign(subscriptions, { at: 0, data: [] });
        feeds.rec = { all: [], token: null }; feeds.subs = { all: [], token: null };
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
