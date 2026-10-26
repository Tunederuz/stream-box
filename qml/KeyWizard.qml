// "Set up the keys" wizard (stream-box.lua, user-data/streambox/learn): action to learn, countdown (with no key,
// the action keeps its own), key received, then "Keys saved"
import QtQuick
import QtQuick.Effects
import "i18n.js" as I18n

Item {
    id: root
    anchors.fill: parent
    function tr(s, a) { return I18n.t(i18n.dict, s, a) }
    readonly property var l: { try { return JSON.parse(osd.learn || "{}") } catch (e) { return {} } }
    readonly property bool shown: !!l.phase
    property var last: ({})
    onLChanged: if (l.phase) { last = l; if (l.phase === "wait") countdown.restart() }
    opacity: shown ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 200 } }

    Rectangle { anchors.fill: parent; color: "#05030a"; opacity: 0.75 }
    Item {
        anchors.centerIn: parent
        width: 900; height: 420
        RectangularShadow { anchors.fill: parent; radius: 30; blur: 60; color: "black"; opacity: 0.6 }
        Rectangle { anchors.fill: parent; radius: 30; color: "#1e1e22"; border.color: "#33ffffff"; border.width: 1 }
        Column {
            anchors.centerIn: parent
            width: parent.width - 100
            spacing: 22
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.last.phase === "done" || root.last.phase === "cancel" ? root.tr("REMOTE CONTROL KEYS")
                      : root.tr("REMOTE CONTROL KEYS · {step} / {total}", { step: root.last.step || 0, total: root.last.total || 0 })
                color: "#a3a3ad"; font.pixelSize: 20; font.bold: true; font.letterSpacing: 3
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.last.phase === "done" ? root.tr("Keys saved") : root.last.phase === "cancel" ? root.tr("Wizard canceled")
                      : root.tr("Press the key for")
                color: "white"; font.pixelSize: root.last.phase === "done" || root.last.phase === "cancel" ? 46 : 30
            }
            Text {
                visible: root.last.phase !== "done" && root.last.phase !== "cancel"
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.last.label || ""
                color: "white"; font.pixelSize: 58; font.bold: true
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.last.phase === "ok" ? "✓ " + root.last.key
                      : root.last.phase === "taken" ? root.tr("{key}: already used for another action", { key: root.last.key })
                      : root.last.phase === "done" ? "" : root.last.phase === "cancel" ? root.tr("Keys unchanged")
                      : root.tr("With no key, it keeps the current one  ·  Back on the phone to quit")
                color: root.last.phase === "ok" ? "#7ee0a0" : root.last.phase === "taken" ? "#ffb44a" : "#8a8a95"
                font.pixelSize: 24
            }
            Rectangle {   // remaining time
                visible: root.last.phase === "wait" || root.last.phase === "taken"
                anchors.horizontalCenter: parent.horizontalCenter
                width: 600; height: 6; radius: 3; color: "#33ffffff"
                Rectangle {
                    id: bar
                    height: parent.height; radius: 3; color: "white"; width: parent.width
                    NumberAnimation on width { id: countdown; running: false; from: 600; to: 0; duration: (root.last.seconds || 8) * 1000 }
                }
            }
        }
    }
}
