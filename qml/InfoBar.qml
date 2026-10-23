// Bandeau du bas (appli Qt), affiché quand stream-box.lua le décide (OK pendant un direct, ←/→ ou pause en vidéo) :
// direct (photo, titre, jeu, spectateurs, durée du live, mémoire du différé et « EN DIRECT » ou le retard) ou barre de
// lecture d'une vidéo (titre, position, partie chargée, aperçu YouTube au-dessus du curseur). Monte en glissant.
import QtQuick
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
        height: root.live ? 300 : 420
        y: root.shown ? parent.height - height : parent.height - height + 60
        Behavior on y { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }

        Rectangle {   // fondu vers le noir en bas de l'écran
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#00000000" }
                GradientStop { position: 0.45; color: "#a0000000" }
                GradientStop { position: 1.0; color: "#e6000000" }
            }
        }

        // En-tête : photo du streamer (direct) ou symbole pause (vidéo), titre, ligne d'infos
        Row {
            x: 96; y: root.live ? 70 : 60
            spacing: 22
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
            Row {   // pause
                visible: !root.live && !!root.pb.pause
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
            x: 96; y: root.live ? 200 : 320
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
                    GradientStop { position: 0; color: "#8a3ffc" }
                    GradientStop { position: 1; color: "#b062ff" }
                }
                Behavior on width { NumberAnimation { duration: 240 } }
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
        Text {
            x: 96; y: track.y + 26
            visible: !root.live
            text: Fmt.clock(root.at)
            color: "white"; font.pixelSize: 23
        }
        Text {
            anchors.right: track.right; y: track.y + 26
            text: root.live ? (root.delay < 4 ? "● EN DIRECT" : "−" + Fmt.clock(root.delay)) : Fmt.clock(root.span)
            color: root.live && root.delay < 4 ? "#ff4f5e" : "white"
            font.pixelSize: 23; font.bold: root.live && root.delay < 4
        }
    }
}
