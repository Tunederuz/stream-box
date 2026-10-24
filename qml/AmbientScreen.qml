// Écran d'accueil de la TV en QML (appli Qt) : affiché quand stream-box.lua le décide (box.ambientOn : chaîne hors
// ligne, liste vide, mode accueil). Fond « aurore » de taches floues qui dérivent, horloge, date, météo dessinée,
// prochains lives (plannings Twitch de remote.py), streamers en live, message d'état, QR code de la télécommande.
// Tout le contenu dérive lentement, pour ne pas marquer l'écran. Coordonnées en 1920x1080.
import QtQuick
import QtQuick.Effects
import "fmt.js" as Fmt

Item {
    id: root
    anchors.fill: parent
    readonly property var ambient: { try { return JSON.parse(box.ambient || "{}") } catch (e) { return {} } }
    readonly property var weather: ambient.weather || null
    readonly property var schedule: setup ? [] : (ambient.schedule || [])
    // Mode configuration (netsetup.py) : point d'accès Wi-Fi de la box, ou connexion en cours à un réseau
    readonly property var setup: ambient.setup || null
    property var st: ({})                     // /api/state : photos, streamers en live
    property date now: new Date()
    property bool qrShown: true
    // QR code affiché (réglage : toujours, 30 secondes à chaque arrivée, jamais)
    readonly property bool qrWanted: !!(ambient.qr && ambient.qr.rows) && (box.qrMode === "always" || (box.qrMode === "timed" && qrShown))
    readonly property var liveOthers: {
        var out = [], live = st.live || {}
        for (var i = 0; i < (st.streamers || []).length; i++) {
            var n = st.streamers[i]
            if (live[n] && !(st.mode === "twitch" && st.channel === n && box.videoActive)) out.push(n)
        }
        return out
    }
    opacity: box.ambientOn ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 600; easing.type: Easing.InOutQuad } }

    function refresh() {
        var x = new XMLHttpRequest()
        x.onreadystatechange = function () {
            if (x.readyState === XMLHttpRequest.DONE && x.status === 200) {
                try { root.st = JSON.parse(x.responseText) } catch (e) {}
            }
        }
        x.open("GET", "http://127.0.0.1:8080/api/state")
        x.send()
    }
    Timer { interval: 20000; repeat: true; running: root.visible; triggeredOnStart: true; onTriggered: root.refresh() }
    Timer { interval: 1000; repeat: true; running: root.visible; triggeredOnStart: true; onTriggered: root.now = new Date() }
    // QR code « 30 secondes » : affiché à chaque arrivée sur l'écran d'accueil
    Timer { id: qrTimer; interval: 30000; onTriggered: root.qrShown = false }
    Connections {
        target: box
        function onAmbientOnChanged() { if (box.ambientOn) { root.qrShown = true; qrTimer.restart(); root.refresh() } }
    }

    // Fond : presque noir, et des taches de couleur très floues qui dérivent lentement (ombres rectangulaires
    // arrondies en disque : flou calculé par la puce graphique, sans calque)
    Rectangle { anchors.fill: parent; color: "#0b0710" }
    Repeater {
        model: [{ c: "#9146ff", o: 0.42, s: 700, x0: 200, y0: 120, dx: 520, dy: 260, d: 47000 },
                { c: "#2b4bdc", o: 0.30, s: 640, x0: 1150, y0: 420, dx: -480, dy: -220, d: 61000 },
                { c: "#b03a7a", o: 0.28, s: 560, x0: 700, y0: 650, dx: 380, dy: -300, d: 53000 },
                { c: "#5b2bdc", o: 0.25, s: 520, x0: 1400, y0: 60, dx: -300, dy: 340, d: 71000 }]
        RectangularShadow {
            width: modelData.s; height: modelData.s; radius: modelData.s / 2
            blur: 260; spread: 0
            color: modelData.c; opacity: modelData.o
            x: modelData.x0; y: modelData.y0
            SequentialAnimation on x {
                loops: Animation.Infinite
                NumberAnimation { to: modelData.x0 + modelData.dx; duration: modelData.d; easing.type: Easing.InOutSine }
                NumberAnimation { to: modelData.x0; duration: modelData.d; easing.type: Easing.InOutSine }
            }
            SequentialAnimation on y {
                loops: Animation.Infinite
                NumberAnimation { to: modelData.y0 + modelData.dy; duration: modelData.d * 0.8; easing.type: Easing.InOutSine }
                NumberAnimation { to: modelData.y0; duration: modelData.d * 0.8; easing.type: Easing.InOutSine }
            }
        }
    }

    // Contenu, qui dérive de quelques dizaines de pixels sur plusieurs minutes (écran de TV : pas d'image fixe)
    Item {
        id: content
        width: parent.width
        height: parent.height
        SequentialAnimation on x {
            loops: Animation.Infinite
            NumberAnimation { to: 36; duration: 420000; easing.type: Easing.InOutSine }
            NumberAnimation { to: -36; duration: 420000; easing.type: Easing.InOutSine }
        }
        SequentialAnimation on y {
            loops: Animation.Infinite
            NumberAnimation { to: 24; duration: 660000; easing.type: Easing.InOutSine }
            NumberAnimation { to: -24; duration: 660000; easing.type: Easing.InOutSine }
        }

        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            y: 110
            spacing: 6
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: Qt.formatTime(root.now, "hh:mm")
                color: "white"
                font.pixelSize: 210
                font.weight: Font.Light
                font.letterSpacing: -4
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.now.toLocaleDateString(Qt.locale("fr_FR"), "dddd d MMMM")
                color: "#d0c8e0"
                font.pixelSize: 40
            }
            Item { width: 1; height: 22 }
            Row {   // météo
                visible: !!root.weather
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 22
                WeatherIcon {
                    anchors.verticalCenter: parent.verticalCenter
                    width: 84; height: 84
                    code: root.weather ? root.weather.code || 0 : 0
                    night: root.now.getHours() >= 20 || root.now.getHours() < 7
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.weather ? root.weather.temp + "°" : ""
                    color: "white"; font.pixelSize: 56; font.weight: Font.Light
                }
                Column {
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2
                    Text { text: root.weather ? (root.weather.city ? root.weather.city + "  ·  " : "") + root.weather.text : ""; color: "white"; font.pixelSize: 28 }
                    Text {
                        text: root.weather ? root.weather.min + "° / " + root.weather.max + "°"
                              + (root.weather.rain >= 30 ? "  ·  pluie " + root.weather.rain + " %" : "") : ""
                        color: "#b4afc2"; font.pixelSize: 24
                    }
                }
            }
        }

        // En live maintenant (streamers de la liste qu'on ne regarde pas)
        Column {
            visible: root.liveOthers.length > 0 && !root.setup
            anchors.horizontalCenter: parent.horizontalCenter
            y: 625
            spacing: 14
            Text { anchors.horizontalCenter: parent.horizontalCenter; text: "EN LIVE MAINTENANT"; color: "#ff7f8a"; font.pixelSize: 20; font.bold: true; font.letterSpacing: 3 }
            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 14
                Repeater {
                    model: root.liveOthers.slice(0, 5)
                    Rectangle {
                        readonly property var info: (root.st.live || {})[modelData] || {}
                        width: chipRow.width + 36; height: 60; radius: 30
                        color: "#1affffff"; border.color: "#26ffffff"; border.width: 1
                        Row {
                            id: chipRow
                            x: 10; anchors.verticalCenter: parent.verticalCenter; spacing: 12
                            Rectangle {   // anneau rouge des lives
                                width: 44; height: 44; radius: 22; color: "#ff4f5e"
                                anchors.verticalCenter: parent.verticalCenter
                                RoundImage { anchors.centerIn: parent; width: 38; height: 38; circle: true; source: (root.st.avatars || {})[modelData] || "" }
                            }
                            Text { anchors.verticalCenter: parent.verticalCenter; text: modelData; color: "white"; font.pixelSize: 24; font.bold: true }
                            Text { anchors.verticalCenter: parent.verticalCenter; text: "● " + Fmt.viewers(info.viewers); color: "#ff7f8a"; font.pixelSize: 21 }
                        }
                    }
                }
            }
        }

        // Prochains lives : cartes de verre
        Column {
            visible: root.schedule.length > 0
            anchors.horizontalCenter: parent.horizontalCenter
            y: root.liveOthers.length > 0 ? 770 : 660
            spacing: 18
            Behavior on y { NumberAnimation { duration: 400; easing.type: Easing.OutCubic } }
            Text { anchors.horizontalCenter: parent.horizontalCenter; text: "PROCHAINS LIVES"; color: "#a99fc0"; font.pixelSize: 20; font.bold: true; font.letterSpacing: 3 }
            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 18
                Repeater {
                    model: root.schedule.slice(0, root.qrWanted ? 3 : 4)
                    Rectangle {   // cartes de 330 : 3 quand le QR code est affiché en bas à droite, pour ne pas le toucher
                        width: 330; height: 108; radius: 24
                        color: "#14ffffff"; border.color: "#22ffffff"; border.width: 1
                        RoundImage {
                            x: 20; anchors.verticalCenter: parent.verticalCenter
                            width: 64; height: 64; circle: true; placeholder: "#4a3d5c"
                            source: (root.st.avatars || {})[modelData.login] || ""
                            Text { anchors.centerIn: parent; z: -1; text: (modelData.login || "?").charAt(0).toUpperCase(); color: "#d0c8e0"; font.pixelSize: 28; font.bold: true }
                        }
                        Column {
                            x: 100; width: parent.width - 120
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 2
                            Text { width: parent.width; text: modelData.login; color: "white"; font.pixelSize: 25; font.bold: true; elide: Text.ElideRight }
                            Text { width: parent.width; text: modelData.when; color: "#c9b8ff"; font.pixelSize: 21; elide: Text.ElideRight }
                            Text { width: parent.width; visible: !!modelData.title; text: modelData.title || ""; color: "#b4afc2"; font.pixelSize: 19; elide: Text.ElideRight }
                        }
                    }
                }
            }
        }

        Text {   // message d'état (« X n'est pas en live, nouvel essai dans 15 s »…)
            anchors.horizontalCenter: parent.horizontalCenter
            y: 1010
            text: box.statusText
            color: "#8a85a0"
            font.pixelSize: 20
        }

        // Mode configuration : 1. rejoindre le Wi-Fi de la box (QR code Wi-Fi, ou nom et mot de passe), 2. ouvrir la page
        Item {
            visible: !!root.setup
            anchors.horizontalCenter: parent.horizontalCenter
            y: 560; width: 1300; height: 420
            Text {
                visible: !!(root.setup && root.setup.connecting)
                anchors.centerIn: parent
                text: root.setup && root.setup.connecting ? "Connexion au Wi-Fi « " + root.setup.connecting + " »…" : ""
                color: "white"; font.pixelSize: 36
            }
            Column {
                visible: !!(root.setup && root.setup.ssid)
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 22
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "CONFIGURATION"; color: "#c9b8ff"; font.pixelSize: 22; font.bold: true; font.letterSpacing: 4
                }
                Text {
                    visible: !!(root.setup && root.setup.error)
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: root.setup ? root.setup.error || "" : ""; color: "#ff8f8f"; font.pixelSize: 22
                }
                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 90
                    Repeater {
                        model: root.setup && root.setup.ssid ? [
                            { n: "1", title: "Connecte ton téléphone", rows: root.setup.wifi_rows,
                              lines: ["Wi-Fi « " + root.setup.ssid + " »", "Mot de passe : " + root.setup.password] },
                            { n: "2", title: "Ouvre la configuration", rows: root.setup.url_rows,
                              lines: [String(root.setup.url).replace(/^http:\/\//, "").replace(/\/$/, ""), "Choisis le Wi-Fi de la maison"] }] : []
                        Row {
                            spacing: 26
                            QrCode { size: 220; rows: modelData.rows || [] }
                            Column {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 10
                                Rectangle {
                                    width: 52; height: 52; radius: 26; color: "#9146ff"
                                    Text { anchors.centerIn: parent; text: modelData.n; color: "white"; font.pixelSize: 28; font.bold: true }
                                }
                                Text { text: modelData.title; color: "white"; font.pixelSize: 30; font.bold: true }
                                Repeater {
                                    model: modelData.lines
                                    Text { text: modelData; color: "#d0c8e0"; font.pixelSize: 24 }
                                }
                            }
                        }
                    }
                }
            }
        }

        // QR code de la télécommande, selon le réglage (toujours, 30 secondes à chaque arrivée, jamais)
        Column {
            visible: opacity > 0 && !!(root.ambient.qr && root.ambient.qr.rows) && !root.setup
            opacity: root.qrWanted ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 500 } }
            x: 1920 - 56 - width; y: 1080 - 44 - height
            spacing: 10
            Text { anchors.horizontalCenter: parent.horizontalCenter; text: "Télécommande"; color: "#b4afc2"; font.pixelSize: 21 }
            QrCode { anchors.horizontalCenter: parent.horizontalCenter; size: 230; rows: root.ambient.qr ? root.ambient.qr.rows : [] }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.ambient.qr ? String(root.ambient.qr.url).replace(/^https?:\/\//, "").replace(/\/$/, "") : ""
                color: "#8a85a0"; font.pixelSize: 18
            }
        }
    }
}
