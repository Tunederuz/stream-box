// TV menu, System tab, right of the rows: QR code of the companion app, box status tiles below it
import QtQuick
import ".."

Item {
    required property var menu
    anchors.fill: parent
    Flow {   // box status, below the QR code ("Playback" is two tiles wide)
        visible: menu.tabId === "system"
        x: 860; y: 430; width: 520   // stops 80 px from the edge of the screen
        spacing: 10
        Repeater {
            model: parent.visible ? menu.healthTiles() : []
            Rectangle {
                width: index === 6 ? 520 : 255; height: 92; radius: 18
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
    Row {   // QR code of the companion app, for everything that requires typing text
        visible: menu.tabId === "system" && !!(menu.ambient.qr && menu.ambient.qr.rows)
        x: 860; y: 210; spacing: 24
        QrCode { size: 190; rows: menu.ambient.qr ? menu.ambient.qr.rows : [] }
        Column {
            anchors.verticalCenter: parent.verticalCenter; spacing: 10
            Text { text: menu.tr("Companion app on your phone"); color: "white"; font.pixelSize: 23; font.bold: true }
            Text { text: menu.tr("Link, streamer, Twitch account…"); color: "#b4afc2"; font.pixelSize: 20 }
            Text { text: menu.ambient.qr ? String(menu.ambient.qr.url).replace(/^https?:\/\//, "").replace(/\/$/, "") : ""; color: "#b4afc2"; font.pixelSize: 20 }
        }
    }
}
