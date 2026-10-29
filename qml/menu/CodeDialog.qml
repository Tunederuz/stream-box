// TV menu: sign-in by code (YouTube account on google.com/device, Plex account on plex.tv/link): the code (and the QR
// code of the page), updated by itself; menu.codeDialog gives the texts
import QtQuick
import ".."

Item {
    id: dialog
    required property var menu
    anchors.fill: parent
    readonly property var d: menu.codeDialog || ({})
    opacity: menu.codeDialog ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 160 } }
    Rectangle { anchors.fill: parent; color: "#05030a"; opacity: 0.6 }
    MouseArea {   // a click closes it, as Back
        anchors.fill: parent; enabled: !!menu.codeDialog
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onClicked: menu.key("back")
    }
    Rectangle {
        width: 1240; height: 520; radius: 28
        anchors.centerIn: parent
        color: menu.pal.sheet
        Column {
            x: 60; y: 60; spacing: 26; width: 700
            Text { text: dialog.d.title || ""; color: "white"; font.pixelSize: 30; font.bold: true }
            Text {
                width: parent.width; wrapMode: Text.WordWrap; color: "white"; font.pixelSize: 25
                text: dialog.d.code ? dialog.d.where : dialog.d.error ? dialog.d.error : menu.tr("Requesting the code…")
            }
            Text {
                visible: !!dialog.d.code
                text: dialog.d.code || ""
                color: "white"; font.pixelSize: 68; font.bold: true; font.letterSpacing: 8
            }
            Text {
                width: parent.width; wrapMode: Text.WordWrap; color: "#b4afc2"; font.pixelSize: 21
                text: (dialog.d.help || "") + " " + menu.tr("The TV updates by itself; Back to close.")
            }
        }
        QrCode {
            visible: !!dialog.d.code && n > 0
            x: 820; y: 80; size: 360; rows: dialog.d.qr ? dialog.d.qr.rows : []
        }
    }
}
