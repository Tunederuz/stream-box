// TV home screen in QML (Qt app): shown when stream-box.lua decides so (box.ambientOn: channel offline, empty list,
// home mode). "Aurora" background of drifting blurry blobs, clock, date, drawn weather, upcoming lives (Twitch
// schedules from remote.py), live streamers, status message, QR code of the companion app.
// All the content drifts slowly, so as not to burn in the screen. Coordinates in 1920x1080.
import QtQuick
import QtQuick.Effects
import "fmt.js" as Fmt
import "i18n.js" as I18n

Item {
    id: root
    anchors.fill: parent
    function tr(s, a) { return I18n.t(i18n.dict, s, a) }
    readonly property var ambient: { try { return JSON.parse(box.ambient || "{}") } catch (e) { return {} } }
    readonly property var weather: ambient.weather || null
    readonly property var schedule: setup ? [] : (ambient.schedule || [])
    // Setup mode (netsetup.py): Wi-Fi access point of the box, or connection to a network in progress
    readonly property var setup: ambient.setup || null
    // First setup not done yet (remote.py, setup-done): large QR code of the page, nothing else
    readonly property bool firstRun: !!ambient.first_run && !setup
    property var st: ({})                     // /api/state: photos, live streamers
    // Animated background: from the last state read, here (every 20 s) or by the open menu (ui.qml, fresher)
    property var backdrop: null
    property var bd: ({})
    onBackdropChanged: if (backdrop) bd = backdrop
    onStChanged: if (st.backdrop) bd = st.backdrop
    property date now: new Date()
    property bool qrShown: true
    // QR code shown (setting: always, 30 seconds on each arrival, never)
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
    // "30 seconds" QR code: shown on each arrival on the home screen
    Timer { id: qrTimer; interval: 30000; onTriggered: root.qrShown = false }
    Connections {
        target: box
        function onAmbientOnChanged() { if (box.ambientOn) { root.qrShown = true; qrTimer.restart(); root.refresh() } }
    }

    // Animated background, chosen in Settings (Backdrop.qml)
    // Colors to choose from (Settings → "Home colors"): three hues and the almost black background
    readonly property var palettes: ({
        violet: ["#9146ff", "#2b4bdc", "#b03a7a", "#0b0710"], blue: ["#2f7bff", "#1fb5c9", "#4b3cdc", "#050a14"],
        green: ["#1ed68a", "#1a9fb0", "#6fcf3a", "#04100b"], sunset: ["#ff7a2f", "#ff3d6e", "#ffc23d", "#120806"],
        pink: ["#ff4fa3", "#9b4dff", "#ff7b6b", "#12060d"], ice: ["#cfd8ff", "#7fa8ff", "#b9a6ff", "#08090f"] })
    readonly property var pal: palettes[bd.color] || palettes.violet
    Backdrop {
        anchors.fill: parent; base: root.bd.base || "aurora"; overlay: root.bd.overlay || "none"; running: root.visible
        c1: root.pal[0]; c2: root.pal[1]; c3: root.pal[2]; bg: root.pal[3]
        Behavior on c1 { ColorAnimation { duration: 800 } }
        Behavior on c2 { ColorAnimation { duration: 800 } }
        Behavior on c3 { ColorAnimation { duration: 800 } }
        Behavior on bg { ColorAnimation { duration: 800 } }
    }

    // Content, drifting by a few tens of pixels over several minutes (TV screen: no still image)
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
                text: root.now.toLocaleDateString(Qt.locale(i18n.lang), root.tr("dddd, MMMM d"))
                color: "#d0c8e0"
                font.pixelSize: 40
            }
            Item { width: 1; height: 22 }
            Row {   // weather
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
                              + (root.weather.rain >= 30 ? "  ·  " + root.tr("rain {n}%", { n: root.weather.rain }) : "") : ""
                        color: "#b4afc2"; font.pixelSize: 24
                    }
                }
            }
        }

        // Live now (streamers of the list that we are not watching)
        Column {
            visible: root.liveOthers.length > 0 && !root.setup && !root.firstRun
            anchors.horizontalCenter: parent.horizontalCenter
            y: 625
            spacing: 14
            Text { anchors.horizontalCenter: parent.horizontalCenter; text: root.tr("LIVE NOW"); color: "#ff7f8a"; font.pixelSize: 20; font.bold: true; font.letterSpacing: 3 }
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
                            Rectangle {   // red ring of lives
                                width: 44; height: 44; radius: 22; color: "#ff4f5e"
                                anchors.verticalCenter: parent.verticalCenter
                                RoundImage { anchors.centerIn: parent; width: 38; height: 38; circle: true; source: (root.st.avatars || {})[modelData] || "" }
                            }
                            Text { anchors.verticalCenter: parent.verticalCenter; text: modelData; color: "white"; font.pixelSize: 24; font.bold: true }
                            Text { anchors.verticalCenter: parent.verticalCenter; text: "● " + Fmt.viewers(info.viewers, root.tr); color: "#ff7f8a"; font.pixelSize: 21 }
                        }
                    }
                }
            }
        }

        // Upcoming lives: glass cards
        Column {
            visible: root.schedule.length > 0 && !root.firstRun
            anchors.horizontalCenter: parent.horizontalCenter
            y: root.liveOthers.length > 0 ? 770 : 660
            spacing: 18
            Behavior on y { NumberAnimation { duration: 400; easing.type: Easing.OutCubic } }
            Text { anchors.horizontalCenter: parent.horizontalCenter; text: root.tr("UPCOMING LIVES"); color: "#a99fc0"; font.pixelSize: 20; font.bold: true; font.letterSpacing: 3 }
            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 18
                Repeater {
                    model: root.schedule.slice(0, root.qrWanted ? 3 : 4)
                    Rectangle {   // 330-wide cards: 3 when the QR code is shown at the bottom right, so as not to touch it
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

        Text {   // status message ("X is not live, retrying in 15 s"…)
            anchors.horizontalCenter: parent.horizontalCenter
            y: 1010
            text: box.statusText
            color: "#8a85a0"
            font.pixelSize: 20
        }

        // Setup mode: 1. join the Wi-Fi of the box (Wi-Fi QR code, or name and password), 2. open the page
        Item {
            visible: !!root.setup
            anchors.horizontalCenter: parent.horizontalCenter
            y: 560; width: 1300; height: 420
            Text {
                visible: !!(root.setup && root.setup.connecting)
                anchors.centerIn: parent
                text: root.setup && root.setup.connecting ? root.tr("Connecting to Wi-Fi \"{ssid}\"…", { ssid: root.setup.connecting }) : ""
                color: "white"; font.pixelSize: 36
            }
            Column {
                visible: !!(root.setup && root.setup.ssid)
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 22
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: root.tr("SETUP"); color: "#c9b8ff"; font.pixelSize: 22; font.bold: true; font.letterSpacing: 4
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
                            { n: "1", title: root.tr("Connect your phone"), rows: root.setup.wifi_rows,
                              lines: [root.tr("Wi-Fi \"{ssid}\"", { ssid: root.setup.ssid }),
                                      root.tr("Password: {password}", { password: root.setup.password })] },
                            { n: "2", title: root.tr("Open the setup"), rows: root.setup.url_rows,
                              lines: [String(root.setup.url).replace(/^http:\/\//, "").replace(/\/$/, ""), root.tr("Choose your home Wi-Fi")] }] : []
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

        // First setup: the rest happens on the phone
        Row {
            visible: root.firstRun && !!(root.ambient.qr && root.ambient.qr.rows)
            anchors.horizontalCenter: parent.horizontalCenter
            y: 560
            spacing: 60
            QrCode { size: 330; rows: root.ambient.qr ? root.ambient.qr.rows : [] }
            Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 16
                Text { text: root.tr("WELCOME"); color: "#c9b8ff"; font.pixelSize: 24; font.bold: true; font.letterSpacing: 4 }
                Text { text: root.tr("Continue on your phone"); color: "white"; font.pixelSize: 54; font.bold: true }
                Text { text: root.tr("Scan this code to set up the box:"); color: "#d0c8e0"; font.pixelSize: 30 }
                Text { text: root.tr("streamers, accounts, or restoring a backup"); color: "#d0c8e0"; font.pixelSize: 30 }
                Text {
                    text: root.ambient.qr ? String(root.ambient.qr.url).replace(/^https?:\/\//, "").replace(/\/$/, "") : ""
                    color: "#8a85a0"; font.pixelSize: 26
                }
            }
        }

        // QR code of the companion app, depending on the setting (always, 30 seconds on each arrival, never)
        Column {
            visible: opacity > 0 && !!(root.ambient.qr && root.ambient.qr.rows) && !root.setup && !root.firstRun
            opacity: root.qrWanted ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 500 } }
            x: 1920 - 56 - width; y: 1080 - 44 - height
            spacing: 10
            Text { anchors.horizontalCenter: parent.horizontalCenter; text: root.tr("Companion app"); color: "#b4afc2"; font.pixelSize: 21 }
            QrCode { anchors.horizontalCenter: parent.horizontalCenter; size: 230; rows: root.ambient.qr ? root.ambient.qr.rows : [] }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.ambient.qr ? String(root.ambient.qr.url).replace(/^https?:\/\//, "").replace(/\/$/, "") : ""
                color: "#8a85a0"; font.pixelSize: 18
            }
        }
    }
}
