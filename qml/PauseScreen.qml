// Pause screen (video): the picture darkens, a big pause icon in the center of the screen. Fade in and
// out.
import QtQuick

Item {
    id: root
    anchors.fill: parent
    readonly property var b: { try { return JSON.parse(osd.bar || "{}") } catch (e) { return {} } }
    readonly property bool shown: b.mode === "media" && !!b.bar && !!(b.playback || {}).pause
    opacity: shown ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 300; easing.type: Easing.InOutQuad } }

    Rectangle { anchors.fill: parent; color: "black"; opacity: 0.55 }
    Rectangle {   // pause icon, in the center of the screen
        anchors.centerIn: parent
        width: 132; height: 132; radius: 66
        color: "#40ffffff"; border.color: "#80ffffff"; border.width: 2
        scale: root.shown ? 1 : 0.85
        Behavior on scale { NumberAnimation { duration: 300; easing.type: Easing.OutBack } }
        Row {
            anchors.centerIn: parent
            spacing: 16
            Rectangle { width: 16; height: 50; radius: 4; color: "white" }
            Rectangle { width: 16; height: 50; radius: 4; color: "white" }
        }
    }
}
