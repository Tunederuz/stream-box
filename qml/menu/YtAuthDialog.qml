// TV menu: YouTube account dialog, code to enter on google.com/device (or QR code), updated by itself (menu.ytAuth)
import QtQuick
import ".."

Item {
    id: dialog
    required property var menu
    anchors.fill: parent
    opacity: menu.ytAuth ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 160 } }
    readonly property var pend: menu.ytAuth ? menu.ytAuth.pending : null
    readonly property bool waiting: !!(pend && pend.user_code && !pend.error)
    Rectangle { anchors.fill: parent; color: "#05030a"; opacity: 0.6 }
    Rectangle {
        width: 1240; height: 520; radius: 28
        anchors.centerIn: parent
        color: menu.pal.sheet
        Column {
            x: 60; y: 60; spacing: 26; width: 700
            Text {
                text: menu.ytAuth && menu.ytAuth.tv ? menu.tr("Sync YouTube progress") : menu.tr("Connect my YouTube account")
                color: "white"; font.pixelSize: 30; font.bold: true
            }
            Text {
                width: parent.width; wrapMode: Text.WordWrap; color: "white"; font.pixelSize: 25
                text: dialog.waiting ? menu.tr("On your phone, open google.com/device and enter:")
                    : dialog.pend && dialog.pend.error ? menu.tr("Authorization denied: {error}", { error: dialog.pend.error })
                    : menu.tr("Requesting the code…")
            }
            Text {
                visible: dialog.waiting
                text: visible ? dialog.pend.user_code : ""
                color: "white"; font.pixelSize: 68; font.bold: true; font.letterSpacing: 8
            }
            Text {
                width: parent.width; wrapMode: Text.WordWrap; color: "#b4afc2"; font.pixelSize: 21
                text: (menu.ytAuth && menu.ytAuth.tv
                    ? menu.tr("Google shows \"YouTube on TV\": the box presents itself as the YouTube app for TVs, to read and send back progress.")
                    : menu.tr("Google warns that the app isn't verified: \"Advanced\", then \"Go to Stream Box\". Read-only."))
                    + " " + menu.tr("The TV updates by itself; Back to close.")
            }
        }
        QrCode {
            visible: dialog.waiting && n > 0
            x: 820; y: 80; size: 360; rows: menu.ytAuthQr ? menu.ytAuthQr.rows : []
        }
    }
}
