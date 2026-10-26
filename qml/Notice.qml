// Small banner at the top center, for a few seconds (user-data/streambox/notice, sent by stream-box.lua):
// "Device connected · Xiaomi RC"… On top of everything, menu included (pairing is often done from the menu)
import QtQuick

Item {
    id: root
    anchors.fill: parent
    readonly property var n: { try { return JSON.parse(osd.notice || "{}") } catch (e) { return {} } }
    property string text: ""
    property bool shown: false
    property real lastId: -1
    // All display data share a single signal (ui.py): n is re-read on every change (info bar…),
    // we only show for a new notification
    onNChanged: if (n.text && n.id !== lastId) { lastId = n.id; text = n.text; shown = true; hide.restart() }
    Timer { id: hide; interval: 4000; onTriggered: root.shown = false }

    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        y: root.shown ? 40 : -height - 20
        Behavior on y { NumberAnimation { duration: 350; easing.type: Easing.OutCubic } }
        opacity: root.shown ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 350 } }
        width: label.implicitWidth + 96; height: 72; radius: 36
        color: "#e6201828"
        border.color: "#33ffffff"; border.width: 1
        Rectangle {
            x: 18; anchors.verticalCenter: parent.verticalCenter
            width: 40; height: 40; radius: 20; color: "#9146ff"
            Text { anchors.centerIn: parent; text: "✓"; color: "white"; font.pixelSize: 22; font.bold: true }
        }
        Text {
            id: label
            x: 74; anchors.verticalCenter: parent.verticalCenter
            text: root.text; color: "white"; font.pixelSize: 26
        }
    }
}
