// Bandeau du bas (appli Qt), affiché quand stream-box.lua le décide (OK pendant un direct, ←/→ ou pause en vidéo) :
// direct (photo, titre, jeu, spectateurs, durée du live, mémoire du différé et « EN DIRECT » ou le retard) ou barre de
// lecture d'une vidéo (titre, chaîne ou série, chapitre, position, partie chargée, repères de chapitres, aperçu YouTube
// au-dessus du curseur, saut en cours « +30 s », temps restant et heure de fin, rangée de boutons). Monte en glissant.
import QtQuick
import QtQuick.Effects
import "fmt.js" as Fmt

Item {
    id: root
    anchors.fill: parent
    readonly property var b: { try { return JSON.parse(osd.bar || "{}") } catch (e) { return {} } }
    readonly property var pb: b.playback || {}
    readonly property bool live: b.mode === "twitch"
    readonly property var info: (b.live || {})[b.channel] || null
    readonly property var board: { try { return JSON.parse(osd.storyboard || "{}") } catch (e) { return {} } }
    readonly property bool shown: !!b.bar && (b.mode === "twitch" || b.mode === "media")
    property var avatars: ({})
    // Barre : en direct, la mémoire du différé (son bout droit est le direct) ; en vidéo, la durée
    readonly property real span: live ? (pb.window ? pb.window[1] - pb.window[0] : 0) : (pb.duration || 0)
    readonly property real at: live ? (pb.window ? (pb.pos || 0) - pb.window[0] : 0) : (pb.pos || 0)
    readonly property real delay: live && pb.window ? pb.window[1] - (pb.pos || 0) : 0
    // Couleur de la barre selon la source : rouge YouTube, bleu Jellyfin (lien de son serveur : /Videos/…), sinon le
    // violet de Twitch
    readonly property string source: live ? "twitch" : /youtube\.com|youtu\.be|googlevideo/.test(pb.path || "") ? "youtube"
        : /\/Videos\/|\/videos\/[0-9a-f]{32}|api_key=|MediaSourceId=/i.test(pb.path || "") ? "jellyfin" : "other"
    readonly property var colors: source === "youtube" ? ["#ff0033", "#ff4e45"]
        : source === "jellyfin" ? ["#1565c0", "#4a90e2"] : ["#8a3ffc", "#b062ff"]
    // Vidéo : infos (remote.py : chaîne, série, épisode…), chapitres (mpv), boutons et saut (stream-box.lua)
    readonly property var meta: { try { return JSON.parse(osd.meta || "{}") } catch (e) { return {} } }
    readonly property var ctl: { try { return JSON.parse(osd.controls || "{}") } catch (e) { return {} } }
    readonly property var fx: { try { return JSON.parse(osd.seekfx || "{}") } catch (e) { return {} } }
    readonly property var chapters: pb.chapters || []
    readonly property string chapterTitle: {
        var c = chapters[pb.chapter]
        return c && chapters.length > 1 ? "Chapitre " + (pb.chapter + 1) + (c.title && !/^Chapter \d+$/i.test(c.title) ? " · " + c.title : "") : ""
    }
    readonly property string details: (meta.source === "youtube" ? [meta.channel, meta.date, meta.views ? Fmt.big(meta.views) + " vues" : ""]
        : meta.source === "jellyfin" ? [meta.year, meta.rating ? "★ " + Number(meta.rating).toFixed(1).replace(".", ",") : ""]   // série et épisode : déjà dans le titre
        : []).concat([chapterTitle]).filter(function (t) { return !!t }).join("  ·  ")
    property date now: new Date()
    Timer { interval: 15000; repeat: true; running: root.visible; triggeredOnStart: true; onTriggered: root.now = new Date() }
    readonly property real remaining: Math.max(0, span - at)
    readonly property string endsAt: Qt.formatTime(new Date(now.getTime() + remaining * 1000), "hh:mm")

    opacity: shown ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 220 } }
    onShownChanged: if (shown && live && !avatars[b.channel]) loadAvatars()

    function loadAvatars() {
        var x = new XMLHttpRequest()
        x.onreadystatechange = function () {
            if (x.readyState === XMLHttpRequest.DONE && x.status === 200)
                try { root.avatars = JSON.parse(x.responseText).avatars || {} } catch (e) {}
        }
        x.open("GET", "http://127.0.0.1:8080/api/state")
        x.send()
    }

    Item {
        id: panel
        width: parent.width
        // En vidéo, plus haut : l'aperçu YouTube s'affiche entre le titre et la barre
        height: root.live ? 300 : 520
        y: root.shown ? parent.height - height : parent.height - height + 60
        Behavior on y { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }

        Rectangle {   // fondu vers le noir en bas de l'écran
            anchors.fill: parent
            gradient: Gradient {
                // plus sombre plus tôt : le titre, en haut du bandeau, reste lisible sur une image claire
                GradientStop { position: 0.0; color: "#00000000" }
                GradientStop { position: 0.22; color: "#99000000" }
                GradientStop { position: 0.55; color: "#cc000000" }
                GradientStop { position: 1.0; color: "#ee000000" }
            }
        }

        // En-tête : photo du streamer (direct) ou symbole pause (vidéo), titre, ligne d'infos
        Row {
            x: 96; y: root.live ? 70 : 60
            spacing: 22
            layer.enabled: true   // ombre sous les textes, lisibles quel que soit l'image derrière
            layer.effect: MultiEffect { shadowEnabled: true; shadowColor: "black"; shadowBlur: 0.7; shadowOpacity: 0.9; shadowVerticalOffset: 2 }
            Rectangle {
                visible: root.live
                width: 82; height: 82; radius: 41
                color: root.info ? "#ff4f5e" : "#4a3d5c"
                anchors.verticalCenter: parent.verticalCenter
                RoundImage {
                    anchors.centerIn: parent; width: 74; height: 74; circle: true; placeholder: "#4a3d5c"
                    source: root.avatars[root.b.channel] || ""
                }
            }
            Row {   // pause (vidéo : PauseScreen.qml affiche déjà la grande icône)
                visible: false
                spacing: 9
                anchors.verticalCenter: parent.verticalCenter
                Rectangle { width: 12; height: 38; radius: 3; color: "white" }
                Rectangle { width: 12; height: 38; radius: 3; color: "white" }
            }
            Column {
                width: 1500
                anchors.verticalCenter: parent.verticalCenter
                spacing: 4
                Marquee {
                    width: parent.width
                    text: root.live ? (root.b.channel || "") + (root.info && root.info.title ? "  ·  " + root.info.title : "")
                                    : (root.pb.title || "")
                    pixelSize: 31; bold: true; running: root.shown
                }
                Text {   // vidéo : chaîne ou série, épisode, chapitre
                    visible: !root.live && !!root.details
                    width: parent.width; elide: Text.ElideRight
                    text: root.details
                    color: "#d0c8e0"; font.pixelSize: 22
                }
                Text {
                    visible: root.live && !!root.info
                    text: root.info ? [root.info.game, Fmt.viewers(root.info.viewers) + " spectateurs",
                                       root.info.started ? "en live depuis " + Fmt.since(root.info.started) : ""]
                                      .filter(function (t) { return !!t }).join("  ·  ") : ""
                    color: "#d0c8e0"; font.pixelSize: 22
                }
            }
        }

        // Barre
        Item {
            id: track
            x: 96; y: root.live ? 200 : 330
            width: parent.width - 192
            height: 8
            readonly property real played: root.span > 0 ? Math.max(0, Math.min(1, root.at / root.span)) : 0
            Rectangle { anchors.fill: parent; radius: 4; color: "#40ffffff" }
            Rectangle {   // partie chargée (vidéo)
                visible: !root.live && root.span > 0 && (root.pb.cached || 0) > root.at
                height: parent.height; radius: 4; color: "#70ffffff"
                width: parent.width * Math.min(1, (root.pb.cached || 0) / Math.max(1, root.span))
            }
            Rectangle {
                height: parent.height; radius: 4
                width: parent.width * track.played
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: root.colors[0] }
                    GradientStop { position: 1; color: root.colors[1] }
                }
                Behavior on width { NumberAnimation { duration: 240 } }
            }
            Repeater {   // repères des chapitres
                model: root.live || root.span <= 0 ? 0 : root.chapters.length
                Rectangle {
                    visible: index > 0
                    x: track.width * Math.min(1, root.chapters[index].time / root.span) - 2
                    width: 4; height: 16; radius: 2; anchors.verticalCenter: parent.verticalCenter
                    color: "#d0ffffff"
                }
            }
            Rectangle {   // curseur
                width: 22; height: 22; radius: 11; color: "white"
                x: track.width * track.played - width / 2
                anchors.verticalCenter: parent.verticalCenter
                Behavior on x { NumberAnimation { duration: 240 } }
            }
            // Aperçu YouTube au-dessus du curseur : une case de la planche de miniatures
            Item {
                id: preview
                readonly property var bd: root.board
                readonly property bool ok: !root.live && !!(bd.fragments && bd.fragments.length) && root.span > 0
                readonly property var tile: {
                    if (!ok) return null
                    var t = root.at, start = 0
                    for (var i = 0; i < bd.fragments.length; i++) {
                        var f = bd.fragments[i], d = f.duration || 1
                        if (t < start + d || i === bd.fragments.length - 1) {
                            var per = d / (bd.rows * bd.columns)
                            var idx = Math.min(bd.rows * bd.columns - 1, Math.floor((t - start) / per))
                            return { url: f.url, col: idx % bd.columns, row: Math.floor(idx / bd.columns) }
                        }
                        start += d
                    }
                    return null
                }
                readonly property real s: 280 / Math.max(1, bd.width || 160)
                visible: ok && !!tile
                width: (bd.width || 160) * s
                height: (bd.height || 90) * s
                x: Math.max(0, Math.min(track.width - width, track.width * track.played - width / 2))
                y: -height - 26
                Rectangle { anchors.fill: parent; anchors.margins: -3; radius: 10; color: "white" }
                Item {
                    anchors.fill: parent
                    clip: true
                    Image {
                        source: preview.tile ? preview.tile.url : ""
                        asynchronous: true; cache: true
                        width: (preview.bd.width || 160) * preview.bd.columns * preview.s
                        height: (preview.bd.height || 90) * preview.bd.rows * preview.s
                        x: preview.tile ? -preview.tile.col * preview.width : 0
                        y: preview.tile ? -preview.tile.row * preview.height : 0
                    }
                }
            }
        }
        // Saut en cours au-dessus du curseur (« +30 s », total des appuis rapprochés), le temps d'un instant
        Rectangle {
            id: seekBubble
            property int lastN: -1
            visible: opacity > 0
            opacity: 0
            readonly property real cx: track.x + track.width * (root.span > 0 ? Math.min(1, root.at / root.span) : 0)
            x: Math.max(track.x, Math.min(track.x + track.width - width, cx - width / 2))
            y: track.y - height - 30 - (preview.visible ? preview.height + 10 : 0)
            width: fxText.implicitWidth + 44; height: 58; radius: 29
            color: "#ee17151c"; border.color: root.colors[0]; border.width: 2
            Text { id: fxText; anchors.centerIn: parent; text: root.fx.text || ""; color: "white"; font.pixelSize: 28; font.bold: true }
            Connections {
                target: root
                function onFxChanged() {
                    if (root.fx.n !== undefined && root.fx.n !== seekBubble.lastN) {
                        seekBubble.lastN = root.fx.n
                        seekBubble.opacity = 1
                        fxHide.restart()
                    }
                }
            }
            Timer { id: fxHide; interval: 1100; onTriggered: seekBubble.opacity = 0 }
            Behavior on opacity { NumberAnimation { duration: 200 } }
        }
        Text {
            x: 96; y: track.y + 26
            visible: !root.live
            text: Fmt.clock(root.at) + "  /  " + Fmt.clock(root.span)
            color: "white"; font.pixelSize: 23
        }
        Text {
            anchors.right: track.right; y: track.y + 26
            text: root.live ? (root.delay < 4 ? "● EN DIRECT" : "−" + Fmt.clock(root.delay))
                            : root.span > 0 ? "−" + Fmt.clock(root.remaining) + "   ·   fin à " + root.endsAt : ""
            color: root.live && root.delay < 4 ? "#ff4f5e" : "white"
            font.pixelSize: 23; font.bold: root.live && root.delay < 4
        }
        // Rangée de boutons (vidéo) : ↓ pour y aller, ← → et OK ; discrète tant qu'aucun n'est choisi
        Row {
            visible: !root.live && (root.ctl.items || []).length > 0
            x: 96; y: track.y + 86
            spacing: 14
            opacity: root.ctl.focus >= 0 ? 1 : 0.55
            Behavior on opacity { NumberAnimation { duration: 160 } }
            Repeater {
                model: (root.ctl.items || []).length
                Rectangle {
                    readonly property var it: root.ctl.items[index] || {}
                    readonly property bool foc: index === root.ctl.focus
                    width: btnText.implicitWidth + 56; height: 56; radius: 28
                    color: foc ? "white" : "#26ffffff"
                    border.color: foc ? "white" : "#40ffffff"; border.width: 1
                    scale: foc ? 1.06 : 1
                    Behavior on scale { NumberAnimation { duration: 140 } }
                    Behavior on color { ColorAnimation { duration: 140 } }
                    Text {
                        id: btnText
                        anchors.centerIn: parent
                        text: ({ back: "⟲  ", play: root.pb.pause ? "▶  " : "❚❚  ", fwd: "⟳  ", tracks: "≡  ", chapter: "⏭  ", next: "▶▶  " }[it.id] || "") + (it.label || "")
                        color: parent.foc ? "#17151c" : "white"; font.pixelSize: 22; font.bold: parent.foc
                    }
                }
            }
            Text {
                visible: root.ctl.focus < 0
                anchors.verticalCenter: parent.verticalCenter
                text: "↓ commandes"
                color: "#a0ffffff"; font.pixelSize: 20
            }
        }
    }
}
