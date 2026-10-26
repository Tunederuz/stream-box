// "X is live" notification (Qt app), top right: slides in from the edge, photo, title, game, and a line
// that empties during the seconds when OK lets you go there (handled by stream-box.lua)
import QtQuick
import QtQuick.Effects
import "fmt.js" as Fmt
import "i18n.js" as I18n

Item {
    id: root
    anchors.fill: parent
    function tr(s, a) { return I18n.t(i18n.dict, s, a) }
    readonly property var t: { try { return JSON.parse(osd.toast || "{}") } catch (e) { return {} } }
    readonly property bool shown: !!t.name
    property var avatars: ({})
    property var last: ({})   // last notification, kept while sliding out
    onTChanged: if (t.name) { last = t; loadAvatars(); countdown.restart() }

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
        id: card
        width: 560; height: 170   // narrow: does not cover the polls box, centered
        y: 44
        x: root.shown ? root.width - width - 44 : root.width + 40
        opacity: root.shown ? 1 : 0
        Behavior on x { NumberAnimation { duration: 380; easing.type: Easing.OutBack; easing.overshoot: 0.8 } }
        Behavior on opacity { NumberAnimation { duration: 250 } }

        RectangularShadow { anchors.fill: parent; radius: 26; blur: 50; color: "black"; opacity: 0.6 }
        Rectangle { anchors.fill: parent; radius: 26; color: "#ee1a1424"; border.color: "#33ffffff"; border.width: 1 }
        Rectangle {
            x: 26; anchors.verticalCenter: parent.verticalCenter
            width: 100; height: 100; radius: 50; color: "#ff4f5e"
            RoundImage { anchors.centerIn: parent; width: 92; height: 92; circle: true; placeholder: "#4a3d5c"; source: root.avatars[root.last.name] || "" }
        }
        Column {
            x: 150; width: card.width - 176
            anchors.verticalCenter: parent.verticalCenter
            spacing: 5
            Row {
                spacing: 10
                Text { text: "●"; color: "#ff4f5e"; font.pixelSize: 26 }
                Text { text: root.tr("{name} is live", { name: root.last.name || "" }); color: "white"; font.pixelSize: 28; font.bold: true }
            }
            Text {
                width: parent.width; elide: Text.ElideRight
                text: [root.last.title, root.last.game].filter(function (s) { return !!s }).join("  ·  ")
                color: "#d0c8e0"; font.pixelSize: 21
            }
            Text { text: root.tr("OK to watch"); color: "#b67bff"; font.pixelSize: 21; font.bold: true }
        }
        Rectangle {   // remaining time to press OK
            id: bar
            x: 26; y: card.height - 12; height: 4; radius: 2
            width: card.width - 52
            color: "#9146ff"
            NumberAnimation on width {
                id: countdown
                running: false
                from: card.width - 52; to: 0
                duration: (root.last.seconds || 12) * 1000
            }
        }
    }
}
