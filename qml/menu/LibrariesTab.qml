// TV menu, Libraries tab (only while neither Jellyfin nor Plex is connected): how to connect one or the other, and the
// QR code of the companion app. Nothing to focus: the rail keeps the focus. Once connected, its own tab replaces this one.
import QtQuick
import ".."

Item {
    id: root
    required property var menu
    anchors.fill: parent
    visible: menu.tabId === "libraries"

    Row {
        y: 210; spacing: 40
        Repeater {
            model: [
                { name: "Jellyfin", color: "#1565c0", steps: [
                    "Settings → Accounts and libraries → Jellyfin: choose your server, then approve the code in Jellyfin (user menu, Quick Connect).",
                    "Or in the companion app (QR code below): Settings → Jellyfin, the server's address.",
                    "The Jellyfin tab then shows here, with your library." ] },
                { name: "Plex", color: "#e5a00d", steps: [
                    "Settings → Accounts and libraries → Plex: sign in with your Plex account, with a code to type on plex.tv/link.",
                    "Or in the companion app (QR code below): Settings → Plex, a server's address.",
                    "The Plex tab then shows here, with your library." ] }]
            Rectangle {
                width: 560; height: 350; radius: 24
                color: "#1affffff"; border.color: "#22ffffff"; border.width: 1
                Rectangle { x: 34; y: 36; width: 14; height: 14; radius: 7; color: modelData.color }
                Text { x: 62; y: 43 - height / 2; text: modelData.name; color: "white"; font.pixelSize: 32; font.bold: true }
                Column {
                    x: 34; y: 90; width: parent.width - 68; spacing: 16
                    Repeater {
                        model: modelData.steps
                        Row {
                            width: parent.width; spacing: 14
                            Text { text: (index + 1) + "."; color: root.menu.pal.label; font.pixelSize: 24; font.bold: true }
                            Text {
                                width: parent.width - 40; wrapMode: Text.WordWrap
                                text: root.menu.tr(modelData); color: "#e0daea"; font.pixelSize: 24
                            }
                        }
                    }
                }
            }
        }
    }
    Row {   // QR code of the companion app (Plex address, and everything that requires typing text)
        visible: !!(root.menu.ambient.qr && root.menu.ambient.qr.rows)
        y: 610; spacing: 24
        QrCode { size: 190; rows: root.menu.ambient.qr ? root.menu.ambient.qr.rows : [] }
        Column {
            anchors.verticalCenter: parent.verticalCenter; spacing: 10
            Text { text: root.menu.tr("Companion app on your phone"); color: "white"; font.pixelSize: 23; font.bold: true }
            Text {
                text: root.menu.ambient.qr ? String(root.menu.ambient.qr.url).replace(/^https?:\/\//, "").replace(/\/$/, "") : ""
                color: "#b4afc2"; font.pixelSize: 20
            }
        }
    }
}
