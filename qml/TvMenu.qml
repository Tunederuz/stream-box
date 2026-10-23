// Stream Box : grand menu de la TV en QML (rendu par la puce graphique), à la place de tv_menu.lua quand le lecteur est
// l'appli Qt (ui.py). Mêmes onglets et mêmes actions : tout passe par l'API de remote.py, comme la page web.
// Les touches arrivent de ui.py (box.keyPressed) déjà traduites : up, down, left, right, ok, back, home (bouton Menu,
// ferme), homescreen (WWW), corner (Play), menu (≡). Coordonnées en 1920x1080, mises à l'échelle par ui.qml.
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
        { id: "replays", label: "Rediffusions" }, { id: "history", label: "Historique" },
        { id: "settings", label: "Réglages" }, { id: "system", label: "Système" }]
    readonly property var corners: ({ tl: "↖ haut gauche", tr: "↗ haut droite", br: "↘ bas droite", bl: "↙ bas gauche" })
    readonly property var cornerOrder: ["tl", "tr", "br", "bl"]
    readonly property var qrModes: [["always", "Toujours"], ["timed", "30 secondes"], ["never", "Jamais"]]
    readonly property var kinds: ({ youtube: "YouTube", "twitch-vod": "Rediffusion Twitch", "twitch-clip": "Clip Twitch", link: "Lien" })

    // Données (relues à l'ouverture ; réaffectées en entier pour que les liaisons suivent)
    property var st: ({})
    property var follows: null
    property var replays: ({})
    property var history: null
    property var display: null
    property var account: null
    property var followsQr: null
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
    function loadHistory() { call("GET", "/api/history", undefined, function (d) { history = d || [] }) }
    function play(url, fromStart) {
        call("POST", "/api/play", { url: url, from_start: !!fromStart }, function () { refreshSoon.restart() })
        close()
    }

    Timer { id: refreshSoon; interval: 300; onTriggered: menu.refresh() }
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
        return l
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
            { label: "Éteindre la box", danger: true,
              hint: poweroffUntil > 0 ? "Appuie encore sur OK pour éteindre" : undefined,
              ok: function () {
                  if (poweroffUntil > 0) { act("poweroff"); close() }
                  else { poweroffUntil = 1; poweroffReset.restart() }
              } },
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
        if (k === "back") { area = "rail"; pendingDisplay = ""; return }
        switch (tabId) {
        case "live": return keyLive(k)
        case "follows": return keyFollows(k)
        case "replays": return keyReplays(k)
        case "history": return keyHistory(k)
        case "settings": return keyRows(k, settingsRows())
        case "system": return keyRows(k, systemRows())
        }
    }
    function enterContent() {
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
        if (k === "ok" && list[followSel]) {
            var name = list[followSel].login
            var watch = function () { act("channel", { name: name }); close() }
            if (inList(name)) return watch()
            openModal(name, [{ label: "▶  Regarder", ok: watch },
                             { label: "＋  Ajouter à ma liste", ok: function () { act("streamers", { action: "add", login: name }) } }])
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
        var set = function (v) { if (tabId === "settings") setSel = v; else sysSel = v; pendingDisplay = "" }
        if (k === "up") set(Math.max(0, cur - 1))
        else if (k === "down") set(Math.min(sel.length - 1, cur + 1))
        else if ((k === "left" || k === "right") && row && row.step) row.step(k === "right" ? 1 : -1)
        else if (k === "left") area = "rail"
        else if (k === "ok" && row) { if (row.ok) row.ok(); else if (row.step) row.step(1) }
    }

    // Dessin

    Rectangle {   // voile sur la vidéo ; opaque sans vidéo, pour cacher l'écran d'ambiance
        anchors.fill: parent
        color: "#0a0612"
        opacity: box.videoActive ? 0.89 : 1
    }
    Rectangle {   // lueur violette en haut à droite
        x: 1350; y: -350; width: 900; height: 700; radius: 450
        color: "#9146ff"; opacity: 0.10
    }

    // Rail des onglets
    Rectangle { width: 400; height: parent.height; color: "#100b17"; opacity: 0.55 }
    Rectangle { x: 56; y: 62; width: 52; height: 52; radius: 14; color: "#9146ff"
        Text { anchors.centerIn: parent; anchors.horizontalCenterOffset: 2; text: "▶"; color: "white"; font.pixelSize: 20 } }
    Text { x: 126; y: 88 - height / 2; text: "Stream Box"; color: "white"; font.pixelSize: 28; font.bold: true }
    Rectangle {   // pastille de l'onglet : glisse d'un onglet à l'autre
        x: 40; width: 320; height: 72; radius: 36
        y: 220 + menu.tab * 92
        color: "white"
        opacity: menu.area === "rail" ? 1 : 0.10
        Behavior on y { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
        Behavior on opacity { NumberAnimation { duration: 160 } }
    }
    Repeater {
        model: menu.tabs.length
        Item {
            x: 40; y: 220 + index * 92; width: 320; height: 72
            readonly property bool cur: index === menu.tab
            Rectangle {   // onglet en cours, focus dans le contenu : point violet
                visible: cur && menu.area !== "rail"
                x: 20; anchors.verticalCenter: parent.verticalCenter
                width: 12; height: 12; radius: 6; color: "#9146ff"
            }
            Text {
                x: cur && menu.area !== "rail" ? 48 : 38
                anchors.verticalCenter: parent.verticalCenter
                text: menu.tabs[index].label
                color: cur && menu.area === "rail" ? "#20101a" : (cur ? "white" : "#c2afb4")
                font.pixelSize: 25
                font.bold: cur
                Behavior on x { NumberAnimation { duration: 160 } }
            }
        }
    }
    Column {   // ce qui joue sur la TV
        x: 56; y: menu.height - 190; width: 310; spacing: 8
        visible: (menu.st.mode === "twitch" && !!menu.st.channel) || menu.st.mode === "media"
        Text { text: "EN COURS SUR LA TV"; color: "#c09fa9"; font.pixelSize: 16; font.bold: true; font.letterSpacing: 2 }
        Marquee {
            width: parent.width; pixelSize: 22; running: menu.isOpen
            text: menu.st.mode === "media" ? (menu.st.title || "Vidéo")
                : (menu.st.channel || "") + "  ·  " + (((menu.st.live || {})[menu.st.channel] || {}).title || "hors ligne")
        }
    }
    Text {
        x: 56; y: menu.height - 75
        text: "▲▼◀▶ se déplacer   ·   OK valider   ·   Retour revenir   ·   Menu fermer"
        color: "#a0858a"; font.pixelSize: 19
    }

    // En-tête
    Text { x: 460; y: 100 - height / 2; text: menu.tabs[menu.tab].label; color: "white"; font.pixelSize: 41; font.bold: true }
    Text { x: 460; y: 158 - height / 2; text: menu.subtitle(); color: "#c2afb4"; font.pixelSize: 25 }
    Row {
        anchors.right: parent.right; anchors.rightMargin: 80; y: 100 - height / 2; spacing: 28
        Text {
            anchors.verticalCenter: parent.verticalCenter
            visible: !!(menu.ambient.weather && menu.ambient.weather.temp !== undefined)
            text: visible ? menu.ambient.weather.temp + "°  " + (menu.ambient.weather.text || "") : ""
            color: "#c2afb4"; font.pixelSize: 25
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
            GridView {
                id: liveGrid
                y: 270; x: -40; width: 1500; height: 3 * 176 + 60
                cellWidth: 356; cellHeight: 176
                interactive: false; clip: false
                topMargin: 27; leftMargin: 27
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
            Marquee {   // titre du live choisi, en entier
                y: 290 + 3 * 176 + 40; width: 1400; pixelSize: 24; color: "#e0c8d0"; running: true
                readonly property string login: (menu.st.streamers || [])[menu.liveSel] || ""
                readonly property var info: (menu.st.live || {})[login]
                visible: menu.area === "content" && menu.shortcut < 0 && !!info
                text: info ? login + "  ·  " + info.title : ""
            }
            Text {
                visible: !(menu.st.streamers || []).length
                y: 280; text: "La liste est vide : ajoute des streamers depuis la télécommande web."
                color: "#c2afb4"; font.pixelSize: 27
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
                Text { text: "Télécommande web → Réglages → Chaînes suivies : tout y est expliqué."; color: "#c2afb4"; font.pixelSize: 22 }
            }
            Item {
                visible: !!followsPage.f.configured && !followsPage.f.authorized
                anchors.fill: parent
                Column {
                    visible: followsPage.waiting
                    y: 260; spacing: 26
                    Text { text: "Sur ton téléphone, ouvre twitch.tv/activate et tape :"; color: "white"; font.pixelSize: 27 }
                    Text { text: followsPage.pend ? followsPage.pend.user_code || "" : ""; color: "white"; font.pixelSize: 75; font.bold: true; font.letterSpacing: 12 }
                    Text { text: "ou scanne le QR code. La TV se met à jour toute seule."; color: "#c2afb4"; font.pixelSize: 22 }
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
            GridView {
                visible: !!followsPage.f.authorized
                y: 176; x: -40; width: 1500; height: 4 * 176 + 60
                cellWidth: 356; cellHeight: 176
                interactive: false; clip: false; topMargin: 27; leftMargin: 27
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

        // --- Rediffusions
        Item {
            anchors.fill: parent
            visible: menu.tabId === "replays"
            readonly property var rows: menu.replayRows()
            ListView {   // puces des streamers
                y: 166; x: -40; width: 1500; height: 116
                orientation: ListView.Horizontal; spacing: 16; interactive: false; clip: false
                leftMargin: 40; topMargin: 26
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
                    opacity: rel > -width / 2 && rel + width / 2 < ListView.view.width ? 1 : 0
                    Behavior on opacity { NumberAnimation { duration: 150 } }
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
                    y: 290 + index * 372; width: 1460; height: 360
                    Text { x: 2; text: row ? row.title.toUpperCase() : ""; color: "#c09fa9"; font.pixelSize: 20; font.bold: true; font.letterSpacing: 2 }
                    ListView {
                        y: 4; x: -40; width: 1500; height: 370
                        orientation: ListView.Horizontal; spacing: 26; interactive: false; clip: false
                        leftMargin: 40; topMargin: 38
                        model: row ? row.items.length : 0
                        currentIndex: menu.rpSel[r] || 0
                        onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)
                        Behavior on contentX { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }
                        delegate: VideoCard {
                            readonly property var it: row.items[index] || {}
                            readonly property real rel: x - ListView.view.contentX
                            opacity: rel > -width / 2 && rel + width / 2 < ListView.view.width ? 1 : 0
                            Behavior on opacity { NumberAnimation { duration: 150 } }
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

        // --- Historique
        GridView {
            visible: menu.tabId === "history"
            y: 176; x: -40; width: 1500; height: 2 * 340 + 60
            cellWidth: 356; cellHeight: 340
            interactive: false; clip: false; topMargin: 27; leftMargin: 27
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
                    focused: menu.area === "content" && index === menu.histSel
                }
            }
        }

        // --- Réglages et Système : listes de lignes
        Repeater {
            model: ["settings", "system"]
            ListView {
                id: rowsView
                visible: menu.tabId === modelData
                readonly property var rows: modelData === "settings" ? menu.settingsRows() : menu.systemRows()
                readonly property var sel: menu.selectable(rows)
                readonly property int focusedRow: menu.area === "content" ? sel[modelData === "settings" ? menu.setSel : menu.sysSel] : -1
                y: 180; x: -40; width: modelData === "settings" ? 1060 : 890; height: 880
                spacing: 10; interactive: false; clip: false; topMargin: 30; leftMargin: 40
                model: rows.length
                onFocusedRowChanged: if (focusedRow >= 0) positionViewAtIndex(focusedRow, ListView.Contain)
                Behavior on contentY { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
                delegate: SettingRow {
                    width: rowsView.width - 80
                    readonly property real rel: y - rowsView.contentY
                    opacity: rel > -height / 2 && rel + height / 2 < rowsView.height ? 1 : 0
                    Behavior on opacity { NumberAnimation { duration: 150 } }
                    row: rowsView.rows[index] || {}
                    focused: index === rowsView.focusedRow
                }
            }
        }
        Column {   // Système : QR code de la télécommande web, pour tout ce qui demande de taper du texte
            visible: menu.tabId === "system" && !!(menu.ambient.qr && menu.ambient.qr.rows)
            x: 880; y: 230; spacing: 16
            QrCode { size: 300; rows: menu.ambient.qr ? menu.ambient.qr.rows : [] }
            Text { text: "Télécommande sur le téléphone"; color: "white"; font.pixelSize: 23; font.bold: true }
            Text { text: "Lien, streamer, compte Twitch…"; color: "#c2afb4"; font.pixelSize: 20 }
            Text { text: menu.ambient.qr ? String(menu.ambient.qr.url).replace(/^https?:\/\//, "").replace(/\/$/, "") : ""; color: "#c2afb4"; font.pixelSize: 20 }
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
            color: "#2c1821"
            scale: menu.modal ? 1 : 0.92
            Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutBack } }
            Marquee { x: 44; y: 46; width: parent.width - 88; text: menu.modal ? menu.modal.title || "" : ""; pixelSize: 27; bold: true; running: !!menu.modal }
            Repeater {
                model: sheet.items.length
                Rectangle {
                    readonly property bool foc: index === menu.modalSel
                    x: 30; y: 112 + index * 92; width: sheet.width - 60; height: 76; radius: 38
                    color: foc ? "white" : "#3f2833"
                    Behavior on color { ColorAnimation { duration: 140 } }
                    Text {
                        x: 40; anchors.verticalCenter: parent.verticalCenter
                        text: sheet.items[index] ? sheet.items[index].label : ""
                        color: parent.foc ? "#20101a" : (sheet.items[index] && sheet.items[index].danger ? "#ff8f8f" : "white")
                        font.pixelSize: 26; font.bold: parent.foc
                    }
                }
            }
        }
    }
}
