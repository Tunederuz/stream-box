// Stream Box: the full TV menu in QML (rendered by the GPU), used when the player is the Qt app
// (ui.py). Same tabs and same actions: everything goes through the remote.py API, like the companion app.
// Keys arrive from ui.py (box.keyPressed) already translated: up, down, left, right, ok, back, home (Menu button,
// closes), homescreen (WWW), corner (Play), menu (≡: options of the chosen card, including the second stream).
// Coordinates in 1920x1080, scaled by ui.qml. Second stream: "pip" object from ui.py. Data, keys and actions here;
// the drawing in qml/menu/ (one component per tab and per dialog, given this object as "menu").
import QtQuick
import QtQuick.Effects
import "fmt.js" as Fmt
import "i18n.js" as I18n
import "menu"
import "menu/layout.js" as Layout

Item {
    id: menu
    width: 1920
    height: 1080
    property bool isOpen: false
    // Closing with the home screen: it fades in over the menu (600 ms), the menu stays shown under it meanwhile
    property bool underHome: false
    onIsOpenChanged: if (!isOpen && box.ambientOn) { underHome = true; underHomeEnd.restart() }
    Timer { id: underHomeEnd; interval: 650; onTriggered: menu.underHome = false }
    opacity: isOpen || underHome ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
    function tr(s, a) { return I18n.t(i18n.dict, s, a) }

    readonly property string api: "http://127.0.0.1:8080"
    readonly property var tabs: [
        { id: "live", label: "Live" }, { id: "follows", label: "Following" },
        { id: "replays", label: "Replays" }, { id: "youtube", label: "YouTube" },
        { id: "jellyfin", label: "Jellyfin" },
        { id: "history", label: "History" },
        { id: "settings", label: "Settings" }, { id: "system", label: "System" }]
    readonly property var corners: ({ tl: "↖ top left", tr: "↗ top right", br: "↘ bottom right", bl: "↙ bottom left" })
    readonly property var qrModes: [["always", "Always"], ["timed", "30 seconds"], ["never", "Never"]]
    readonly property var kinds: ({ youtube: "YouTube", "twitch-vod": "Twitch replay", "twitch-clip": "Twitch clip", link: "Link", jellyfin: "Jellyfin" })

    // Data (reloaded on open; reassigned as a whole so bindings follow)
    property var st: ({})
    property var follows: null
    property var replays: ({})
    property var history: null
    property var display: null
    property var account: null
    property var followsQr: null
    property var health: null                // /api/health, reloaded every 5 s on the System tab
    property var wifi: null
    property var audioOut: null
    // Bluetooth (System menu): /api/bluetooth, and current step of the dialog ("", scan, pair)
    property var bt: null
    property var ssh: null                   // /api/ssh: SSH access (maintenance) on or off
    property var dev: null                   // /api/dev: developer mode (sudo for media, SSH)
    property var install: null               // /api/install: box booted from its USB stick, internal disks, progress
    property string btPhase: ""              // /api/audio: audio outputs, choice ("auto" or an output), current output                  // /api/wifi, same ("Wi-Fi" row: setup mode)
    // YouTube: channels of the list (/api/youtube), search results, row and choice per row
    property var yt: null
    // YouTube account: dialog with the code to enter on google.com/device (/api/youtube_account), and its QR code
    property var ytAuth: null
    property var ytAuthQr: null
    property var ytAccount: null             // same state, for the "YouTube account" row of the System menu
    // Colors per tab: purple for Twitch (live, following, replays), red for YouTube, neutral (charcoal, white glow)
    // for what belongs to no service (history, settings, system), blue for Jellyfin
    readonly property string theme: tabId === "youtube" || tabId === "jellyfin" ? tabId
        : ["live", "follows", "replays"].indexOf(tabId) >= 0 ? "twitch" : "neutral"
    readonly property var pal: theme === "youtube"
        ? { accent: "#ff0033", veil: "#180407", rail: "#1a0709", sheet: "#261216", key: "#3a1f24",
            surface: "#33171c", surfaceFocus: "#4a2027", label: "#c9a3aa" }
        : theme === "jellyfin"
        ? { accent: "#1565c0", veil: "#030f17", rail: "#06131c", sheet: "#0f202c", key: "#173244",
            surface: "#12293a", surfaceFocus: "#1b3c54", label: "#9cc3d8" }
        : theme === "twitch"
        ? { accent: "#9146ff", veil: "#0a0612", rail: "#100b17", sheet: "#21182c", key: "#33283f",
            surface: "#2a2034", surfaceFocus: "#3a2c4e", label: "#a99fc0" }
        : { accent: "#e8e8ee", veil: "#0b0b0d", rail: "#121214", sheet: "#1e1e22", key: "#2f2f35",
            surface: "#232327", surfaceFocus: "#35353c", label: "#a3a3ad" }
    readonly property color accent: pal.accent
    property var ytResults: null             // { query, results, channels } or null
    property var ytPreview: null             // found channel, opened: { id, name, avatar, followers, videos, saved }
    property bool ytSearching: false
    property int ytRow: 0                    // 0: search row, then results (if any) and channels
    property var ytSel: ({})
    // Jellyfin: home (/api/jellyfin), search, episodes of an opened series, row and choice per row
    property var jf: null
    property var jfResults: null             // { query, results } or null
    property var jfPreview: null             // opened series: { id, name, episodes, first }
    property bool jfSearching: false
    property int jfRow: 0
    property var jfSel: ({})
    // Row-based tabs (YouTube, Jellyfin): same page, same keyboard, separate state for each
    readonly property bool jfTab: tabId === "jellyfin"
    readonly property int mRow: jfTab ? jfRow : ytRow
    readonly property var mSel: jfTab ? jfSel : ytSel
    readonly property bool mSearching: jfTab ? jfSearching : ytSearching
    readonly property var mResults: jfTab ? jfResults : ytResults
    // On-screen keyboard (search): text, chosen row and column
    property bool kbOpen: false
    property string kbText: ""
    // Keyboard opened or closed: reported to the box, the companion app then offers to type the text
    onKbOpenChanged: call("POST", "/api/keyboard", { open: kbOpen, text: kbText, target: jfTab ? "Jellyfin" : "YouTube" })
    property int kbRow: 0
    property int kbCol: 0
    readonly property var kbKeys: [
        "abcdefghij".split(""), "klmnopqrst".split(""), "uvwxyz-'.?".split(""), "0123456789".split(""),
        "éèàçùêô".split("").concat(["Space"]), ["Delete", "Clear all", "Search"]]
    readonly property var ambient: { try { return JSON.parse(box.ambient || "{}") } catch (e) { return {} } }

    // Focus
    property int tab: 0
    readonly property string tabId: tabs[tab].id
    property string area: "content"          // rail or content
    property bool railHome: false            // rail: focus on "Home screen" (above the tabs)
    property int shortcut: -1                // Live: shortcut chosen above the grid, -1 = grid
    property int liveSel: 0
    property int followSel: 0
    property int histSel: 0
    property int setSel: 0                   // index in settingsRows (selectable rows only)
    property int sysSel: 0
    property int rpRow: 0                    // 0 chips, 1 replays, 2 clips (if any)
    property var rpSel: [0, 0, 0]
    property string rpLogin: ""
    property string pendingDisplay: ""
    property string pendingPlayer: ""        // player chosen with the arrows, applied by OK (the player restarts)
    property real poweroffUntil: 0
    property real rebootUntil: 0             // "Restart the box": second OK within 4 s
    property bool powerOnly: false           // "Box" dialog alone, without the menu behind (power held)
    property var modal: null                 // { title, items: [{ label, danger, ok }] }
    property int modalSel: 0
    property date now: new Date()
    property bool startFocus: false          // on open: focus to move onto the watched streamer

    // remote.py API

    function call(method, path, body, cb) {
        var x = new XMLHttpRequest()
        x.onreadystatechange = function () {
            if (x.readyState !== XMLHttpRequest.DONE) return
            var d = null
            try { d = JSON.parse(x.responseText) } catch (e) {}
            if (cb) cb(x.status === 200 ? d : null)
        }
        x.open(method, api + path)
        if (body !== undefined) x.setRequestHeader("Content-Type", "application/json")
        x.send(body !== undefined ? JSON.stringify(body) : null)
    }
    property string stJson: ""
    function refresh() {
        call("GET", "/api/state", undefined, function (d) {
            if (!d || !d.streamers) return
            var j = JSON.stringify(d)
            if (j !== stJson) { stJson = j; st = d }   // same state: nothing to recompute
            if (startFocus) {   // on open, before any key: tab of the current media
                liveSel = Math.max(0, d.streamers.indexOf(d.channel))
                var t = mediaTab(d)
                for (var i = 0; i < tabs.length; i++) if (tabs[i].id === t && tab !== i) { tab = i; area = "content" }
                if (area === "rail" && canEnter(tabs[tab].id)) area = "content"
            }
            checkArea()
        })
    }
    function act(name, body) { call("POST", "/api/" + name, body || {}, function () { refreshSoon.restart() }) }
    function loadFollows() {
        call("GET", "/api/follows", undefined, function (d) {
            follows = d || { error: true }
            checkArea()
            var p = follows.pending
            if (p && p.verification_uri && !p.error) {
                if (!followsQr || followsQr.text !== p.verification_uri)
                    call("GET", "/api/qr?text=" + encodeURIComponent(p.verification_uri), undefined, function (q) {
                        followsQr = q ? { text: p.verification_uri, rows: q.rows } : null
                    })
                followsPoll.restart()   // waiting for the code entered on twitch.tv/activate
            }
        })
    }
    function loadReplays(login) {
        if (!login || replays[login] !== undefined) return
        var r = Object.assign({}, replays); r[login] = "loading"; replays = r
        call("GET", "/api/replays?login=" + encodeURIComponent(login), undefined, function (d) {
            var r2 = Object.assign({}, replays); r2[login] = d && d.vods ? d : false; replays = r2
        })
    }
    function loadYoutube() {
        call("GET", "/api/youtube", undefined, function (d) { if (d && d.channels) yt = d; else if (!yt) yt = { channels: [] } })
    }
    function ytSearch(q) {
        q = q.trim()
        if (!q) return
        ytResults = { query: q, results: [], channels: [] }   // before ytSearching: the search row text reads query
        ytSearching = true
        ytPreview = null
        call("GET", "/api/youtube_search?q=" + encodeURIComponent(q), undefined, function (d) {
            ytSearching = false
            ytResults = { query: q, results: d && d.results ? d.results : [], channels: d && d.channels ? d.channels : [], error: !d }
            ytRow = 1; var s = Object.assign({}, ytSel); s["search"] = 0; ytSel = s
        })
    }
    // Rows of the YouTube tab: search, results, one per channel
    function ytRows() {
        var rows = [{ kind: "search" }]
        if (ytResults && ytResults.channels.length)
            rows.push({ kind: "chans", key: "chans", title: tr("Channels"), items: ytResults.channels })
        if (ytPreview)
            rows.push({ kind: "preview", key: "preview", title: tr("{name} · latest videos", { name: ytPreview.name }), avatar: ytPreview.avatar,
                        items: ytPreview.videos || [], loading: ytPreview.videos === null })
        if (ytResults) rows.push({ kind: "results", key: "search", title: tr("Results for \"{query}\"", { query: ytResults.query }), items: ytResults.results })
        var subs = yt && yt.subs
        if (subs && subs.authorized)
            rows.push({ kind: "subs", key: "subs", title: tr("Subscriptions"), items: subs.videos || [], loading: subs.videos === null })
        else if (subs && subs.configured)
            rows.push({ kind: "connect", key: "connect", title: tr("Subscriptions"),
                        items: [{ title: tr("Connect my account"), connect: true }] })
        var chans = yt ? yt.channels : []
        for (var i = 0; i < chans.length; i++)
            rows.push({ kind: "channel", key: chans[i].id, title: chans[i].name, avatar: chans[i].avatar, items: chans[i].videos || [] })
        return rows
    }
    // Channel found by the search: see its videos (row just below the channels), add or remove it
    function ytChannelMenu(c) {
        openModal(c.name + (c.followers ? " · " + tr("{n} subscribers", { n: Fmt.big(c.followers, tr) }) : ""), [
            { label: tr("▶  See latest videos"), ok: function () { ytOpenChannel(c) } },
            { label: tr(c.saved ? "✕  Remove from favorites" : "★  Add to favorites"), ok: function () { ytToggleSaved(c) } }])
    }
    function ytOpenChannel(c) {
        ytPreview = { id: c.id, name: c.name, avatar: c.avatar, videos: null }
        var s = Object.assign({}, ytSel); s["preview"] = 0; ytSel = s
        ytRow = Math.max(1, ytRows().findIndex(function (r) { return r.kind === "preview" }))   // just below the found channels
        call("GET", "/api/youtube_channel?id=" + encodeURIComponent(c.id), undefined, function (d) {
            if (ytPreview && ytPreview.id === c.id) ytPreview = Object.assign({}, ytPreview, { videos: d ? d.videos : [] })
        })
    }
    // YouTube account: code to enter on google.com/device; the dialog reloads every 3 s until authorized
    // tv: progress through the "YouTube TV app" access (cast/youtube_tv.js), otherwise subscriptions (own Google app)
    function ytConnect(tv) {
        ytAuth = { tv: !!tv, pending: null }
        call("POST", tv ? "/api/youtube_tv_login" : "/api/youtube_login", {}, function (d) {
            if (!d) ytAuth = { tv: !!tv, pending: { error: tv ? tr("YouTube unreachable") : tr("Google unreachable, or app misconfigured") } }
            else loadYtAuth()
        })
    }
    function loadYtAccount() { call("GET", "/api/youtube_account", undefined, function (d) { if (d) ytAccount = d }) }
    function loadYtAuth() {
        if (!ytAuth) return
        call("GET", "/api/youtube_account", undefined, function (d) {
            if (!ytAuth || !d) return
            ytAccount = d
            var tv = ytAuth.tv, st = tv ? (d.tv || {}) : d
            if (tv ? st.connected : st.authorized) { ytAuth = null; yt = null; loadYoutube(); return }
            var p = st.pending || (st.error ? { error: st.error } : null)
            ytAuth = { tv: tv, pending: p }
            if (p && p.verification_uri && !p.error) {
                if (!ytAuthQr || ytAuthQr.text !== p.verification_uri)
                    call("GET", "/api/qr?text=" + encodeURIComponent(p.verification_uri), undefined, function (q) {
                        ytAuthQr = q ? { text: p.verification_uri, rows: q.rows } : null
                    })
                ytAuthPoll.restart()
            }
        })
    }
    function ytAccountMenu() {
        var a = ytAccount
        if (!a) return
        var items = []
        if (a.configured && !a.authorized)
            items.push({ label: tr("+  Connect my subscriptions"), ok: function () { ytConnect(false) } })
        if (a.authorized) {
            items.push({ label: tr("↻  Reload my subscriptions"), ok: function () {
                call("POST", "/api/youtube_sync", {}, function () { yt = null; loadYoutube() }) } })
        }
        if (a.tv && !a.tv.unavailable)
            items.push(a.tv.connected
                ? { label: tr("✕  Stop syncing progress"), danger: true, ok: function () {
                    call("POST", "/api/youtube_tv_logout", {}, function () { yt = null; loadYtAccount() }) } }
                : { label: tr("⟳  Sync progress"), ok: function () { ytConnect(true) } })
        if (a.authorized)
            items.push({ label: tr("✕  Disconnect subscriptions"), danger: true, ok: function () {
                call("POST", "/api/youtube_logout", {}, function () { yt = null; loadYtAccount() }) } })
        openModal(tr("YouTube account") + (a.channels !== null ? " · " + tr("{n} subscriptions", { n: a.channels }) : ""), items)
    }
    // Options on a subscription video: play, channel as favorite (a row of its own)
    function ytSubOptions(v) {
        var fav = (yt ? yt.channels : []).some(function (c) { return c.id === v.channel_id })
        var c = { id: v.channel_id, name: v.channel, avatar: v.avatar, saved: fav }
        openModal(v.channel, [
            { label: tr("▶  Play the video"), ok: function () { chooseVideo(v) } },
            { label: tr("▶  See latest videos"), ok: function () { ytOpenChannel(c) } },
            { label: tr(fav ? "✕  Remove from favorites" : "★  Add to favorites"), ok: function () { ytToggleSaved(c) } }])
    }
    function ytToggleSaved(c) {
        call("POST", "/api/youtube_channels", { action: c.saved ? "remove" : "add", channel: c.id }, function (d) {
            if (d && ytResults)
                ytResults = Object.assign({}, ytResults, { channels: ytResults.channels.map(function (x) {
                    return x.id === c.id ? Object.assign({}, x, { saved: !c.saved }) : x }) })
            loadYoutube()
        })
    }
    function ago(iso) {
        var days = Math.floor((Date.now() - new Date(iso)) / 86400000)
        return days <= 0 ? tr("today") : days === 1 ? tr("yesterday") : days < 7 ? tr("{n} d ago", { n: days })
            : days < 31 ? tr("{n} wk ago", { n: Math.floor(days / 7) })
            : new Date(iso).toLocaleDateString(Qt.locale(i18n.lang === "fr" ? "fr_FR" : "en_US"), "d MMM")
    }
    function loadJellyfin() {
        call("GET", "/api/jellyfin", undefined, function (d) { jf = d || { error: true } })
    }
    function jfSearch(q) {
        q = q.trim()
        if (!q) return
        jfResults = { query: q, results: [] }   // before jfSearching: the search row text reads query
        jfSearching = true
        jfPreview = null
        call("GET", "/api/jellyfin_search?q=" + encodeURIComponent(q), undefined, function (d) {
            jfSearching = false
            jfResults = { query: q, results: d && d.results ? d.results : [], error: !d }
            jfRow = 1; var s = Object.assign({}, jfSel); s["search"] = 0; jfSel = s
        })
    }
    // Rows of the Jellyfin tab: search, opened series, results, resume, next episodes, recently added
    function jfRows() {
        var rows = [{ kind: "search" }]
        if (jfPreview)
            rows.push({ kind: "preview", key: "preview", title: tr("{name} · episodes", { name: jfPreview.name }), items: jfPreview.episodes || [],
                        loading: jfPreview.episodes === null })
        if (jfResults) rows.push({ kind: "results", key: "search", title: tr("Results for \"{query}\"", { query: jfResults.query }), items: jfResults.results })
        if (jf && jf.configured) {
            if (jf.resume.length) rows.push({ kind: "jf", key: "resume", title: tr("Resume"), items: jf.resume })
            if (jf.nextup.length) rows.push({ kind: "jf", key: "nextup", title: tr("Next episodes"), items: jf.nextup })
            for (var i = 0; i < jf.libraries.length; i++)
                rows.push({ kind: "jf", key: "lib:" + jf.libraries[i].id, title: tr("{name} · recently added", { name: jf.libraries[i].name }), items: jf.libraries[i].items })
        }
        return rows
    }
    function mediaRows() { return jfTab ? jfRows() : ytRows() }
    // Chosen series (or season): its episodes in a row just below the search, focus on the first unwatched
    function jfOpenSeries(item) {
        jfPreview = { id: item.series, name: item.title, episodes: null }
        jfRow = 1
        call("GET", "/api/jellyfin_series?id=" + encodeURIComponent(item.series), undefined, function (d) {
            if (!jfPreview || jfPreview.id !== item.series) return
            jfPreview = Object.assign({}, jfPreview, { episodes: d ? d.episodes : [] })
            var s = Object.assign({}, jfSel); s["preview"] = d ? d.first : 0; jfSel = s
        })
    }
    function jfPlay(item, fromStart) {
        call("POST", "/api/jellyfin_play", { id: item.id, from_start: !!fromStart }, function () { refreshSoon.restart() })
        close()
    }
    function jfChoose(item) {
        if (item.type === "Series" || item.type === "Season") return jfOpenSeries(item)
        var name = item.episode ? item.title + " · " + item.episode : item.title
        var items = []
        if (Fmt.resumable(item.position, item.seconds, item.finished)) {
            items.push({ label: tr("▶  Resume at {time}", { time: Fmt.clock(item.position) }), ok: function () { jfPlay(item) } })
            items.push({ label: tr("↺  From the beginning"), ok: function () { jfPlay(item, true) } })
        } else items.push({ label: tr(item.finished ? "↺  Watch again" : "▶  Play"), ok: function () { jfPlay(item, true) } })
        if (item.type === "Episode" && item.series && !(jfPreview && jfPreview.id === item.series))
            items.push({ label: tr("☰  All episodes"), ok: function () { jfOpenSeries({ series: item.series, title: item.title }) } })
        openModal(name, items)
    }
    // Info line of a card in the row-based tabs
    function hm(t) {
        var h = Math.floor(t / 3600), m = Math.floor(t / 60) % 60
        return h > 0 ? h + " h " + (m < 10 ? "0" : "") + m : m + " min"
    }
    function cardMeta(row, it) {
        var parts
        if (jfTab)
            parts = it.type === "Series" ? [it.unplayed ? tr("{n} unwatched", { n: it.unplayed }) : tr("Series"), it.year]
                : it.episode ? [it.episode] : [it.year, it.seconds ? hm(it.seconds) : ""]
        else if (row.kind === "subs")
            parts = [it.channel, ago(it.date), it.seconds ? Fmt.clock(it.seconds) : ""]
        else if (row.kind === "connect")
            parts = [tr("Your YouTube subscriptions")]
        else if (row.kind === "results")
            parts = [it.channel, it.seconds ? Fmt.clock(it.seconds) : "", it.views ? tr("{n} views", { n: Fmt.big(it.views, tr) }) : ""]
        else
            parts = [ago(it.date), it.views ? tr("{n} views", { n: Fmt.big(it.views, tr) }) : ""]
        return parts.filter(function (t) { return !!t }).join(" · ") + (it.finished ? " · " + tr("watched") : "")
    }
    function searchLabel() {
        var r = mResults
        return mSearching ? tr("Searching for \"{query}\"…", { query: r.query })
            : r ? tr("New search  (\"{query}\")", { query: r.query })
            : jfTab ? tr("Search Jellyfin") : tr("Search YouTube")
    }
    function loadHistory() { call("GET", "/api/history", undefined, function (d) { history = d || []; checkArea() }) }
    function play(url, fromStart, item) {   // item: title and image for the loading screen and the history
        call("POST", "/api/play", { url: url, from_start: !!fromStart, title: item ? item.title : undefined,
                                    thumb: item ? item.thumb : undefined }, function () { refreshSoon.restart() })
        close()
    }

    Timer { id: refreshSoon; interval: 300; onTriggered: menu.refresh() }
    Timer {
        interval: 5000; repeat: true; triggeredOnStart: true
        running: menu.isOpen && menu.tabId === "system"
        onTriggered: {
            menu.call("GET", "/api/health", undefined, function (d) { if (d && d.temps) menu.health = d })
            menu.call("GET", "/api/wifi", undefined, function (d) { if (d) menu.wifi = d })
        }
    }
    Timer { interval: 4000; repeat: true; running: menu.isOpen; onTriggered: menu.refresh() }
    Timer { id: ytAuthPoll; interval: 3000; onTriggered: if (menu.isOpen) menu.loadYtAuth() }
    Timer { id: followsPoll; interval: 3000; onTriggered: if (menu.isOpen) menu.loadFollows() }
    Timer { interval: 10000; repeat: true; running: menu.isOpen; triggeredOnStart: true; onTriggered: menu.now = new Date() }
    Timer { id: idleClose; interval: 90000; onTriggered: menu.close() }   // TV screen: no still image
    Timer { id: poweroffReset; interval: 4100; onTriggered: menu.poweroffUntil = 0 }
    Timer { id: rebootReset; interval: 4100; onTriggered: menu.rebootUntil = 0 }

    // Opening, closing

    // Tab matching the current media: live → Live, YouTube video → YouTube, Jellyfin → Jellyfin, Twitch replay or
    // clip → Replays, other link → History
    function mediaTab(d) {
        if (d.mode !== "media") return "live"
        return { youtube: "youtube", jellyfin: "jellyfin", "twitch-vod": "replays", "twitch-clip": "replays" }[d.media_kind] || "history"
    }
    function open() {
        powerOnly = false
        if (isOpen) return
        // Tab of the current media (mediaTab, adjusted when the state arrives); YouTube and Jellyfin keep their row and
        // their card; the data is reloaded
        var t = mediaTab(st)
        for (var i = 0; i < tabs.length; i++) if (tabs[i].id === t) tab = i
        area = "rail"; railHome = false
        shortcut = -1; modal = null; pendingDisplay = ""; poweroffUntil = 0; rebootUntil = 0
        follows = null; replays = ({}); history = null; rpLogin = ""; rpRow = 0; rpSel = [0, 0, 0]
        jf = null; kbOpen = false   // search results stay from one opening to the next; yt too (reloaded in the background)
        var list = st.streamers || []
        liveSel = Math.max(0, list.indexOf(st.channel))
        startFocus = true
        if (canEnter(t)) area = "content"
        checkArea()
        loadTab(tabs[tab].id)
        isOpen = true
        box.setMenuOpen(true)
        refresh()
        call("GET", "/api/display", undefined, function (d) { if (d && d.modes) display = d })
        call("GET", "/api/account", undefined, function (d) { account = d })
        idleClose.restart()
    }
    function close() {
        if (!isOpen) return
        stopPreview()
        isOpen = false
        modal = null
        kbOpen = false
        box.setMenuOpen(false)
        idleClose.stop()
    }
    Connections {
        target: box
        function onOpenRequested() { menu.open() }
        function onPowerMenuRequested() { menu.open(); menu.powerMenu() }
        function onCloseRequested() { menu.close() }
        function onKeyPressed(k) { menu.key(k) }
        // Text typed on the phone while the search keyboard is open
        function onTextInput(text, submit) {
            if (!menu.kbOpen) return
            menu.kbText = text.slice(0, 80)
            if (submit && menu.kbText.trim()) { menu.kbOpen = false; if (menu.jfTab) menu.jfSearch(menu.kbText); else menu.ytSearch(menu.kbText) }
        }
    }
    Component.onCompleted: refresh()

    // Computed content

    function shortcuts() {
        var l = []
        if (st.mode !== "twitch" && st.channel)
            l.push({ label: tr("▶  Resume {channel}", { channel: st.channel }), ok: function () { act("twitch"); close() } })
        if (pip.channel) {   // second stream running
            l.push({ label: tr("Swap with {channel}", { channel: pip.channel }), ok: function () { pip.swap(); close() } })
            l.push(pip.layout === "split" ? { label: tr("Picture-in-picture"), ok: function () { pip.setLayout("pip") } }
                                          : { label: tr("Side by side"), ok: function () { pip.setLayout("split") } })
            l.push({ label: tr("Close {channel}", { channel: pip.channel }), ok: function () { pip.close() } })
        }
        return l
    }
    // ≡ menu on a streamer: watch it, or add it as a second stream next to the current one
    function streamerOptions(name, addToList, isLive) {
        var watch = function () { act("channel", { name: name }); close() }
        var items = [{ label: tr("▶  Watch"), ok: watch }]
        // Second stream: only a live channel (otherwise a black frame that waits), next to a live stream
        if (isLive && st.mode === "twitch" && st.channel && name !== st.channel) {
            items.push({ label: tr("As picture-in-picture"), ok: function () { pip.open(name, "pip"); close() } })
            items.push({ label: tr("Side by side"), ok: function () { pip.open(name, "split"); close() } })
        }
        if (addToList) items.push({ label: tr("+  Add to my list"), ok: function () { act("streamers", { action: "add", login: name }) } })
        openModal(name, items)
    }
    // Following: live then offline, computed once (and not per card)
    readonly property var followItems: !follows || !follows.authorized ? [] : (follows.live || []).concat(follows.offline || [])
    function followList() { return followItems }
    function inList(name) { return (st.streamers || []).indexOf(name) >= 0 }
    function replayRows() {
        var rows = [{ kind: "chips", items: st.streamers || [] }]
        var d = replays[rpLogin]
        if (d && d.vods) {
            if (d.vods.length) rows.push({ kind: "vods", title: tr("Replays"), items: d.vods })
            if (d.clips.length) rows.push({ kind: "clips", title: tr("Clips of the week"), items: d.clips })
        }
        return rows
    }
    function prettyMode(m) { return String(m).replace("x", " × ").replace("@", " · ") + " Hz" }
    function settingsRows() {
        var s = st
        var modes = ["auto"].concat(display ? display.modes : [])
        var cur = pendingDisplay || (display ? display.setting : "auto")
        var qi = 0
        for (var i = 0; i < qrModes.length; i++) if (qrModes[i][0] === s.qr) qi = i
        var langs = Object.keys(s.languages || { en: "English" })
        return [
            { header: tr("Language") },
            // names in their own language; the TV and the companion app switch right away (streambox-language)
            { label: tr("Interface language"), value: (s.languages || {})[s.lang] || "English", step: function (d) {
                var i = Math.max(0, langs.indexOf(s.lang))
                act("language", { lang: langs[(i + d + langs.length) % langs.length] })
            } },
            { header: tr("Chat") },
            { label: tr("Chat on the TV"), toggle: !!s.chat_visible, ok: function () { act("chat") } },
            { label: tr("Chat corner"), value: tr(corners[s.corner] || ""), step: function (d) {
                // the API can only move forward one corner: three steps forward make one step back
                for (var n = 0; n < (d > 0 ? 1 : 3); n++) act("corner")
            } },
            { label: tr("Chat background"), value: (s.chat_bg || 0) + " %", step: function (d) {
                act("set", { key: "chat_bg", value: Math.max(0, Math.min(100, (s.chat_bg || 0) + 10 * d)) })
            } },
            { label: tr("Text size"), value: (s.chat_size || 0) + " px", step: function (d) {
                act("set", { key: "chat_size", value: Math.max(20, Math.min(60, (s.chat_size || 0) + 2 * d)) })
            } },
            { header: tr("Subtitles") },
            { label: tr("Subtitle size"), value: (s.sub_size || 100) + " %", step: function (d) {
                act("set", { key: "sub_size", value: Math.max(50, Math.min(200, (s.sub_size || 100) + 10 * d)) })
            } },
            { label: tr("Subtitle background"), hint: tr("Black band behind the text, easier to read on a bright picture"),
              value: s.sub_bg ? s.sub_bg + " %" : tr("None"), step: function (d) {
                act("set", { key: "sub_bg", value: Math.max(0, Math.min(100, (s.sub_bg || 0) + 10 * d)) })
            } },
            { header: tr("Sound") },
            { label: tr("Audio output"),
              // automatic: USB or Bluetooth device plugged in, otherwise the TV (audio.py)
              hint: audioOut && audioCurrentLabel() ? tr("Right now: {output}", { output: audioCurrentLabel() }) : undefined,
              value: !audioOut ? "…" : audioOut.choice === "auto" ? tr("Automatic")
                   : (audioOut.outputs.filter(function (o) { return o.id === audioOut.choice })[0] || { label: tr("missing") }).label,
              step: function (d) {
                  if (!audioOut) return
                  var ids = ["auto"].concat(audioOut.outputs.map(function (o) { return o.id }))
                  var i = Math.max(0, ids.indexOf(audioOut.choice))
                  var next = ids[(i + d + ids.length) % ids.length]
                  audioOut = Object.assign({}, audioOut, { choice: next })
                  call("POST", "/api/audio", { output: next }, function () { loadAudio() })
              } },
            { header: tr("Playback") },
            { label: tr("Auto switch"), hint: tr("Switch to a live streamer if yours is offline"),
              toggle: !!s.auto_switch, ok: function () { act("auto_switch", { enabled: !s.auto_switch }) } },
            { label: tr("Polls and predictions"), hint: tr("At the top of the TV during a live stream"), toggle: !!s.events,
              ok: function () { act("flag", { key: "events", enabled: !s.events }) } },
            { label: tr("Night mode"), hint: tr("Loud sounds softened, voices boosted"), toggle: !!s.night,
              ok: function () { act("flag", { key: "night", enabled: !s.night }) } },
            { label: tr("Volume"), value: s.mute ? tr("muted") : (s.volume || 0) + " %", step: function (d) { act("volume", { delta: 5 * d }) } },
            { header: tr("Display") },
            { label: tr("Animated background"), hint: tr("Home screen and menu with no video behind"),
              value: tr(backdropNames.base[bd.base] || ""), step: function (d) { stepBackdrop("base", d) } },
            { label: tr("Overlay"), hint: tr("A layer added over the background"),
              value: tr(backdropNames.overlay[bd.overlay] || ""), step: function (d) { stepBackdrop("overlay", d) } },
            { label: tr("Home screen colors"), hint: tr("The menu itself takes the color of each tab"),
              value: tr(backdropNames.color[bd.color || "violet"] || ""), step: function (d) { stepBackdrop("color", d) } },
            { label: tr("TV resolution"),
              value: !display ? "…" : cur === "auto" ? tr("Auto ({mode})", { mode: prettyMode(display.auto) }) : prettyMode(cur),
              hint: pendingDisplay && display && pendingDisplay !== display.setting ? tr("OK to apply") : undefined,
              step: function (d) {
                  if (!display) return
                  var i = Math.max(0, modes.indexOf(cur))
                  pendingDisplay = modes[Math.max(0, Math.min(modes.length - 1, i + d))]
              },
              ok: function () {
                  if (!pendingDisplay || !display || pendingDisplay === display.setting) return
                  act("display", { mode: pendingDisplay })
                  pendingDisplay = ""
                  displayReload.restart()
              } },
            { label: tr("Companion app QR code"), value: tr(qrModes[qi][1]), step: function (d) {
                act("qr", { mode: qrModes[Math.max(0, Math.min(qrModes.length - 1, qi + d))][0] })
            } },
        ]
    }
    Timer { id: displayReload; interval: 3000; onTriggered: menu.call("GET", "/api/display", undefined, function (d) { if (d && d.modes) menu.display = d }) }
    function audioCurrentLabel() {
        var o = audioOut && audioOut.outputs.filter(function (x) { return x.id === audioOut.current })[0]
        return o ? o.label : ""
    }
    function selectable(rows) {
        var out = []
        for (var i = 0; i < rows.length; i++) if (!rows[i].header) out.push(i)
        return out
    }
    function systemRows() {
        var login = account && account.login
        return [
            { label: tr("Twitch account"), value: login ? tr("Connected: {login}", { login: login }) : tr("Not connected"),
              hint: login ? tr("No ads on the channels you're subscribed to") : tr("Sign in from the companion app on your phone") },
            { label: tr("YouTube account"), visible: !!(ytAccount && (ytAccount.configured || (ytAccount.tv && !ytAccount.tv.unavailable))),
              value: ytAccount && ytAccount.authorized
                   ? tr("Connected") + (ytAccount.channels !== null ? " · " + tr("{n} subscriptions", { n: ytAccount.channels }) : "")
                   : tr("Not connected"),
              hint: ytAccount && ytAccount.tv && ytAccount.tv.connected ? tr("Progress synced with your account (phone, computer)")
                  : tr("Subscriptions, and progress synced with your account"),
              ok: function () { ytAccountMenu() } },
            { label: tr("Version"), value: (pendingPlayer || st.player) === "mpv" ? tr("Simplified version") : tr("Full version"),
              // simplified: mpv alone, small menu (Twitch streamers); videos sent from the phone still play
              hint: pendingPlayer && pendingPlayer !== st.player ? tr("OK to apply: the player restarts")
                  : tr("Simplified: lighter, only Twitch streamers in the TV menu"),
              step: function (d) { pendingPlayer = (pendingPlayer || st.player) === "qt" ? "mpv" : "qt" },
              ok: function () {
                  if (!pendingPlayer || pendingPlayer === st.player) return
                  act("player", { mode: pendingPlayer })
                  pendingPlayer = ""
                  close()
              } },
            { label: "Wi-Fi", visible: !!(wifi && wifi.device),
              value: !wifi ? "" : wifi.connecting ? tr("connecting…") : wifi.mode === "hotspot" ? tr("setup mode")
                   : wifi.network ? (wifi.wired ? tr("cable") : wifi.network) : tr("no network"),
              hint: wifi && wifi.mode === "hotspot" ? tr("Wi-Fi \"{ssid}\", password {password}, then {url}", {
                      ssid: wifi.hotspot.ssid, password: wifi.hotspot.password,
                      url: String(wifi.hotspot.url).replace(/^http:\/\//, "").replace(/\/$/, "") })
                  : tr("OK: setup mode, to choose another network from the phone"),
              ok: function () { if (wifi && wifi.mode !== "hotspot") act("wifi", { action: "hotspot" }) } },
            { label: tr("Remotes and controllers"),
              value: bt ? tr(bt.paired.length > 1 ? "{n} devices paired" : "{n} device paired", { n: bt.paired.length }) : "",
              hint: tr("Pair, unpair"), ok: function () { btMenu() } },
            { label: tr("Set up keys"), hint: tr("Learn the keys of a remote or a controller, one by one"),
              ok: function () { act("keymap", { action: "wizard" }); close() } },
            { label: tr("Default keys"), ok: function () { act("keymap", { action: "reset" }) } },
            { label: tr("SSH access"), visible: !!(ssh && ssh.available), toggle: !!(ssh && ssh.enabled),
              hint: !(ssh && ssh.enabled) ? tr("Off: no more remote command-line access")
                  : "ssh " + (ssh.address || tr("media@<box address>"))
                    + "  ·  " + (ssh.password ? tr("password: {password}", { password: ssh.password }) : tr("by key")),
              ok: function () {
                  var on = !ssh.enabled
                  ssh = Object.assign({}, ssh, { enabled: on })   // on screen right away
                  call("POST", "/api/ssh", { enabled: on }, function () { loadSsh() })
              } },
            { label: tr("Developer mode"), visible: !!(dev && dev.available), toggle: !!(dev && dev.enabled),
              hint: dev && dev.enabled ? tr("Passwordless sudo for media, over SSH (password above)")
                                       : tr("Root access to develop and test the box"),
              ok: function () {
                  if (dev.enabled) { call("POST", "/api/dev", { enabled: false }, function () { loadSsh() }); dev = Object.assign({}, dev, { enabled: false }); return }
                  openModal(tr("Enable developer mode? media will get passwordless sudo, and SSH turns on"), [
                      { label: tr("Enable"), danger: true, ok: function () {
                          call("POST", "/api/dev", { enabled: true }, function () { loadSsh() }) } },
                      { label: tr("Cancel"), ok: function () {} }])
              } },
            { label: tr("Install on this PC"), visible: !!(install && install.available),
              value: install && install.progress && install.progress.state === "running" ? install.progress.percent + " %" : "",
              hint: tr("The box runs from its USB stick: copy it, settings included, to the internal disk"),
              ok: function () { installMenu() } },
            { label: tr("Backup and restore"), hint: tr("On a USB stick, or as a file from the companion app"),
              ok: function () { backupMenu() } },
            { label: tr("Update now"),
              hint: health && health.update ? (health.update.running ? tr("Update in progress…")
                    : (health.update.last ? tr(health.update.last.ok ? "Last: {date}" : "Failed: {date}",
                                               { date: frDate(health.update.last.date) }) : tr("Never"))
                      + (health.update.next ? "  ·  " + tr("next: {date}", { date: frDate(health.update.next) }) : "")) : undefined,
              ok: function () { if (!(health && health.update && health.update.running)) act("update") } },
            { label: tr("Power button"), hint: tr("Remote, phone and Home Assistant"),
              value: st.power_action === "suspend" ? tr("Sleep") : tr("Full shutdown"),
              step: function (d) { act("power_action", { mode: st.power_action === "suspend" ? "poweroff" : "suspend" }) } },
            { label: tr("Put to sleep"), hint: tr("Wake up with the remote, Home Assistant or the power button"),
              ok: function () { act("poweroff", { mode: "suspend" }); close() } },
            { label: tr("Restart the box"),
              hint: rebootUntil > 0 ? tr("Press OK again to restart") : undefined,
              ok: function () {
                  if (rebootUntil > 0) { act("reboot"); close() }
                  else { rebootUntil = 1; rebootReset.restart() }
              } },
            { label: tr("Shut down the box"), danger: true,
              hint: poweroffUntil > 0 ? tr("Press OK again to shut down") : undefined,
              ok: function () {
                  if (poweroffUntil > 0) { act("poweroff", { mode: "full" }); close() }
                  else { poweroffUntil = 1; poweroffReset.restart() }
              } },
        ].filter(function (r) { return r.visible !== false })   // Wi-Fi: only with a Wi-Fi card
    }
    // "2026-10-23 11:48:14" or "Mon 2026-10-26 05:07:37 CET" → "Fri 23 Oct at 11:48"
    function frDate(text) {
        var m = /(\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d)/.exec(text || "")
        if (!m) return text || ""
        var d = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5])
        return tr("{date} at {time}", { date: d.toLocaleDateString(Qt.locale(i18n.lang === "fr" ? "fr_FR" : "en_US"), "ddd d MMM"),
                                        time: m[4] + ":" + m[5] })
    }
    // One decimal, with the separator of the language ("{int}.{dec}")
    function dec1(x) { var p = x.toFixed(1).split("."); return tr("{int}.{dec}", { int: p[0], dec: p[1] }) }
    function bytes(n) { return n >= 1e9 ? tr("{n} GB", { n: dec1(n / 1e9) }) : tr("{n} MB", { n: Math.round(n / 1e6) }) }
    function bits(n) {
        return n === null || n === undefined ? "…" : n >= 1e6 ? dec1(n / 1e6) + " Mbit/s" : Math.round(n / 1e3) + " kbit/s"
    }
    function since(s) {
        var h = Math.floor(s / 3600), d = Math.floor(h / 24)
        return d ? tr("{d} d {h} h", { d: d, h: h % 24 }) : h ? h + " h " + (Math.floor(s / 60) % 60 < 10 ? "0" : "") + Math.floor(s / 60) % 60 : Math.floor(s / 60) + " min"
    }
    // Box status tiles: [title, value, detail, level (""|"warn"|"bad")]
    function healthTiles() {
        var h = health
        if (!h) return []
        var t = h.temps.cpu, p = h.player, ok = function (v) { return v === "active" ? "✓" : "✕" }
        var net = h.network
        return [
            [tr("Temperature"), t !== undefined ? t + " °C" : "–", h.temps.disk !== undefined ? tr("disk {n} °C", { n: h.temps.disk }) : "",
             t >= 85 ? "bad" : t >= 70 ? "warn" : ""],
            [tr("Processor"), h.cpu !== null ? Math.round(h.cpu) + " %" : "…", tr("load {load} · {n} cores", { load: dec1(h.load), n: h.cores }),
             h.cpu >= 85 ? "warn" : ""],
            [tr("Memory"), bytes(h.memory.total - h.memory.available), tr("of {total}", { total: bytes(h.memory.total) }), h.memory.available < 5e8 ? "warn" : ""],
            [tr("Disk"), tr("{n} free", { n: bytes(h.disk.free) }), tr("of {total}", { total: bytes(h.disk.total) }), h.disk.free < 5e9 ? "warn" : ""],
            [tr("Network"), "↓ " + bits(net.rx), "↑ " + bits(net.tx) + (net.speed > 0 ? " · " + tr("link {speed}", { speed: net.speed >= 1000 ? net.speed / 1000 + " Gbit/s" : net.speed + " Mbit/s" }) : ""), ""],
            [tr("Up for"), since(h.uptime), "MQTT " + ok(h.services.mqtt) + " · " + tr("YouTube tokens {ok}", { ok: ok(h.services.youtube_tokens) }),
             h.services.mqtt !== "active" || h.services.youtube_tokens !== "active" ? "warn" : ""],
            [tr("Playback"), (p.running === "qt" ? tr("Full version") : tr("Simplified version")) + (p.hwdec && p.hwdec !== "no" ? " · " + p.hwdec : p.size ? " · " + tr("CPU") : ""),
             p.size ? tr("{size} · {fps} fps · {dropped} dropped", { size: p.size.replace("x", " × "), fps: Math.round(p.fps || 0), dropped: p.dropped || 0 })
                    : tr("nothing playing"),
             p.size && (!p.hwdec || p.hwdec === "no") ? "warn" : ""],
        ]
    }
    // Power held 1 s: sleep, restart, shutdown (no second confirmation: the gesture is deliberate)
    function powerMenu() {
        powerOnly = true
        openModal("Box", [
            { label: tr("☾  Sleep"), ok: function () { act("poweroff", { mode: "suspend" }); close() } },
            { label: tr("↻  Restart"), ok: function () { act("reboot"); close() } },
            { label: tr("⏻  Shut down"), danger: true, ok: function () { act("poweroff", { mode: "full" }); close() } },
            { label: tr("Cancel"), ok: function () { close() } }])
    }
    readonly property var backdropNames: ({
        base: { none: "Nothing", aurora: "Blurry blobs", fluid: "Fluid", borealis: "Northern lights" },
        overlay: { none: "Nothing", silk: "Silk", stars: "Stars" },
        color: { violet: "Purple", blue: "Blue", green: "Green", sunset: "Sunset", pink: "Pink", ice: "Glacier" }
    })
    readonly property var bd: st.backdrop || ({ base: "aurora", overlay: "none", color: "violet" })
    // "Animated background", "Overlay", "Home screen colors" settings
    function stepBackdrop(key, d) {
        var ids = Object.keys(backdropNames[key])
        var next = ids[(Math.max(0, ids.indexOf(bd[key])) + d + ids.length) % ids.length]
        var change = {}
        change[key] = next
        st = Object.assign({}, st, { backdrop: Object.assign({}, bd, change) })   // on screen right away
        call("POST", "/api/backdrop", change, function () { refreshSoon.restart() })
    }
    // Neighboring color on the hue circle (animated background in the tab's colors); gray for neutral tabs
    function hueShift(c, dh, light) {
        if (c.hslHue < 0) return Qt.darker(c, 2.5)
        return Qt.hsla((c.hslHue + dh + 1) % 1, c.hslSaturation, c.hslLightness * light, 1)
    }
    function openModal(title, items) { modal = { title: title, items: items }; modalSel = 0 }
    function chooseVideo(item) {
        if (Fmt.resumable(item.position, item.seconds, item.finished))
            openModal(item.title, [
                { label: tr("▶  Resume at {time}", { time: Fmt.clock(item.position) }), ok: function () { play(item.url, false, item) } },
                { label: tr("↺  From the beginning"), ok: function () { play(item.url, true, item) } }])
        else
            play(item.url, true, item)
    }
    function subtitle() {
        var live = st.live || {}
        switch (tabId) {
        case "live":
            var n = (st.streamers || []).filter(function (s) { return !!live[s] }).length
            return n === 0 ? tr("No streamer from the list is live") : n === 1 ? tr("1 streamer live") : tr("{n} streamers live", { n: n })
        case "follows":
            if (!follows) return tr("Loading…")
            if (follows.error) return tr("Twitch unreachable for now")
            if (!follows.configured) return tr("Your followed channels on Twitch")
            if (!follows.authorized) return tr("Allow the box to read your followed channels (read-only)")
            return (follows.live.length ? tr("{n} live", { n: follows.live.length }) : tr("Nobody live")) + "  ·  "
                + tr("{n} followed channels", { n: followList().length })
        case "replays":
            var d = replays[rpLogin]
            return d === "loading" ? tr("{login} · loading…", { login: rpLogin }) : d === false ? tr("Twitch unreachable for now")
                : (d && replayRows().length === 1) ? tr("{login}: nothing this week", { login: rpLogin })
                : tr("{login} · replays and clips of the week", { login: rpLogin })
        case "history":
            return history === null ? tr("Loading…") : history.length === 0 ? tr("Videos played on the TV will show up here")
                : (history.length === 1 ? tr("1 video") : tr("{n} videos", { n: history.length })) + " · " + tr("OK to resume or remove")
        case "youtube":
            if (!yt) return tr("Loading…")
            var nc = yt.channels.length
            if (yt.subs && yt.subs.authorized)
                return !nc ? tr("Your subscriptions · latest videos")
                    : tr(nc === 1 ? "Your subscriptions and 1 channel · latest videos" : "Your subscriptions and {n} channels · latest videos", { n: nc })
            return nc ? tr(nc === 1 ? "1 channel · latest videos" : "{n} channels · latest videos", { n: nc })
                : tr("Search for a video, or add channels from the companion app")
        case "jellyfin":
            if (!jf) return tr("Loading…")
            if (jf.error) return tr("Jellyfin unreachable for now")
            if (!jf.configured) return tr("Your Jellyfin library")
            return tr("{server} · progress follows on all your devices", { server: jf.server })
        case "settings": return tr("◀ ▶ to change a value")
        }
        return ""
    }

    // Displayed tab: data loaded on the first visit
    onTabChanged: {
        stopPreview()
        tabEnter.restart()
        loadTab(tabs[tab].id)   // tabs[tab] and not tabId: the tabId binding is not recomputed yet here
    }
    // Live preview: on the Live tab, the card of a live streamer grows and plays its live, muted (LiveTab.grow →
    // startPreview with "twitch:<login>": streamlink and player "cardPreview" of ui.py, drawn by menu/CardPreview.qml)
    property var previewRect: null   // where the video goes, in menu coordinates; null: no preview
    property string previewFor: ""   // "twitch:<login>" being previewed
    function startPreview(url, r) {   // r: rect in menu coordinates
        stopPreview()
        previewFor = url
        previewRect = { x: r.x, y: r.y, width: r.width, height: r.height }
        cardPreview.play(url, 0)
    }
    function stopPreview() {
        if (!previewFor) return
        previewFor = ""
        previewRect = null
        cardPreview.stop()
    }
    function loadBt(cb) { call("GET", "/api/bluetooth", undefined, function (d) { if (d) { bt = d; if (cb) cb(d) } }) }
    // "Remotes and controllers" dialog: paired devices (OK: unpair), "Pair a device"
    function btMenu() {
        btPhase = ""
        loadBt(function (d) {
            var items = d.paired.map(function (p) {
                return { label: p.name + (p.connected ? "  ·  " + tr("connected") : ""), ok: function () {
                    openModal(tr("Unpair {name}?", { name: p.name }), [
                        { label: tr("✕  Unpair"), danger: true, ok: function () {
                            call("POST", "/api/bluetooth", { action: "remove", mac: p.mac }, function () { btMenu() }) } },
                        { label: tr("Cancel"), ok: function () { btMenu() } }])
                } }
            })
            items.push({ label: tr("+  Pair a device"), ok: btScan })
            openModal(d.paired.length ? tr("Remotes and controllers") : tr("No paired device"), items)
            if (d.message) modal = Object.assign({}, modal, { title: d.message })
        })
    }
    // Search: the dialog fills up for 20 s (remotes and controllers first); OK on a device pairs it
    function btScan() {
        btPhase = "scan"
        call("POST", "/api/bluetooth", { action: "scan" })
        openModal(tr("Searching… put the remote in pairing mode"), [{ label: tr("Cancel"), ok: function () { btPhase = "" } }])
    }
    function btRefresh() {
        loadBt(function (d) {
            if (btPhase === "scan") {
                var items = d.found.map(function (f) {
                    return { label: f.name, ok: function () {
                        btPhase = "pair"
                        call("POST", "/api/bluetooth", { action: "pair", mac: f.mac })
                        openModal(tr("Pairing {name}…", { name: f.name }), [{ label: tr("Close"), ok: function () { btPhase = "" } }])
                    } }
                })
                if (!d.scanning) items.push({ label: tr("↻  Search again"), ok: btScan })
                items.push({ label: tr("Cancel"), ok: function () { btPhase = "" } })
                var title = d.scanning ? tr("Searching… put the remote in pairing mode")
                          : d.found.length ? tr("Devices found") : tr("No device found")
                var sel = modalSel
                modal = { title: title, items: items }
                modalSel = Math.min(sel, items.length - 1)
            } else if (btPhase === "pair" && !d.busy) {
                btPhase = ""
                openModal(d.message || tr("Pairing finished"), [{ label: "OK", ok: btMenu }])
            }
        })
    }
    Timer { interval: 2000; repeat: true; running: menu.btPhase !== "" && !!menu.modal; onTriggered: menu.btRefresh() }
    // "Backup and restore" dialog: per plugged-in USB stick, "Back up" then its latest backups
    // (OK: restore, after confirmation); reloaded every 2 s (stick plugged in, backup finished)
    function backupMenu(again) {
        call("GET", "/api/backup", undefined, function (d) {
            if (!d || (again && !(modal && modal.kind === "backup"))) return   // closed, or confirmation opened in the meantime
            var items = []
            if (!d.busy) d.usb.forEach(function (u) {
                items.push({ label: tr("↓  Back up to {name}", { name: u.name }), ok: function () {
                    call("POST", "/api/backup", { action: "save_usb", path: u.path }, function () { backupMenu() }) } })
                u.backups.forEach(function (b) {
                    items.push({ label: tr("↺  Restore the one from {date}", { date: frDate(b.date) }), ok: function () {
                        openModal(tr("Replace the settings with those from {date}? The box restarts afterwards", { date: frDate(b.date) }), [
                            { label: tr("↺  Restore and restart"), danger: true, ok: function () {
                                call("POST", "/api/backup", { action: "restore_usb", path: u.path, name: b.name }, function () { backupMenu() }) } },
                            { label: tr("Cancel"), ok: function () { backupMenu() } }])
                    } })
                })
            })
            if (d.busy !== "reboot") items.push({ label: tr("Close"), ok: function () {} })
            var title = d.message || (d.usb.length ? tr("Backup and restore")
                                                    : tr("Plug in a USB stick to back up"))
            var same = modal && modal.kind === "backup"
            var sel = modalSel
            modal = { title: title, items: items, kind: "backup" }
            modalSel = same ? Math.min(sel, items.length - 1) : 0
        })
    }
    Timer { interval: 2000; repeat: true; running: !!menu.modal && menu.modal.kind === "backup"; onTriggered: menu.backupMenu(true) }
    // "Install on this PC" dialog: internal disks (OK: confirmation, everything is erased), then progress reloaded
    // every 2 s, and at the end "remove the stick, restart"
    function installMenu(again) {
        call("GET", "/api/install", undefined, function (d) {
            if (!d || (again && !(modal && modal.kind === "install"))) return
            install = d
            var p = d.progress, title, items = []
            if (p && p.state === "running") {
                title = tr("Installing… {percent} %  ·  {step}", { percent: p.percent, step: p.step })
                items.push({ label: tr("Hide (the installation continues)"), ok: function () {} })
            } else if (p && p.state === "done") {
                title = tr("Installed! Remove the USB stick, then restart")
                items.push({ label: tr("↻  Restart"), ok: function () { act("reboot"); close() } })
                items.push({ label: tr("Later"), ok: function () {} })
            } else {
                title = p && p.state === "error" ? tr("Failed: {error}", { error: p.error }) : d.disks.length ? tr("Install on which disk?")
                      : d.raid_mode ? tr("Disk hidden by the BIOS RAID mode: set \"SATA Operation\" to AHCI, then try again")
                      : tr("No internal disk of 16 GB or more")
                d.disks.forEach(function (k) {
                    items.push({ label: k.label + (k.data ? "  ·  " + tr("contains: {data}", { data: k.data }) : ""), ok: function () {
                        openModal(tr("Erase everything on {disk} and install the box on it?", { disk: k.label }), [
                            { label: tr("Yes, erase and install"), danger: true, ok: function () {
                                call("POST", "/api/install", { disk: k.name }, function () { installMenu() }) } },
                            { label: tr("Cancel"), ok: function () { installMenu() } }])
                    } })
                })
                items.push({ label: tr("Close"), ok: function () {} })
            }
            var same = modal && modal.kind === "install"
            var sel = modalSel
            modal = { title: title, items: items, kind: "install" }
            modalSel = same ? Math.min(sel, items.length - 1) : 0
        })
    }
    Timer { interval: 2000; repeat: true; running: !!menu.modal && menu.modal.kind === "install"; onTriggered: menu.installMenu(true) }
    function loadSsh() {
        call("GET", "/api/ssh", undefined, function (d) { if (d) ssh = d })
        call("GET", "/api/dev", undefined, function (d) { if (d) dev = d })
    }
    function loadAudio() { call("GET", "/api/audio", undefined, function (d) { if (d && d.outputs) audioOut = d }) }
    function loadTab(id) {
        if (id === "settings") loadAudio()
        if (id === "system") { loadBt(); loadYtAccount(); loadSsh(); call("GET", "/api/install", undefined, function (d) { if (d) install = d }) }
        if (id === "follows" && follows === null) loadFollows()
        if (id === "history" && history === null) loadHistory()
        if (id === "youtube") loadYoutube()   // previous rows shown in the meantime
        if (id === "jellyfin" && jf === null) loadJellyfin()
        if (id === "replays") {
            if (!rpLogin) rpLogin = st.channel || (st.streamers || [])[0] || ""
            loadReplays(rpLogin)
        }
    }

    // Keys

    function grid(sel, count, cols, k) {   // move in a grid: new position, or -1 to exit on the left
        var col = sel % cols
        if (k === "left") return col === 0 ? -1 : sel - 1
        if (k === "right") return col < cols - 1 && sel < count - 1 ? sel + 1 : sel
        if (k === "up") return sel >= cols ? sel - cols : sel
        if (k === "down") return sel + cols < count ? sel + cols : (Math.floor(sel / cols) < Math.floor((count - 1) / cols) ? count - 1 : sel)
        return sel
    }
    property int keyCount: 0   // keys received while open (LiveTab: the banner preview starts again after a key)
    function key(k) {
        keyCount++
        idleClose.restart()
        startFocus = false
        stopPreview()   // any key: the focus moves, a dialog opens, or the video starts for real
        if (k === "home") return close()
        if (k === "homescreen") { act("home"); return close() }
        if (k === "corner") return act("corner")
        if (kbOpen) return keyKeyboard(k)
        if (modal) {
            if (k === "up" || k === "down") modalSel = Math.max(0, Math.min(modal.items.length - 1, modalSel + (k === "down" ? 1 : -1)))
            else if (k === "ok") { var it = modal.items[modalSel]; modal = null; it.ok() }
            else if (k === "back" || k === "left") { modal = null; if (powerOnly) close() }
            return
        }
        if (ytAuth) { if (k === "back" || k === "left" || k === "ok") ytAuth = null; return }
        if (area === "rail") {
            if (railHome) {   // "Home screen": global, above the tabs
                if (k === "down") railHome = false
                else if (k === "ok") { act("home"); close() }
                else if (k === "right") { railHome = false; enterContent() }
                else if (k === "back" && st.mode !== "home") close()
                return
            }
            if (k === "up" && tab === 0) railHome = true
            else if (k === "up" || k === "down") tab = Math.max(0, Math.min(tabs.length - 1, tab + (k === "down" ? 1 : -1)))
            else if (k === "right" || k === "ok") enterContent()
            else if (k === "back" && st.mode !== "home") close()   // nothing playing: the menu stays the main page
            return
        }
        if (k === "back") return toRail()   // Back: to the tabs, then (from the rail) closes the menu
        switch (tabId) {
        case "live": return keyLive(k)
        case "follows": return keyFollows(k)
        case "replays": return keyReplays(k)
        case "youtube": case "jellyfin": return keyMedia(k)
        case "history": return keyHistory(k)
        case "settings": return keyRows(k, settingsRows())
        case "system": return keyRows(k, systemRows())
        }
    }
    function toRail() { area = "rail"; railHome = false; shortcut = -1; pendingDisplay = ""; pendingPlayer = "" }
    // Something to focus in the tab (data still loading counts as yes: checkArea goes back to the rail if it is empty)
    function canEnter(id) {
        var list = st.streamers
        if (id === "live") return !list || list.length > 0 || shortcuts().length > 0
        if (id === "replays") return !list || list.length > 0
        if (id === "follows") return !follows || !!follows.configured
        if (id === "history") return !history || history.length > 0
        return true
    }
    // Nothing to focus in the content: the focus goes back to the rail (Live without streamers: the shortcuts)
    function checkArea() {
        if (area !== "content") return
        var id = tabs[tab].id
        if (!canEnter(id)) return toRail()
        if (id === "live" && st.streamers && !st.streamers.length && shortcut < 0) shortcut = 0
    }
    function enterContent() {
        var id = tabs[tab].id   // and not tabId: right after a tab change, its binding may not be recomputed yet
        if (!canEnter(id)) return
        if (id === "youtube" || id === "jellyfin") { area = "content"; setRow(0); return }
        area = "content"
        checkArea()
        if (id === "replays") { rpRow = 0; rpSel = [Math.max(0, (st.streamers || []).indexOf(rpLogin)), rpSel[1], rpSel[2]] }
    }
    function keyLive(k) {
        var list = st.streamers || []
        if (shortcut >= 0) {
            var sc = shortcuts()
            shortcut = Math.min(shortcut, sc.length - 1)
            if (k === "left") { if (shortcut === 0) { area = "rail"; shortcut = -1 } else shortcut-- }
            else if (k === "right") shortcut = Math.min(sc.length - 1, shortcut + 1)
            else if (k === "down" && list.length) shortcut = -1
            else if (k === "ok") sc[shortcut].ok()
            return
        }
        if (k === "ok") { if (list[liveSel]) { act("channel", { name: list[liveSel] }); close() } return }
        if (k === "menu") { if (list[liveSel]) streamerOptions(list[liveSel], false, !!(st.live || {})[list[liveSel]]); return }
        if (k === "up" && liveSel < 4) { if (shortcuts().length) shortcut = 0; return }
        var n = grid(liveSel, list.length, 4, k)
        if (n < 0) area = "rail"; else liveSel = n
    }
    function keyFollows(k) {
        if (!follows.authorized) {
            var p = follows.pending
            if (k === "left") area = "rail"
            else if (k === "ok" && !(p && p.user_code && !p.error)) call("POST", "/api/follows_login", {}, function () { loadFollows() })
            return
        }
        var list = followList()
        if ((k === "ok" || k === "menu") && list[followSel]) {
            var name = list[followSel].login
            if (k === "ok" && inList(name)) { act("channel", { name: name }); close(); return }
            streamerOptions(name, !inList(name), list[followSel].viewers !== undefined && list[followSel].viewers !== null)
            return
        }
        var n = grid(followSel, list.length, 4, k)
        if (n < 0) area = "rail"; else followSel = n
    }
    function keyReplays(k) {
        var rows = replayRows()
        rpRow = Math.min(rpRow, rows.length - 1)
        var row = rows[rpRow], sel = rpSel[rpRow] || 0
        var s = rpSel.slice()
        if (k === "up") rpRow = Math.max(0, rpRow - 1)
        else if (k === "down") rpRow = Math.min(rows.length - 1, rpRow + 1)
        else if (k === "left") { if (sel === 0) area = "rail"; else { s[rpRow] = sel - 1; rpSel = s } }
        else if (k === "right") { s[rpRow] = Math.min(row.items.length - 1, sel + 1); rpSel = s }
        else if (k === "ok") {
            if (row.kind === "chips") {
                var name = row.items[sel]
                if (name && name !== rpLogin) { rpLogin = name; rpSel = [sel, 0, 0]; loadReplays(name) }
            } else if (row.items[sel]) chooseVideo(row.items[sel])
        }
    }
    function setRow(v) { if (jfTab) jfRow = v; else ytRow = v }
    function setMediaSel(s) { if (jfTab) jfSel = s; else ytSel = s }   // (setSel is the chosen row of Settings)
    function keyMedia(k) {
        var rows = mediaRows()
        var r = Math.min(mRow, rows.length - 1)
        var row = rows[r]
        if (row.kind === "search") {
            if (k === "ok") { kbOpen = true; kbRow = 0; kbCol = 0 }
            else if (k === "down" && rows.length > 1) setRow(1)
            else if (k === "left") area = "rail"
            return
        }
        var sel = Math.min(mSel[row.key] || 0, Math.max(0, row.items.length - 1)), s = Object.assign({}, mSel)
        if (k === "up") setRow(r - 1)
        else if (k === "down") setRow(Math.min(rows.length - 1, r + 1))
        else if (k === "left") { if (sel === 0) area = "rail"; else { s[row.key] = sel - 1; setMediaSel(s) } }
        else if (k === "right") { s[row.key] = Math.min(row.items.length - 1, sel + 1); setMediaSel(s) }
        else if (k === "menu" && row.kind === "subs" && row.items[sel]) ytSubOptions(row.items[sel])
        else if (k === "ok" && row.items[sel]) {
            if (row.kind === "chans") ytChannelMenu(row.items[sel])
            else if (row.kind === "connect") ytConnect(false)
            else if (jfTab) jfChoose(row.items[sel])
            else chooseVideo(row.items[sel])
        }
    }
    function keyKeyboard(k) {
        var rows = kbKeys
        if (k === "up") { kbRow = Math.max(0, kbRow - 1); kbCol = Math.min(kbCol, rows[kbRow].length - 1) }
        else if (k === "down") { kbRow = Math.min(rows.length - 1, kbRow + 1); kbCol = Math.min(kbCol, rows[kbRow].length - 1) }
        else if (k === "left") kbCol = Math.max(0, kbCol - 1)
        else if (k === "right") kbCol = Math.min(rows[kbRow].length - 1, kbCol + 1)
        else if (k === "back") kbOpen = false
        else if (k === "ok") {
            var key = rows[kbRow][kbCol]
            if (key === "Space") kbText += " "
            else if (key === "Delete") kbText = kbText.slice(0, -1)
            else if (key === "Clear all") kbText = ""
            else if (key === "Search") { if (kbText.trim()) { kbOpen = false; if (jfTab) jfSearch(kbText); else ytSearch(kbText) } }
            else if (kbText.length < 80) kbText += key
        }
    }
    function keyHistory(k) {
        var list = history || []
        if (k === "ok" && list[histSel]) {
            var e = list[histSel], items = []
            if (Fmt.resumable(e.position, e.duration, e.finished)) {
                items.push({ label: tr("▶  Resume at {time}", { time: Fmt.clock(e.position) }), ok: function () { play(e.url) } })
                items.push({ label: tr("↺  From the beginning"), ok: function () { play(e.url, true) } })
            } else items.push({ label: tr(e.finished ? "↺  Watch again" : "▶  Play"), ok: function () { play(e.url, true) } })
            items.push({ label: tr("✕  Remove from history"), danger: true, ok: function () {
                call("POST", "/api/history", { action: "remove", key: e.key }, function () { loadHistory() })
                var h = history.slice(); h.splice(histSel, 1); history = h
                histSel = Math.max(0, Math.min(histSel, h.length - 1))
                if (!h.length) area = "rail"
            } })
            openModal(e.title, items)
            return
        }
        var n = grid(histSel, list.length, 3, k)
        if (n < 0) area = "rail"; else histSel = n
    }
    function keyRows(k, rows) {
        var sel = selectable(rows)
        var cur = tabId === "settings" ? setSel : sysSel
        var row = rows[sel[cur]]
        var set = function (v) { if (tabId === "settings") setSel = v; else sysSel = v; pendingDisplay = ""; pendingPlayer = "" }
        if (k === "up") set(Math.max(0, cur - 1))
        else if (k === "down") set(Math.min(sel.length - 1, cur + 1))
        else if ((k === "left" || k === "right") && row && row.step) row.step(k === "right" ? 1 : -1)
        else if (k === "left") area = "rail"
        else if (k === "ok" && row) { if (row.ok) row.ok(); else if (row.step) row.step(1) }
    }

    // Drawing: one component per tab and per dialog (qml/menu/), all reading this object (menu: data, focus, functions)

    Item {   // the whole menu; hidden when only the "Box" dialog (power held) is shown
        anchors.fill: parent
        visible: !menu.powerOnly
        Rectangle {   // veil over the video; opaque without video, to hide the ambient screen
            anchors.fill: parent
            color: menu.pal.veil
            opacity: box.videoActive ? 0.89 : 1
            Behavior on color { ColorAnimation { duration: 400 } }
        }
        // Without video behind (the menu is then the main page): animated background in the tab's colors, softened
        Backdrop {
            anchors.fill: parent
            visible: opacity > 0
            opacity: box.videoActive ? 0 : 1
            Behavior on opacity { NumberAnimation { duration: 500 } }
            running: menu.isOpen && !box.videoActive
            base: menu.bd.base
            overlay: menu.bd.overlay
            overlayOpacity: 0.6
            bg: menu.pal.veil
            c1: menu.accent
            c2: menu.hueShift(menu.accent, 0.10, 0.8)
            c3: menu.hueShift(menu.accent, -0.12, 0.9)
        }
        Rectangle { anchors.fill: parent; color: menu.pal.veil; opacity: box.videoActive ? 0 : 0.30 }
        Rail { menu: menu }   // (menu: the id of this object, looked up before the property of the same name)
        Header { menu: menu }

        // Tab content: slides in on each change
        Item {
            id: content
            x: Layout.contentX; y: 0; width: Layout.contentW; height: parent.height
            ParallelAnimation {
                id: tabEnter
                NumberAnimation { target: content; property: "x"; from: Layout.contentX + 40; to: Layout.contentX; duration: 260; easing.type: Easing.OutCubic }
                NumberAnimation { target: content; property: "opacity"; from: 0; to: 1; duration: 220 }
            }
            LiveTab { menu: menu }
            FollowsTab { menu: menu }
            ReplaysTab { menu: menu }
            MediaTab { menu: menu }   // YouTube and Jellyfin
            HistoryTab { menu: menu }
            RowsTab { menu: menu; which: "settings" }
            RowsTab { menu: menu; which: "system" }
            SystemStatus { menu: menu }
        }
        CardPreview { menu: menu }
    }
    SearchKeyboard { menu: menu }
    YtAuthDialog { menu: menu }
    ActionDialog { menu: menu }
}
