// Assistant « Configurer les touches » (stream-box.lua, user-data/streambox/learn) : action à apprendre, compte à
// rebours (sans touche, l'action garde la sienne), touche reçue, puis « Touches enregistrées »
import QtQuick
import QtQuick.Effects

Item {
    id: root
    anchors.fill: parent
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
                text: root.last.phase === "done" || root.last.phase === "cancel" ? "TOUCHES DE LA TÉLÉCOMMANDE"
                      : "TOUCHES DE LA TÉLÉCOMMANDE · " + (root.last.step || 0) + " / " + (root.last.total || 0)
                color: "#a3a3ad"; font.pixelSize: 20; font.bold: true; font.letterSpacing: 3
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.last.phase === "done" ? "Touches enregistrées" : root.last.phase === "cancel" ? "Assistant annulé"
                      : "Appuie sur la touche pour"
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
                      : root.last.phase === "taken" ? root.last.key + " : déjà prise pour une autre action"
                      : root.last.phase === "done" ? "" : root.last.phase === "cancel" ? "Touches inchangées"
                      : "Sans touche, elle garde l'actuelle  ·  Retour sur le téléphone pour quitter"
                color: root.last.phase === "ok" ? "#7ee0a0" : root.last.phase === "taken" ? "#ffb44a" : "#8a8a95"
                font.pixelSize: 24
            }
            Rectangle {   // temps restant
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
