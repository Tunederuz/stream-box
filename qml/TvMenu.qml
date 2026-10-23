// Stream Box : grand menu de la TV en QML (rendu par la puce graphique), à la place de tv_menu.lua quand le lecteur est
// l'appli Qt (ui.py). Mêmes onglets et mêmes actions : tout passe par l'API de remote.py, comme la page web.
// Les touches arrivent de ui.py (box.keyPressed) déjà traduites : up, down, left, right, ok, back, home (bouton Menu,
// ferme), homescreen (WWW), corner (Play), menu (≡ : options de la carte choisie, dont le second stream). Coordonnées
// en 1920x1080, mises à l'échelle par ui.qml. Second stream : objet « pip » de ui.py.
import QtQuick
import "fmt.js" as Fmt

Item {
    id: menu
    width: 1920
    height: 1080
    property bool isOpen: false
    opacity: isOpen ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }

    readonly property string api: "http://127.0.0.1:8080"
    readonly property var tabs: [
        { id: "live", label: "En direct" }, { id: "follows", label: "Suivis" },
        { id: "replays", label: "Rediffusions" }, { id: "youtube", label: "YouTube" },
        { id: "jellyfin", label: "Jellyfin" },
        { id: "history", label: "Historique" },
        { id: "settings", label: "Réglages" }, { id: "system", label: "Système" }]
    readonly property var corners: ({ tl: "↖ haut gauche", tr: "↗ haut droite", br: "↘ bas droite", bl: "↙ bas gauche" })
    readonly property var cornerOrder: ["tl", "tr", "br", "bl"]
    readonly property var qrModes: [["always", "Toujours"], ["timed", "30 secondes"], ["never", "Jamais"]]
    readonly property var kinds: ({ youtube: "YouTube", "twitch-vod": "Rediffusion Twitch", "twitch-clip": "Clip Twitch", link: "Lien", jellyfin: "Jellyfin" })

    // Données (relues à l'ouverture ; réaffectées en entier pour que les liaisons suivent)
    property var st: ({})
    property var follows: null
    property var replays: ({})
    property var history: null
    property var display: null
    property var account: null
    property var followsQr: null
    property var health: null                // /api/health, relu toutes les 5 s sur l'onglet Système
    // YouTube : chaînes de la liste (/api/youtube), résultats de recherche, rangée et choix par rangée
    property var yt: null
    // Couleurs selon l'onglet : violet pour Twitch (direct, suivis, rediffusions), rouge pour YouTube, neutre
    // (anthracite, halo blanc) pour ce qui n'appartient à aucun service (historique, réglages, système), bleu Jellyfin
    readonly property string theme: tabId === "youtube" || tabId === "jellyfin" ? tabId
        : ["live", "follows", "replays"].indexOf(tabId) >= 0 ? "twitch" : "neutral"
    readonly property var pal: theme === "youtube"
        ? { accent: "#ff0033", veil: "#180407", rail: "#1a0709", glow: 0.22, sheet: "#261216", key: "#3a1f24",
            surface: "#33171c", surfaceFocus: "#4a2027", label: "#c9a3aa" }
        : theme === "jellyfin"
        ? { accent: "#00a4dc", veil: "#030f17", rail: "#06131c", glow: 0.20, sheet: "#0f202c", key: "#173244",
            surface: "#12293a", surfaceFocus: "#1b3c54", label: "#9cc3d8" }
        : theme === "twitch"
        ? { accent: "#9146ff", veil: "#0a0612", rail: "#100b17", glow: 0.10, sheet: "#21182c", key: "#33283f",
            surface: "#2a2034", surfaceFocus: "#3a2c4e", label: "#a99fc0" }
        : { accent: "#e8e8ee", veil: "#0b0b0d", rail: "#121214", glow: 0.05, sheet: "#1e1e22", key: "#2f2f35",
            surface: "#232327", surfaceFocus: "#35353c", label: "#a3a3ad" }
    readonly property bool ytTheme: theme === "youtube"
    readonly property color accent: pal.accent
    property var ytResults: null             // { query, results, channels } ou null
    property var ytPreview: null             // chaîne trouvée ouverte : { id, name, avatar, followers, videos, saved }
    property bool ytSearching: false
    property int ytRow: 0                    // 0 : ligne de recherche, puis résultats (s'il y en a) et chaînes
    property var ytSel: ({})
    // Jellyfin : accueil (/api/jellyfin), recherche, épisodes d'une série ouverte, rangée et choix par rangée
    property var jf: null
    property var jfResults: null             // { query, results } ou null
    property var jfPreview: null             // série ouverte : { id, name, episodes, first }
    property bool jfSearching: false
    property int jfRow: 0
    property var jfSel: ({})
    // Onglets à rangées (YouTube, Jellyfin) : même page, même clavier, état propre à chacun
    readonly property bool jfTab: tabId === "jellyfin"
    readonly property int mRow: jfTab ? jfRow : ytRow
    readonly property var mSel: jfTab ? jfSel : ytSel
    readonly property bool mSearching: jfTab ? jfSearching : ytSearching
    readonly property var mResults: jfTab ? jfResults : ytResults
    // Clavier à l'écran (recherche) : texte, ligne et colonne choisies
    property bool kbOpen: false
    property string kbText: ""
    property int kbRow: 0
    property int kbCol: 0
    readonly property var kbKeys: [
        "abcdefghij".split(""), "klmnopqrst".split(""), "uvwxyz-'.?".split(""), "0123456789".split(""),
        "éèàçùêô".split("").concat(["Espace"]), ["Effacer", "Tout effacer", "Rechercher"]]
    readonly property var ambient: { try { return JSON.parse(box.ambient || "{}") } catch (e) { return {} } }

    // Focus
    property int tab: 0
    readonly property string tabId: tabs[tab].id
    property string area: "content"          // rail ou content
    property int shortcut: -1                // En direct : raccourci choisi au-dessus de la grille, -1 = grille
    property int liveSel: 0
    property int followSel: 0
    property int histSel: 0
    property int setSel: 0                   // index dans settingsRows (lignes sélectionnables seulement)
    property int sysSel: 0
    property int rpRow: 0                    // 0 puces, 1 rediffusions, 2 clips (s'ils existent)
    property var rpSel: [0, 0, 0]
    property string rpLogin: ""
    property string pendingDisplay: ""
    property string pendingPlayer: ""        // lecteur choisi aux flèches, appliqué par OK (le lecteur redémarre)
    property real poweroffUntil: 0
    property var modal: null                 // { title, items: [{ label, danger, ok }] }
    property int modalSel: 0
    property date now: new Date()
    property bool startFocus: false          // à l'ouverture : focus à recaler sur le streamer regardé

    // API de remote.py

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
    function refresh() {
        call("GET", "/api/state", undefined, function (d) {
            if (!d || !d.streamers) return
            st = d
            if (startFocus) liveSel = Math.max(0, d.streamers.indexOf(d.channel))
        })
    }
    function act(name, body) { call("POST", "/api/" + name, body || {}, function () { refreshSoon.restart() }) }
    function loadFollows() {
        call("GET", "/api/follows", undefined, function (d) {
            follows = d || { error: true }
            var p = follows.pending
            if (p && p.verification_uri && !p.error) {
                if (!followsQr || followsQr.text !== p.verification_uri)
                    call("GET", "/api/qr?text=" + encodeURIComponent(p.verification_uri), undefined, function (q) {
                        followsQr = q ? { text: p.verification_uri, rows: q.rows } : null
                    })
                followsPoll.restart()   // en attente du code tapé sur twitch.tv/activate
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
        call("GET", "/api/youtube", undefined, function (d) { yt = d && d.channels ? d : { channels: [] } })
    }
    function ytSearch(q) {
        q = q.trim()
        if (!q) return
        ytResults = { query: q, results: [], channels: [] }   // avant ytSearching : le texte de la ligne de recherche lit query
        ytSearching = true
        ytPreview = null
        call("GET", "/api/youtube_search?q=" + encodeURIComponent(q), undefined, function (d) {
            ytSearching = false
            ytResults = { query: q, results: d && d.results ? d.results : [], channels: d && d.channels ? d.channels : [], error: !d }
            ytRow = 1; var s = Object.assign({}, ytSel); s["search"] = 0; ytSel = s
        })
    }
    // Rangées de l'onglet YouTube : recherche, résultats, une par chaîne
    function ytRows() {
        var rows = [{ kind: "search" }]
        if (ytResults && ytResults.channels.length)
            rows.push({ kind: "chans", key: "chans", title: "Chaînes", items: ytResults.channels })
        if (ytPreview)
            rows.push({ kind: "preview", key: "preview", title: ytPreview.name + " · dernières vidéos", avatar: ytPreview.avatar,
                        items: ytPreview.videos || [], loading: ytPreview.videos === null })
        if (ytResults) rows.push({ kind: "results", key: "search", title: "Résultats pour « " + ytResults.query + " »", items: ytResults.results })
        var chans = yt ? yt.channels : []
        for (var i = 0; i < chans.length; i++)
            rows.push({ kind: "channel", key: chans[i].id, title: chans[i].name, avatar: chans[i].avatar, items: chans[i].videos || [] })
        return rows
    }
    // Chaîne trouvée par la recherche : voir ses vidéos (rangée juste sous les chaînes), l'ajouter ou la retirer
    function ytChannelMenu(c) {
        openModal(c.name + (c.followers ? " · " + Fmt.big(c.followers) + " abonnés" : ""), [
            { label: "▶  Voir ses dernières vidéos", ok: function () { ytOpenChannel(c) } },
            { label: c.saved ? "✕  Retirer de mes chaînes" : "+  Ajouter à mes chaînes", ok: function () { ytToggleSaved(c) } }])
    }
    function ytOpenChannel(c) {
        ytPreview = { id: c.id, name: c.name, avatar: c.avatar, videos: null }
        var s = Object.assign({}, ytSel); s["preview"] = 0; ytSel = s
        ytRow = 2   // recherche, chaînes, puis cette rangée
        call("GET", "/api/youtube_channel?id=" + encodeURIComponent(c.id), undefined, function (d) {
            if (ytPreview && ytPreview.id === c.id) ytPreview = Object.assign({}, ytPreview, { videos: d ? d.videos : [] })
        })
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
        return days <= 0 ? "aujourd'hui" : days === 1 ? "hier" : days < 7 ? "il y a " + days + " j"
            : days < 31 ? "il y a " + Math.floor(days / 7) + " sem." : new Date(iso).toLocaleDateString(Qt.locale("fr_FR"), "d MMM")
    }
    function loadJellyfin() {
        call("GET", "/api/jellyfin", undefined, function (d) { jf = d || { error: true } })
    }
    function jfSearch(q) {
        q = q.trim()
        if (!q) return
        jfResults = { query: q, results: [] }   // avant jfSearching : le texte de la ligne de recherche lit query
        jfSearching = true
        jfPreview = null
        call("GET", "/api/jellyfin_search?q=" + encodeURIComponent(q), undefined, function (d) {
            jfSearching = false
            jfResults = { query: q, results: d && d.results ? d.results : [], error: !d }
            jfRow = 1; var s = Object.assign({}, jfSel); s["search"] = 0; jfSel = s
        })
    }
    // Rangées de l'onglet Jellyfin : recherche, série ouverte, résultats, reprendre, prochains épisodes, ajouts récents
    function jfRows() {
        var rows = [{ kind: "search" }]
        if (jfPreview)
            rows.push({ kind: "preview", key: "preview", title: jfPreview.name + " · épisodes", items: jfPreview.episodes || [],
                        loading: jfPreview.episodes === null })
        if (jfResults) rows.push({ kind: "results", key: "search", title: "Résultats pour « " + jfResults.query + " »", items: jfResults.results })
        if (jf && jf.configured) {
            if (jf.resume.length) rows.push({ kind: "jf", key: "resume", title: "Reprendre", items: jf.resume })
            if (jf.nextup.length) rows.push({ kind: "jf", key: "nextup", title: "Prochains épisodes", items: jf.nextup })
            for (var i = 0; i < jf.libraries.length; i++)
                rows.push({ kind: "jf", key: "lib:" + jf.libraries[i].id, title: jf.libraries[i].name + " · ajouts récents", items: jf.libraries[i].items })
        }
        return rows
    }
    function mediaRows() { return jfTab ? jfRows() : ytRows() }
    // Série (ou saison) choisie : ses épisodes dans une rangée juste sous la recherche, focus sur le premier pas vu
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
            items.push({ label: "▶  Reprendre à " + Fmt.clock(item.position), ok: function () { jfPlay(item) } })
            items.push({ label: "↺  Depuis le début", ok: function () { jfPlay(item, true) } })
        } else items.push({ label: item.finished ? "↺  Revoir" : "▶  Lire", ok: function () { jfPlay(item, true) } })
        if (item.type === "Episode" && item.series && !(jfPreview && jfPreview.id === item.series))
            items.push({ label: "☰  Tous les épisodes", ok: function () { jfOpenSeries({ series: item.series, title: item.title }) } })
        openModal(name, items)
    }
    // Ligne d'infos d'une carte des onglets à rangées
    function hm(t) {
        var h = Math.floor(t / 3600), m = Math.floor(t / 60) % 60
        return h > 0 ? h + " h " + (m < 10 ? "0" : "") + m : m + " min"
    }
    function cardMeta(row, it) {
        var parts
        if (jfTab)
            parts = it.type === "Series" ? [it.unplayed ? it.unplayed + " à voir" : "Série", it.year]
                : it.episode ? [it.episode] : [it.year, it.seconds ? hm(it.seconds) : ""]
        else if (row.kind === "results")
            parts = [it.channel, it.seconds ? Fmt.clock(it.seconds) : "", it.views ? Fmt.big(it.views) + " vues" : ""]
        else
            parts = [ago(it.date), it.views ? Fmt.big(it.views) + " vues" : ""]
        return parts.filter(function (t) { return !!t }).join(" · ") + (it.finished ? " · vu" : "")
    }
    function searchLabel() {
        var r = mResults
        return mSearching ? "Recherche de « " + r.query + " »…" : r ? "Nouvelle recherche  (« " + r.query + " »)"
            : jfTab ? "Rechercher dans Jellyfin" : "Rechercher sur YouTube"
    }
    function loadHistory() { call("GET", "/api/history", undefined, function (d) { history = d || [] }) }
    function play(url, fromStart) {
        call("POST", "/api/play", { url: url, from_start: !!fromStart }, function () { refreshSoon.restart() })
        close()
    }

    Timer { id: refreshSoon; interval: 300; onTriggered: menu.refresh() }
    Timer {
        interval: 5000; repeat: true; triggeredOnStart: true
        running: menu.isOpen && menu.tabId === "system"
        onTriggered: menu.call("GET", "/api/health", undefined, function (d) { if (d && d.temps) menu.health = d })
    }
    Timer { interval: 4000; repeat: true; running: menu.isOpen; onTriggered: menu.refresh() }
    Timer { id: followsPoll; interval: 3000; onTriggered: if (menu.isOpen) menu.loadFollows() }
    Timer { interval: 10000; repeat: true; running: menu.isOpen; triggeredOnStart: true; onTriggered: menu.now = new Date() }
    Timer { id: idleClose; interval: 90000; onTriggered: menu.close() }   // écran de TV : pas d'image fixe
    Timer { id: poweroffReset; interval: 4100; onTriggered: menu.poweroffUntil = 0 }

    // Ouverture, fermeture

    function open() {
        if (isOpen) return
        tab = 0; area = "content"; shortcut = -1; modal = null; pendingDisplay = ""; poweroffUntil = 0
        follows = null; replays = ({}); history = null; rpLogin = ""; rpRow = 0; rpSel = [0, 0, 0]
        yt = null; ytRow = 0; ytSel = ({}); kbOpen = false
        jf = null; jfRow = 0; jfSel = ({})   // les résultats de recherche restent d'une ouverture à l'autre
        var list = st.streamers || []
        liveSel = Math.max(0, list.indexOf(st.channel))
        startFocus = true
        isOpen = true
        box.setMenuOpen(true)
        refresh()
        call("GET", "/api/display", undefined, function (d) { if (d && d.modes) display = d })
        call("GET", "/api/account", undefined, function (d) { account = d })
        idleClose.restart()
    }
    function close() {
        if (!isOpen) return
        isOpen = false
        modal = null
        box.setMenuOpen(false)
        idleClose.stop()
    }
    Connections {
        target: box
        function onOpenRequested() { menu.open() }
        function onKeyPressed(k) { menu.key(k) }
    }
    Component.onCompleted: refresh()

    // Contenu calculé

    function shortcuts() {
        var l = [{ label: "⌂  Écran d'accueil", current: st.mode === "home", ok: function () { act("home"); close() } }]
        if (st.mode !== "twitch" && st.channel)
            l.push({ label: "▶  Reprendre " + st.channel, ok: function () { act("twitch"); close() } })
        if (pip.channel) {   // second stream en cours
            l.push({ label: "Inverser avec " + pip.channel, ok: function () { pip.swap(); close() } })
            l.push(pip.layout === "split" ? { label: "Incrustation", ok: function () { pip.setLayout("pip") } }
                                          : { label: "Côte à côte", ok: function () { pip.setLayout("split") } })
            l.push({ label: "Fermer " + pip.channel, ok: function () { pip.close() } })
        }
        return l
    }
    // Menu ≡ sur un streamer : le regarder, ou l'ajouter en second stream à côté de celui en cours
    function streamerOptions(name, addToList, isLive) {
        var watch = function () { act("channel", { name: name }); close() }
        var items = [{ label: "▶  Regarder", ok: watch }]
        // Second stream : seulement une chaîne en live (sinon un cadre noir qui attend), à côté d'un direct
        if (isLive && st.mode === "twitch" && st.channel && name !== st.channel) {
            items.push({ label: "En incrustation", ok: function () { pip.open(name, "pip"); close() } })
            items.push({ label: "Côte à côte", ok: function () { pip.open(name, "split"); close() } })
        }
        if (addToList) items.push({ label: "+  Ajouter à ma liste", ok: function () { act("streamers", { action: "add", login: name }) } })
        openModal(name, items)
    }
    function followList() {
        if (!follows || !follows.authorized) return []
        return (follows.live || []).concat(follows.offline || [])
    }
    function inList(name) { return (st.streamers || []).indexOf(name) >= 0 }
    function replayRows() {
        var rows = [{ kind: "chips", items: st.streamers || [] }]
        var d = replays[rpLogin]
        if (d && d.vods) {
            if (d.vods.length) rows.push({ kind: "vods", title: "Rediffusions", items: d.vods })
            if (d.clips.length) rows.push({ kind: "clips", title: "Clips de la semaine", items: d.clips })
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
        return [
            { header: "Chat" },
            { label: "Chat sur la TV", toggle: !!s.chat_visible, ok: function () { act("chat") } },
            { label: "Coin du chat", value: corners[s.corner] || "", step: function (d) {
                // l'API ne sait qu'avancer d'un coin : trois pas en avant valent un pas en arrière
                for (var n = 0; n < (d > 0 ? 1 : 3); n++) act("corner")
            } },
            { label: "Fond du chat", value: (s.chat_bg || 0) + " %", step: function (d) {
                act("set", { key: "chat_bg", value: Math.max(0, Math.min(100, (s.chat_bg || 0) + 10 * d)) })
            } },
            { label: "Taille du texte", value: (s.chat_size || 0) + " px", step: function (d) {
                act("set", { key: "chat_size", value: Math.max(20, Math.min(60, (s.chat_size || 0) + 2 * d)) })
            } },
            { header: "Lecture" },
            { label: "Bascule automatique", hint: "Passer sur un streamer en live si le sien est hors ligne",
              toggle: !!s.auto_switch, ok: function () { act("auto_switch", { enabled: !s.auto_switch }) } },
            { label: "Sondages et prédictions", hint: "En haut de la TV pendant un direct", toggle: !!s.events,
              ok: function () { act("flag", { key: "events", enabled: !s.events }) } },
            { label: "Mode nuit", hint: "Sons forts atténués, voix remontées", toggle: !!s.night,
              ok: function () { act("flag", { key: "night", enabled: !s.night }) } },
            { label: "Volume", value: s.mute ? "muet" : (s.volume || 0) + " %", step: function (d) { act("volume", { delta: 5 * d }) } },
            { header: "Affichage" },
            { label: "Résolution de la TV",
              value: !display ? "…" : cur === "auto" ? "Auto (" + prettyMode(display.auto) + ")" : prettyMode(cur),
              hint: pendingDisplay && display && pendingDisplay !== display.setting ? "OK pour appliquer" : undefined,
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
            { label: "QR code de la télécommande", value: qrModes[qi][1], step: function (d) {
                act("qr", { mode: qrModes[Math.max(0, Math.min(qrModes.length - 1, qi + d))][0] })
            } },
        ]
    }
    Timer { id: displayReload; interval: 3000; onTriggered: menu.call("GET", "/api/display", undefined, function (d) { if (d && d.modes) menu.display = d }) }
    function selectable(rows) {
        var out = []
        for (var i = 0; i < rows.length; i++) if (!rows[i].header) out.push(i)
        return out
    }
    function systemRows() {
        var login = account && account.login
        return [
            { label: "Compte Twitch", value: login ? "Connecté : " + login : "Non connecté",
              hint: login ? "Pas de pub sur les chaînes où tu es abonné" : "Se connecte depuis la télécommande du téléphone" },
            { label: "Lecteur", value: (pendingPlayer || st.player) === "mpv" ? "mpv seul" : "Appli Qt (menu animé)",
              hint: pendingPlayer && pendingPlayer !== st.player ? "OK pour appliquer : le lecteur redémarre" : undefined,
              step: function (d) { pendingPlayer = (pendingPlayer || st.player) === "qt" ? "mpv" : "qt" },
              ok: function () {
                  if (!pendingPlayer || pendingPlayer === st.player) return
                  act("player", { mode: pendingPlayer })
                  pendingPlayer = ""
                  close()
              } },
            { label: "Mettre à jour maintenant",
              hint: health && health.update ? (health.update.running ? "Mise à jour en cours…"
                    : (health.update.last ? (health.update.last.ok ? "Dernière : " : "Échec : ") + frDate(health.update.last.date) : "Jamais")
                      + (health.update.next ? "  ·  prochaine : " + frDate(health.update.next) : "")) : undefined,
              ok: function () { if (!(health && health.update && health.update.running)) act("update") } },
            { label: "Éteindre la box", danger: true,
              hint: poweroffUntil > 0 ? "Appuie encore sur OK pour éteindre" : undefined,
              ok: function () {
                  if (poweroffUntil > 0) { act("poweroff"); close() }
                  else { poweroffUntil = 1; poweroffReset.restart() }
              } },
        ]
    }
    // « 2026-10-23 11:48:14 » ou « Mon 2026-10-26 05:07:37 CET » → « ven. 23 oct. à 11:48 »
    function frDate(text) {
        var m = /(\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d)/.exec(text || "")
        if (!m) return text || ""
        var d = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5])
        return d.toLocaleDateString(Qt.locale("fr_FR"), "ddd d MMM") + " à " + m[4] + ":" + m[5]
    }
    function bytes(n) { return n >= 1e9 ? (n / 1e9).toFixed(1).replace(".", ",") + " Go" : Math.round(n / 1e6) + " Mo" }
    function bits(n) {
        return n === null || n === undefined ? "…" : n >= 1e6 ? (n / 1e6).toFixed(1).replace(".", ",") + " Mbit/s" : Math.round(n / 1e3) + " kbit/s"
    }
    function since(s) {
        var h = Math.floor(s / 3600), d = Math.floor(h / 24)
        return d ? d + " j " + (h % 24) + " h" : h ? h + " h " + (Math.floor(s / 60) % 60 < 10 ? "0" : "") + Math.floor(s / 60) % 60 : Math.floor(s / 60) + " min"
    }
    // Tuiles de l'état de la box : [titre, valeur, détail, niveau (""|"warn"|"bad")]
    function healthTiles() {
        var h = health
        if (!h) return []
        var t = h.temps.cpu, p = h.player, ok = function (v) { return v === "active" ? "✓" : "✕" }
        var net = h.network
        return [
            ["Température", t !== undefined ? t + " °C" : "–", h.temps.disk !== undefined ? "disque " + h.temps.disk + " °C" : "",
             t >= 85 ? "bad" : t >= 70 ? "warn" : ""],
            ["Processeur", h.cpu !== null ? Math.round(h.cpu) + " %" : "…", "charge " + h.load.toFixed(1).replace(".", ",") + " · " + h.cores + " cœurs",
             h.cpu >= 85 ? "warn" : ""],
            ["Mémoire", bytes(h.memory.total - h.memory.available), "sur " + bytes(h.memory.total), h.memory.available < 5e8 ? "warn" : ""],
            ["Disque", bytes(h.disk.free) + " libres", "sur " + bytes(h.disk.total), h.disk.free < 5e9 ? "warn" : ""],
            ["Réseau", "↓ " + bits(net.rx), "↑ " + bits(net.tx) + (net.speed > 0 ? " · lien " + (net.speed >= 1000 ? net.speed / 1000 + " Gbit/s" : net.speed + " Mbit/s") : ""), ""],
            ["Allumée depuis", since(h.uptime), "MQTT " + ok(h.services.mqtt) + " · jetons YouTube " + ok(h.services.youtube_tokens),
             h.services.mqtt !== "active" || h.services.youtube_tokens !== "active" ? "warn" : ""],
            ["Lecture", (p.running === "qt" ? "Appli Qt" : "mpv seul") + (p.hwdec && p.hwdec !== "no" ? " · " + p.hwdec : p.size ? " · processeur" : ""),
             p.size ? p.size.replace("x", " × ") + " · " + Math.round(p.fps || 0) + " im/s · " + (p.dropped || 0) + " perdues" : "rien en lecture",
             p.size && (!p.hwdec || p.hwdec === "no") ? "warn" : ""],
        ]
    }
    function openModal(title, items) { modal = { title: title, items: items }; modalSel = 0 }
    function chooseVideo(item) {
        if (Fmt.resumable(item.position, item.seconds, item.finished))
            openModal(item.title, [
                { label: "▶  Reprendre à " + Fmt.clock(item.position), ok: function () { play(item.url) } },
                { label: "↺  Depuis le début", ok: function () { play(item.url, true) } }])
        else
            play(item.url, true)
    }
    function subtitle() {
        var live = st.live || {}
        switch (tabId) {
        case "live":
            var n = (st.streamers || []).filter(function (s) { return !!live[s] }).length
            return n === 0 ? "Aucun streamer de la liste n'est en live" : n === 1 ? "1 streamer en live" : n + " streamers en live"
        case "follows":
            if (!follows) return "Chargement…"
            if (follows.error) return "Twitch injoignable pour l'instant"
            if (!follows.configured) return "Tes chaînes suivies sur Twitch"
            if (!follows.authorized) return "Autorise la box à lire tes chaînes suivies (lecture seule)"
            return (follows.live.length ? follows.live.length + " en live" : "Personne en live") + "  ·  " + followList().length + " chaînes suivies"
        case "replays":
            var d = replays[rpLogin]
            return d === "loading" ? rpLogin + " · chargement…" : d === false ? "Twitch injoignable pour l'instant"
                : (d && replayRows().length === 1) ? rpLogin + " : rien cette semaine" : rpLogin + " · rediffusions et clips de la semaine"
        case "history":
            return history === null ? "Chargement…" : history.length === 0 ? "Les vidéos lancées sur la TV s'afficheront ici"
                : (history.length === 1 ? "1 vidéo" : history.length + " vidéos") + " · OK pour reprendre ou retirer"
        case "youtube":
            if (!yt) return "Chargement…"
            return yt.channels.length ? yt.channels.length + (yt.channels.length === 1 ? " chaîne" : " chaînes") + " · dernières vidéos"
                : "Recherche une vidéo, ou ajoute des chaînes depuis la télécommande"
        case "jellyfin":
            if (!jf) return "Chargement…"
            if (jf.error) return "Jellyfin injoignable pour l'instant"
            if (!jf.configured) return "Ta bibliothèque Jellyfin"
            return jf.server + " · la progression suit sur tous tes appareils"
        case "settings": return "◀ ▶ pour changer une valeur"
        }
        return ""
    }

    // Onglet affiché : données chargées à la première visite
    onTabChanged: {
        // tabs[tab] et pas tabId : la liaison de tabId n'est pas encore recalculée ici
        var id = tabs[tab].id
        tabEnter.restart()
        if (id === "follows" && follows === null) loadFollows()
        if (id === "history" && history === null) loadHistory()
        if (id === "youtube" && yt === null) loadYoutube()
        if (id === "jellyfin" && jf === null) loadJellyfin()
        if (id === "replays") {
            if (!rpLogin) rpLogin = st.channel || (st.streamers || [])[0] || ""
            loadReplays(rpLogin)
        }
    }

    // Touches

    function grid(sel, count, cols, k) {   // déplacement dans une grille : nouvelle position, ou -1 pour sortir à gauche
        var col = sel % cols
        if (k === "left") return col === 0 ? -1 : sel - 1
        if (k === "right") return col < cols - 1 && sel < count - 1 ? sel + 1 : sel
        if (k === "up") return sel >= cols ? sel - cols : sel
        if (k === "down") return sel + cols < count ? sel + cols : (Math.floor(sel / cols) < Math.floor((count - 1) / cols) ? count - 1 : sel)
        return sel
    }
    function key(k) {
        idleClose.restart()
        startFocus = false
        if (k === "home") return close()
        if (k === "homescreen") { act("home"); return close() }
        if (k === "corner") return act("corner")
        if (kbOpen) return keyKeyboard(k)
        if (modal) {
            if (k === "up" || k === "down") modalSel = Math.max(0, Math.min(modal.items.length - 1, modalSel + (k === "down" ? 1 : -1)))
            else if (k === "ok") { var it = modal.items[modalSel]; modal = null; it.ok() }
            else if (k === "back" || k === "left") modal = null
            return
        }
        if (area === "rail") {
            if (k === "up" || k === "down") tab = Math.max(0, Math.min(tabs.length - 1, tab + (k === "down" ? 1 : -1)))
            else if (k === "right" || k === "ok") enterContent()
            else if (k === "back") close()
            return
        }
        if (k === "back") { area = "rail"; pendingDisplay = ""; pendingPlayer = ""; return }
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
    function enterContent() {
        if (tabId === "youtube" || tabId === "jellyfin") { area = "content"; setRow(0); return }
        if (tabId === "follows" && (!follows || !follows.configured)) return
        if (tabId === "history" && !(history && history.length)) return
        area = "content"
        if (tabId === "replays") { rpRow = 0; rpSel = [Math.max(0, (st.streamers || []).indexOf(rpLogin)), rpSel[1], rpSel[2]] }
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
        if (k === "up" && liveSel < 4) { shortcut = 0; return }
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
    function setMediaSel(s) { if (jfTab) jfSel = s; else ytSel = s }   // (setSel est la ligne choisie des Réglages)
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
        else if (k === "ok" && row.items[sel]) {
            if (row.kind === "chans") ytChannelMenu(row.items[sel])
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
            if (key === "Espace") kbText += " "
            else if (key === "Effacer") kbText = kbText.slice(0, -1)
            else if (key === "Tout effacer") kbText = ""
            else if (key === "Rechercher") { if (kbText.trim()) { kbOpen = false; if (jfTab) jfSearch(kbText); else ytSearch(kbText) } }
            else if (kbText.length < 80) kbText += key
        }
    }
    function keyHistory(k) {
        var list = history || []
        if (k === "ok" && list[histSel]) {
            var e = list[histSel], items = []
            if (Fmt.resumable(e.position, e.duration, e.finished)) {
                items.push({ label: "▶  Reprendre à " + Fmt.clock(e.position), ok: function () { play(e.url) } })
                items.push({ label: "↺  Depuis le début", ok: function () { play(e.url, true) } })
            } else items.push({ label: e.finished ? "↺  Revoir" : "▶  Lire", ok: function () { play(e.url, true) } })
            items.push({ label: "✕  Retirer de l'historique", danger: true, ok: function () {
                call("POST", "/api/history", { action: "remove", key: e.key }, function () { loadHistory() })
                var h = history.slice(); h.splice(histSel, 1); history = h
                histSel = Math.max(0, Math.min(histSel, h.length - 1))
                if (!h.length) area = "rail"
            } })
            openModal(e.title, items)
            return
        }
        var n = grid(histSel, list.length, 4, k)
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

    // Dessin

    Rectangle {   // voile sur la vidéo ; opaque sans vidéo, pour cacher l'écran d'ambiance
        anchors.fill: parent
        color: menu.pal.veil
        opacity: box.videoActive ? 0.89 : 1
        Behavior on color { ColorAnimation { duration: 400 } }
    }
    Rectangle {   // lueur en haut à droite, de la couleur de l'onglet
        x: 1350; y: -350; width: 900; height: 700; radius: 450
        color: menu.accent
        opacity: menu.pal.glow
        Behavior on color { ColorAnimation { duration: 400 } }
        Behavior on opacity { NumberAnimation { duration: 400 } }
    }
    Rectangle {   // seconde lueur, en bas, sur les onglets YouTube et Jellyfin
        x: 500; y: 780; width: 1100; height: 600; radius: 300
        color: menu.accent
        opacity: menu.theme === "youtube" ? 0.11 : menu.theme === "jellyfin" ? 0.10 : 0
        Behavior on color { ColorAnimation { duration: 400 } }
        Behavior on opacity { NumberAnimation { duration: 400 } }
    }

    // Rail des onglets
    Rectangle { width: 400; height: parent.height; color: menu.pal.rail; opacity: 0.55
                Behavior on color { ColorAnimation { duration: 400 } } }
    Logo { x: 56; y: 62 }
    Text { x: 126; y: 88 - height / 2; text: "Stream Box"; color: "white"; font.pixelSize: 28; font.bold: true }
    Rectangle {   // pastille de l'onglet : glisse d'un onglet à l'autre
        x: 40; width: 320; height: 64; radius: 32
        y: 206 + menu.tab * 76   // 9 onglets entre le logo et « En cours sur la TV »
        color: "white"
        opacity: menu.area === "rail" ? 1 : 0.10
        Behavior on y { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
        Behavior on opacity { NumberAnimation { duration: 160 } }
    }
    Repeater {
        model: menu.tabs.length
        Item {
            x: 40; y: 206 + index * 76; width: 320; height: 64
            readonly property bool cur: index === menu.tab
            Rectangle {   // onglet en cours, focus dans le contenu : point de la couleur de l'onglet
                visible: cur && menu.area !== "rail"
                x: 20; anchors.verticalCenter: parent.verticalCenter
                width: 12; height: 12; radius: 6; color: menu.accent
            }
            Text {
                x: cur && menu.area !== "rail" ? 48 : 38
                anchors.verticalCenter: parent.verticalCenter
                text: menu.tabs[index].label
                color: cur && menu.area === "rail" ? "#1a1020" : (cur ? "white" : "#b4afc2")
                font.pixelSize: 25
                font.bold: cur
                Behavior on x { NumberAnimation { duration: 160 } }
            }
        }
    }
    Column {   // ce qui joue sur la TV
        x: 56; y: menu.height - 190; width: 310; spacing: 8
        visible: (menu.st.mode === "twitch" && !!menu.st.channel) || menu.st.mode === "media"
        Text { text: "EN COURS SUR LA TV"; color: "#a99fc0"; font.pixelSize: 16; font.bold: true; font.letterSpacing: 2 }
        Marquee {
            width: parent.width; pixelSize: 22; running: menu.isOpen
            // Chaîne hors de la liste (suivie, second stream inversé) : pas de relevé du live, juste son nom
            readonly property var info: (menu.st.live || {})[menu.st.channel]
            text: menu.st.mode === "media" ? (menu.st.title || "Vidéo")
                : (menu.st.channel || "") + (info ? "  ·  " + info.title : "")
        }
    }
    Text {
        x: 56; y: menu.height - 75
        text: "▲▼◀▶ se déplacer   ·   OK valider   ·   ≡ options   ·   Retour revenir   ·   Menu fermer"
        color: "#8a85a0"; font.pixelSize: 19
    }

    // En-tête
    Text { x: 460; y: 100 - height / 2; text: menu.tabs[menu.tab].label; color: "white"; font.pixelSize: 41; font.bold: true }
    Text { x: 460; y: 158 - height / 2; text: menu.subtitle(); color: "#b4afc2"; font.pixelSize: 25 }
    Row {
        anchors.right: parent.right; anchors.rightMargin: 80; y: 100 - height / 2; spacing: 28
        Text {
            anchors.verticalCenter: parent.verticalCenter
            visible: !!(menu.ambient.weather && menu.ambient.weather.temp !== undefined)
            text: visible ? menu.ambient.weather.temp + "°  " + (menu.ambient.weather.text || "") : ""
            color: "#b4afc2"; font.pixelSize: 25
        }
        Text { text: Qt.formatTime(menu.now, "hh:mm"); color: "white"; font.pixelSize: 31 }
    }

    // Contenu de l'onglet : arrive en glissant à chaque changement
    Item {
        id: content
        x: 460; y: 0; width: 1460; height: parent.height
        ParallelAnimation {
            id: tabEnter
            NumberAnimation { target: content; property: "x"; from: 500; to: 460; duration: 260; easing.type: Easing.OutCubic }
            NumberAnimation { target: content; property: "opacity"; from: 0; to: 1; duration: 220 }
        }

        // --- En direct
        Item {
            anchors.fill: parent
            visible: menu.tabId === "live"
            Row {
                y: 210; spacing: 20
                Repeater {
                    model: menu.shortcuts()
                    Item {
                        width: label.implicitWidth + 72; height: 64
                        readonly property bool foc: menu.area === "content" && menu.shortcut === index
                        scale: foc ? 1.05 : 1
                        Behavior on scale { NumberAnimation { duration: 160 } }
                        FocusFrame { active: foc; radius: 32 }
                        Rectangle { anchors.fill: parent; radius: 32; color: modelData.current ? "#9146ff" : (foc ? "#3a2c4e" : "#2a2034") }
                        Text { id: label; anchors.centerIn: parent; text: modelData.label; color: "white"; font.pixelSize: 24; font.bold: !!modelData.current }
                    }
                }
            }
            Item {   // découpe : ce qui défile s'arrête au bord de la zone (ni sur le titre, ni sur l'aide en bas)
                x: -53; y: 255; width: 1540; height: 3 * 176 + 60 + 30; clip: true
                GridView {
                    id: liveGrid
                    y: 15; x: 40; width: 1460; height: 3 * 176 + 60
                    cellWidth: 356; cellHeight: 176
                    interactive: false; clip: false
                    topMargin: 27
                    model: (menu.st.streamers || []).length
                    currentIndex: menu.liveSel
                    onCurrentIndexChanged: positionViewAtIndex(currentIndex, GridView.Contain)
                    Behavior on contentY { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
                    delegate: Item {
                        width: 356; height: 176
                        readonly property real rel: y - GridView.view.contentY
                        opacity: rel > -88 && rel < GridView.view.height - 88 ? 1 : 0
                        Behavior on opacity { NumberAnimation { duration: 150 } }
                        readonly property string login: (menu.st.streamers || [])[index] || ""
                        readonly property var info: (menu.st.live || {})[login]
                        StreamerCard {
                            x: 13; y: 13
                            name: login
                            avatar: (menu.st.avatars || {})[login] || ""
                            live: !!info
                            viewers: info ? info.viewers : 0
                            game: info ? (info.game || info.title || "") : ""
                            focused: menu.area === "content" && menu.shortcut < 0 && index === menu.liveSel
                            current: menu.st.mode === "twitch" && menu.st.channel === login
                        }
                    }
                }
            }
            Marquee {   // titre du live choisi, en entier
                y: 290 + 3 * 176 + 40; width: 1400; pixelSize: 24; color: "#d0c8e0"; running: true
                readonly property string login: (menu.st.streamers || [])[menu.liveSel] || ""
                readonly property var info: (menu.st.live || {})[login]
                visible: menu.area === "content" && menu.shortcut < 0 && !!info
                text: info ? login + "  ·  " + info.title : ""
            }
            Text {
                visible: !(menu.st.streamers || []).length
                y: 280; text: "La liste est vide : ajoute des streamers depuis la télécommande web."
                color: "#b4afc2"; font.pixelSize: 27
            }
        }

        // --- Suivis
        Item {
            id: followsPage
            anchors.fill: parent
            visible: menu.tabId === "follows"
            readonly property var f: menu.follows || {}
            readonly property var pend: f.pending || null
            readonly property bool waiting: !!(pend && pend.user_code && !pend.error)
            Column {
                visible: !!menu.follows && !menu.follows.error && !followsPage.f.configured
                y: 260; spacing: 20
                Text { text: "Pour les afficher, la box a besoin de ta propre appli Twitch."; color: "white"; font.pixelSize: 27 }
                Text { text: "Télécommande web → Réglages → Chaînes suivies : tout y est expliqué."; color: "#b4afc2"; font.pixelSize: 22 }
            }
            Item {
                visible: !!followsPage.f.configured && !followsPage.f.authorized
                anchors.fill: parent
                Column {
                    visible: followsPage.waiting
                    y: 260; spacing: 26
                    Text { text: "Sur ton téléphone, ouvre twitch.tv/activate et tape :"; color: "white"; font.pixelSize: 27 }
                    Text { text: followsPage.pend ? followsPage.pend.user_code || "" : ""; color: "white"; font.pixelSize: 75; font.bold: true; font.letterSpacing: 12 }
                    Text { text: "ou scanne le QR code. La TV se met à jour toute seule."; color: "#b4afc2"; font.pixelSize: 22 }
                }
                QrCode { visible: followsPage.waiting && n > 0; x: 940; y: 240; size: 360; rows: menu.followsQr ? menu.followsQr.rows : [] }
                Item {
                    visible: !followsPage.waiting
                    y: 290; width: 440; height: 74
                    readonly property bool foc: menu.area === "content"
                    scale: foc ? 1.05 : 1
                    Behavior on scale { NumberAnimation { duration: 160 } }
                    FocusFrame { active: parent.foc; radius: 37 }
                    Rectangle { anchors.fill: parent; radius: 37; color: "#9146ff" }
                    Text { anchors.centerIn: parent; text: "Autoriser la box"; color: "white"; font.pixelSize: 25; font.bold: true }
                }
                Text {
                    visible: !!(followsPage.pend && followsPage.pend.error)
                    y: 230; text: visible ? "Autorisation refusée : " + followsPage.pend.error : ""
                    color: "#ff8f8f"; font.pixelSize: 22
                }
            }
            Item {   // découpe : ce qui défile s'arrête au bord de la zone (ni sur le titre, ni sur l'aide en bas)
                x: -53; y: 161; width: 1540; height: 4 * 176 + 60 + 30; clip: true
                GridView {
                    visible: !!followsPage.f.authorized
                    y: 15; x: 40; width: 1460; height: 4 * 176 + 60
                    cellWidth: 356; cellHeight: 176
                    interactive: false; clip: false; topMargin: 27
                    model: menu.followList().length
                    currentIndex: menu.followSel
                    onCurrentIndexChanged: positionViewAtIndex(currentIndex, GridView.Contain)
                    Behavior on contentY { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
                    delegate: Item {
                        width: 356; height: 176
                        readonly property real rel: y - GridView.view.contentY
                        opacity: rel > -88 && rel < GridView.view.height - 88 ? 1 : 0
                        Behavior on opacity { NumberAnimation { duration: 150 } }
                        readonly property var c: menu.followList()[index] || {}
                        StreamerCard {
                            x: 13; y: 13
                            name: c.login || ""
                            avatar: c.avatar || ""
                            live: c.viewers !== undefined && c.viewers !== null
                            viewers: c.viewers || 0
                            game: c.game || c.title || ""
                            focused: menu.area === "content" && index === menu.followSel
                            current: menu.st.mode === "twitch" && menu.st.channel === c.login
                        }
                    }
                }
            }
        }

        // --- Rediffusions
        Item {
            anchors.fill: parent
            visible: menu.tabId === "replays"
            readonly property var rows: menu.replayRows()
            ListView {   // puces des streamers
                y: 196; x: -40; width: 1500; height: 64
                orientation: ListView.Horizontal; spacing: 16; interactive: false; clip: false
                leftMargin: 40
                model: (menu.st.streamers || []).length
                currentIndex: menu.rpSel[0]
                onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)
                Behavior on contentX { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
                delegate: Item {
                    readonly property string login: (menu.st.streamers || [])[index] || ""
                    readonly property bool foc: menu.area === "content" && menu.rpRow === 0 && index === menu.rpSel[0]
                    readonly property bool cur: login === menu.rpLogin
                    // largeur mesurée en gras (le streamer affiché l'est) : la puce ne change pas de taille en le devenant
                    TextMetrics { id: chipMetrics; text: login; font.pixelSize: chipText.font.pixelSize; font.bold: true }
                    width: Math.ceil(chipMetrics.advanceWidth) + 100; height: 64
                    readonly property real rel: x - ListView.view.contentX
                    opacity: index >= ListView.view.first && index < ListView.view.first + ListView.view.fits ? 1 : 0   // fenêtre visée
                    Behavior on opacity { NumberAnimation { duration: 90 } }
                    scale: foc ? 1.05 : 1
                    Behavior on scale { NumberAnimation { duration: 160 } }
                    FocusFrame { active: parent.foc; radius: 32 }
                    Rectangle { anchors.fill: parent; radius: 32; color: parent.cur ? "#9146ff" : (parent.foc ? "#3a2c4e" : "#2a2034") }
                    RoundImage { x: 10; y: 8; width: 48; height: 48; circle: true; placeholder: "#4a3d5c"; source: (menu.st.avatars || {})[login] || "" }
                    Text { id: chipText; x: 70; anchors.verticalCenter: parent.verticalCenter; text: login; color: "white"; font.pixelSize: 22; font.bold: parent.cur }
                }
            }
            Repeater {
                model: Math.max(0, parent.rows.length - 1)
                Item {
                    readonly property int r: index + 1
                    readonly property var row: parent.rows[r]
                    y: 300 + index * 366; width: 1460; height: 350
                    Text { x: 2; text: row ? row.title.toUpperCase() : ""; color: "#a99fc0"; font.pixelSize: 20; font.bold: true; font.letterSpacing: 2 }
                    Item {   // découpe à gauche, au bord du contenu : une carte qui défile ne passe pas sous le rail
                        x: -28; y: 0; width: 1512; height: 302 + 80; clip: true
                        ListView {
                            y: 40; x: -12; width: 1460; height: 302   // 4 cartes jusqu'à 40 px du bord droit
                            orientation: ListView.Horizontal; spacing: 26; interactive: false; clip: false
                            leftMargin: 40
                            model: row ? row.items.length : 0
                            currentIndex: menu.rpSel[r] || 0
                            // Défilement carte par carte, la rangée restant alignée à gauche (et pas au plus juste,
                            // qui laissait des cartes coupées au bord du rail ou de l'écran)
                            property int first: 0
                            readonly property int fits: Math.floor((width - leftMargin + spacing) / 356)
                            onCurrentIndexChanged: {
                                if (currentIndex < first) first = currentIndex
                                else if (currentIndex >= first + fits) first = currentIndex - fits + 1
                                contentX = -leftMargin + first * 356
                            }
                            Behavior on contentX { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }
                            delegate: VideoCard {
                                readonly property var it: row.items[index] || {}
                                opacity: index >= ListView.view.first && index < ListView.view.first + ListView.view.fits ? 1 : 0   // fenêtre visée
                                Behavior on opacity { NumberAnimation { duration: 90 } }
                                title: it.title || ""
                                thumb: it.thumb || ""
                                meta: (row.kind === "vods" ? Fmt.dateFr(it.date) + " · " + Fmt.clock(it.seconds)
                                       : Fmt.clock(it.seconds) + " · " + Fmt.viewers(it.views) + " vues") + (it.finished ? " · vu" : "")
                                progress: it.finished ? 1 : (it.position && it.seconds ? it.position / it.seconds : 0)
                                focused: menu.area === "content" && menu.rpRow === r && index === (menu.rpSel[r] || 0)
                            }
                        }
                    }
                }
            }
        }

        // --- YouTube et Jellyfin : ligne de recherche, puis rangées horizontales de cartes
        Item {
            id: ytPage
            anchors.fill: parent
            visible: menu.tabId === "youtube" || menu.tabId === "jellyfin"
            readonly property var rows: menu.mediaRows()
            // Rangées de hauteur fixe ; défilement vertical pour garder la rangée choisie à l'écran
            readonly property real rowH: 360   // deux rangées entières au-dessus de l'aide en bas
            readonly property real scrollY: Math.max(0, (menu.mRow - 1) * rowH)
            Item {   // ligne de recherche
                y: 200; width: 760; height: 66
                readonly property bool foc: menu.area === "content" && menu.mRow === 0 && !menu.kbOpen
                scale: foc ? 1.03 : 1
                Behavior on scale { NumberAnimation { duration: 160 } }
                FocusFrame { active: parent.foc; radius: 35; glow: menu.accent }
                Rectangle { anchors.fill: parent; radius: 35; color: parent.foc ? menu.pal.surfaceFocus : menu.pal.surface }
                Text {
                    x: 34; anchors.verticalCenter: parent.verticalCenter
                    text: menu.searchLabel()
                    color: "white"; font.pixelSize: 27
                }
            }
            Text {
                visible: menu.jfTab ? !!menu.jf && !menu.jf.configured && !menu.jf.error
                                    : !!menu.yt && menu.yt.channels.length === 0 && !menu.ytResults
                y: 320; text: menu.jfTab ? "Jellyfin n'est pas associé à la box : dans l'appli Jellyfin, « Lire sur… » → la box."
                                         : "Ajoute des chaînes YouTube depuis la télécommande web (Réglages → Chaînes YouTube)."
                color: "#b4afc2"; font.pixelSize: 27
            }
            Item {   // découpe : ce qui défile s'arrête au bord de la zone (ni sur le titre, ni sur l'aide en bas)
                x: -40; y: 276; width: parent.width + 80; height: 995 - 276; clip: true
                Item {   // rangées, sous la ligne de recherche
                    x: 40; y: 10; width: parent.width - 80; height: menu.height - 286
                    Repeater {
                        model: Math.max(0, ytPage.rows.length - 1)
                        Item {
                            readonly property int r: index + 1
                            readonly property var row: ytPage.rows[r]
                            y: index * ytPage.rowH - ytPage.scrollY
                            Behavior on y { NumberAnimation { duration: 280; easing.type: Easing.OutCubic } }
                            opacity: index >= Math.max(0, menu.mRow - 1) && index < Math.max(0, menu.mRow - 1) + 2 ? 1 : 0   // rangées visées
                            Behavior on opacity { NumberAnimation { duration: 180 } }
                            width: 1460; height: ytPage.rowH
                            Row {
                                spacing: 14
                                RoundImage { visible: !!(row && row.avatar); width: 40; height: 40; circle: true; source: row && row.avatar ? row.avatar : "" }
                                Text { anchors.verticalCenter: parent.verticalCenter; text: row ? row.title : ""; color: "#d0c8e0"; font.pixelSize: 24; font.bold: true }
                            }
                            Text {
                                visible: !!row && row.items.length === 0
                                y: 70; text: row && row.kind === "results" ? (menu.mSearching ? "Recherche…" : "Aucun résultat")
                                           : row && row.loading ? "Chargement…" : menu.jfTab ? "Rien ici" : "YouTube injoignable pour l'instant"
                                color: "#8a85a0"; font.pixelSize: 24
                            }
                            Item {   // découpe à gauche, au bord du contenu : une carte qui défile ne passe pas sous le rail
                                x: -28; y: 10; width: 1512; height: 302 + 80; clip: true
                                ListView {   // chaînes trouvées : photo ronde, nom, abonnés, « dans ta liste »
                                    visible: !!row && row.kind === "chans"
                                    y: 40; x: -12; width: 1460; height: 302   // 4 cartes jusqu'à 40 px du bord droit
                                    orientation: ListView.Horizontal; spacing: 30; interactive: false; clip: false
                                    leftMargin: 40
                                    model: visible ? row.items.length : 0
                                    currentIndex: visible ? (menu.mSel["chans"] || 0) : 0
                                    // Défilement carte par carte, la rangée restant alignée à gauche (et pas au plus juste,
                                    // qui laissait des cartes coupées au bord du rail ou de l'écran)
                                    property int first: 0
                                    readonly property int fits: Math.floor((width - leftMargin + spacing) / 270)
                                    onCurrentIndexChanged: {
                                        if (currentIndex < first) first = currentIndex
                                        else if (currentIndex >= first + fits) first = currentIndex - fits + 1
                                        contentX = -leftMargin + first * 270
                                    }
                                    Behavior on contentX { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }
                                    delegate: Item {
                                        readonly property var c: row.items[index] || {}
                                        readonly property bool foc: menu.area === "content" && menu.mRow === r && index === (menu.mSel["chans"] || 0)
                                        width: 240; height: 302
                                        opacity: index >= ListView.view.first && index < ListView.view.first + ListView.view.fits ? 1 : 0
                                        Behavior on opacity { NumberAnimation { duration: 90 } }
                                        z: foc ? 2 : 1
                                        Item {
                                            x: 30; y: 6; width: 180; height: 180
                                            scale: parent.foc ? 1.06 : 1
                                            Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                                            FocusFrame { active: parent.parent.foc; radius: 90; glow: menu.accent }
                                            RoundImage {
                                                anchors.fill: parent; circle: true; placeholder: "#2a2034"; source: c.avatar || ""
                                                Text { anchors.centerIn: parent; z: -1; text: (c.name || "?").charAt(0).toUpperCase(); color: "#d0c8e0"; font.pixelSize: 64; font.bold: true }
                                            }
                                        }
                                        Text {
                                            y: 206; width: parent.width; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight
                                            text: c.name || ""; color: "white"; font.pixelSize: 25; font.bold: parent.foc
                                        }
                                        Text {
                                            y: 242; width: parent.width; horizontalAlignment: Text.AlignHCenter
                                            text: (c.followers ? Fmt.big(c.followers) + " abonnés" : "") + (c.saved ? (c.followers ? " · " : "") + "✓ suivie" : "")
                                            color: c.saved ? "#ff6b7f" : "#b4afc2"; font.pixelSize: 20
                                        }
                                    }
                                }
                            }
                            Item {   // découpe à gauche, au bord du contenu : une carte qui défile ne passe pas sous le rail
                                x: -28; y: 10; width: 1512; height: 302 + 80; clip: true
                                ListView {
                                    visible: !!row && row.kind !== "chans"
                                    y: 40; x: -12; width: 1460; height: 302   // 4 cartes jusqu'à 40 px du bord droit
                                    orientation: ListView.Horizontal; spacing: 26; interactive: false; clip: false
                                    leftMargin: 40
                                    model: visible ? row.items.length : 0
                                    currentIndex: visible ? (menu.mSel[row.key] || 0) : 0
                                    // Défilement carte par carte, la rangée restant alignée à gauche (et pas au plus juste,
                                    // qui laissait des cartes coupées au bord du rail ou de l'écran)
                                    property int first: 0
                                    readonly property int fits: Math.floor((width - leftMargin + spacing) / 356)
                                    onCurrentIndexChanged: {
                                        if (currentIndex < first) first = currentIndex
                                        else if (currentIndex >= first + fits) first = currentIndex - fits + 1
                                        contentX = -leftMargin + first * 356
                                    }
                                    Behavior on contentX { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }
                                    delegate: VideoCard {
                                        readonly property var it: row.items[index] || {}
                                        opacity: index >= ListView.view.first && index < ListView.view.first + ListView.view.fits ? 1 : 0   // fenêtre visée
                                        Behavior on opacity { NumberAnimation { duration: 90 } }
                                        title: it.title || ""
                                        thumb: it.thumb || ""
                                        meta: menu.cardMeta(row, it)
                                        progress: it.finished ? 1 : (it.position && it.seconds ? it.position / it.seconds : 0)
                                        accent: menu.accent
                                        focused: menu.area === "content" && menu.mRow === r && index === (menu.mSel[row.key] || 0)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // --- Historique
        Item {   // découpe : ce qui défile s'arrête au bord de la zone (ni sur le titre, ni sur l'aide en bas)
            x: -53; y: 161; width: 1540; height: 2 * 340 + 60 + 30; clip: true
            GridView {
                visible: menu.tabId === "history"
                y: 15; x: 40; width: 1460; height: 2 * 340 + 60
                cellWidth: 356; cellHeight: 340
                interactive: false; clip: false; topMargin: 27
                model: (menu.history || []).length
                currentIndex: menu.histSel
                onCurrentIndexChanged: positionViewAtIndex(currentIndex, GridView.Contain)
                Behavior on contentY { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }
                delegate: Item {
                    width: 356; height: 340
                    readonly property real rel: y - GridView.view.contentY
                    opacity: rel > -170 && rel < GridView.view.height - 170 ? 1 : 0
                    Behavior on opacity { NumberAnimation { duration: 150 } }
                    readonly property var e: (menu.history || [])[index] || {}
                    VideoCard {
                        x: 13; y: 13
                        title: e.title || ""
                        thumb: e.thumb || ""
                        meta: (menu.kinds[e.kind] || "") + (e.finished ? " · vu"
                              : e.duration > 0 ? " · " + Fmt.clock(e.position) + " / " + Fmt.clock(e.duration) : "")
                        progress: e.finished ? 1 : (Fmt.resumable(e.position, e.duration, e.finished) && e.duration > 0 ? e.position / e.duration : 0)
                        accent: menu.accent
                        focused: menu.area === "content" && index === menu.histSel
                    }
                }
            }
        }

        // --- Réglages et Système : listes de lignes
        Repeater {
            model: ["settings", "system"]
            Item {   // découpe : ce qui défile s'arrête au bord de la zone (ni sur le titre, ni sur l'aide en bas)
                visible: menu.tabId === modelData
                x: -40; y: 165; width: (modelData === "settings" ? 980 : 810) + 80; height: 830; clip: true
                ListView {
                    id: rowsView
                    visible: menu.tabId === modelData
                    readonly property var rows: modelData === "settings" ? menu.settingsRows() : menu.systemRows()
                    readonly property var sel: menu.selectable(rows)
                    readonly property int focusedRow: menu.area === "content" ? sel[modelData === "settings" ? menu.setSel : menu.sysSel] : -1
                    y: 15; x: 40; width: modelData === "settings" ? 980 : 810; height: 800   // s'arrête au-dessus de l'aide en bas
                    spacing: 10; interactive: false; clip: false; topMargin: 30
                    model: rows.length
                    onFocusedRowChanged: if (focusedRow >= 0) positionViewAtIndex(focusedRow, ListView.Contain)
                    Behavior on contentY { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
                    delegate: SettingRow {
                        width: rowsView.width
                        readonly property real rel: y - rowsView.contentY
                        opacity: rel > -height / 2 && rel + height / 2 < rowsView.height ? 1 : 0
                        Behavior on opacity { NumberAnimation { duration: 150 } }
                        row: rowsView.rows[index] || {}
                        pal: menu.pal
                        focused: index === rowsView.focusedRow
                    }
                }
            }
        }
        Flow {   // Système : état de la box, sous les lignes (« Lecture » prend deux tuiles de large)
            visible: menu.tabId === "system"
            x: 0; y: 650; width: 810
            spacing: 10
            Repeater {
                model: menu.healthTiles()
                Rectangle {
                    width: index === 6 ? 262 * 2 + 10 : 262; height: 96; radius: 18
                    color: "#1affffff"; border.color: "#22ffffff"; border.width: 1
                    readonly property color tone: modelData[3] === "bad" ? "#ff6b6b" : modelData[3] === "warn" ? "#ffb44a" : "white"
                    Column {
                        x: 18; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 36; spacing: 2
                        Text { text: modelData[0].toUpperCase(); color: menu.pal.label; font.pixelSize: 15; font.bold: true; font.letterSpacing: 1.5 }
                        Text { width: parent.width; elide: Text.ElideRight; text: modelData[1]; color: parent.parent.tone; font.pixelSize: 23; font.bold: true }
                        Text { width: parent.width; elide: Text.ElideRight; text: modelData[2]; color: "#b0b0b8"; font.pixelSize: 16 }
                    }
                }
            }
        }
        Column {   // Système : QR code de la télécommande web, pour tout ce qui demande de taper du texte
            visible: menu.tabId === "system" && !!(menu.ambient.qr && menu.ambient.qr.rows)
            x: 880; y: 230; spacing: 16
            QrCode { size: 300; rows: menu.ambient.qr ? menu.ambient.qr.rows : [] }
            Text { text: "Télécommande sur le téléphone"; color: "white"; font.pixelSize: 23; font.bold: true }
            Text { text: "Lien, streamer, compte Twitch…"; color: "#b4afc2"; font.pixelSize: 20 }
            Text { text: menu.ambient.qr ? String(menu.ambient.qr.url).replace(/^https?:\/\//, "").replace(/\/$/, "") : ""; color: "#b4afc2"; font.pixelSize: 20 }
        }
    }

    // Clavier à l'écran (recherche YouTube)
    Item {
        anchors.fill: parent
        opacity: menu.kbOpen ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 160 } }
        Rectangle { anchors.fill: parent; color: "#05030a"; opacity: 0.6 }
        Rectangle {
            width: 1180; height: 690; radius: 30
            anchors.centerIn: parent
            color: menu.pal.sheet
            scale: menu.kbOpen ? 1 : 0.95
            Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
            Text { x: 48; y: 36; text: menu.jfTab ? "Rechercher dans Jellyfin" : "Rechercher sur YouTube"; color: menu.pal.label; font.pixelSize: 22; font.bold: true }
            Rectangle {   // texte tapé
                x: 44; y: 78; width: parent.width - 88; height: 76; radius: 18
                color: Qt.darker(menu.pal.sheet, 1.8); border.color: menu.pal.surfaceFocus; border.width: 2
                Text {
                    x: 26; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 52; elide: Text.ElideLeft
                    text: menu.kbText + "▏"; color: menu.kbText ? "white" : "#8a85a0"; font.pixelSize: 34
                }
            }
            Column {
                x: 56; y: 182; spacing: 12
                Repeater {
                    model: menu.kbKeys.length
                    Row {
                        readonly property int r: index
                        spacing: 12
                        Repeater {
                            model: menu.kbKeys[r].length
                            Rectangle {
                                readonly property string label: menu.kbKeys[r][index]
                                readonly property bool foc: menu.kbRow === r && menu.kbCol === index
                                readonly property bool wide: label.length > 1
                                width: wide ? (r === 5 ? 348 : 312) : 96; height: 72; radius: 16   // 10 touches de large : 1068
                                color: foc ? "white" : label === "Rechercher" ? menu.accent : menu.pal.key
                                scale: foc ? 1.06 : 1
                                Behavior on scale { NumberAnimation { duration: 120 } }
                                Text {
                                    anchors.centerIn: parent; text: label
                                    color: parent.foc ? "#1a1020" : "white"; font.pixelSize: wide ? 26 : 32; font.bold: parent.foc
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // Fenêtre d'actions
    Item {
        anchors.fill: parent
        opacity: menu.modal ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 160 } }
        Rectangle { anchors.fill: parent; color: "#05030a"; opacity: 0.6 }
        Rectangle {
            id: sheet
            readonly property var items: menu.modal ? menu.modal.items : []
            width: 820; height: 150 + items.length * 92; radius: 28
            anchors.centerIn: parent
            color: menu.pal.sheet
            scale: menu.modal ? 1 : 0.92
            Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutBack } }
            Marquee { x: 44; y: 46; width: parent.width - 88; text: menu.modal ? menu.modal.title || "" : ""; pixelSize: 27; bold: true; running: !!menu.modal }
            Repeater {
                model: sheet.items.length
                Rectangle {
                    readonly property bool foc: index === menu.modalSel
                    x: 30; y: 112 + index * 92; width: sheet.width - 60; height: 76; radius: 38
                    color: foc ? "white" : menu.pal.key
                    Behavior on color { ColorAnimation { duration: 140 } }
                    Text {
                        x: 40; anchors.verticalCenter: parent.verticalCenter
                        text: sheet.items[index] ? sheet.items[index].label : ""
                        color: parent.foc ? "#1a1020" : (sheet.items[index] && sheet.items[index].danger ? "#ff8f8f" : "white")
                        font.pixelSize: 26; font.bold: parent.foc
                    }
                }
            }
        }
    }
}
