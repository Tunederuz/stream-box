// Built-in battery (Steam Deck, laptop: box.battery from ui.py): drawn battery filled to its level, and the
// percentage; green while charging, red at 15 % and below. Hidden without a battery.
import QtQuick

Row {
    id: root
    property int size: 25                  // text size; the icon follows
    readonly property var info: { try { return box.battery ? JSON.parse(box.battery) : null } catch (e) { return null } }
    readonly property int percent: info ? Math.max(0, Math.min(100, info.percent)) : 0
    readonly property color tint: !info ? "white" : info.charging ? "#5fd38d" : percent <= 15 ? "#ff5a5a" : "white"
    visible: !!info
    spacing: size * 0.35

    Item {
        anchors.verticalCenter: parent.verticalCenter
        width: root.size * 1.5; height: root.size * 0.75
        Rectangle {   // body
            id: body
            width: parent.width - nub.width; height: parent.height
            radius: height * 0.18; color: "transparent"; border.color: root.tint; border.width: Math.max(2, root.size / 12)
            Rectangle {   // level
                x: body.border.width * 2; y: x
                height: body.height - 2 * x
                width: Math.max(0, (body.width - 2 * x) * root.percent / 100)
                radius: body.radius / 2; color: root.tint
            }
        }
        Rectangle {   // terminal
            id: nub
            anchors.left: body.right; anchors.verticalCenter: body.verticalCenter
            width: root.size * 0.1; height: body.height * 0.45; radius: width / 2; color: root.tint
        }
    }
    Text {
        anchors.verticalCenter: parent.verticalCenter
        text: (root.info && root.info.charging ? "⚡ " : "") + root.percent + " %"
        color: root.tint; font.pixelSize: root.size
    }
}
