// Petit bandeau en haut au centre, quelques secondes (user-data/streambox/notice, envoyé par stream-box.lua) :
// « Appareil connecté · Xiaomi RC »… Par-dessus tout, menu compris (on appaire souvent depuis le menu)
import QtQuick

Item {
    id: root
    anchors.fill: parent
    readonly property var n: { try { return JSON.parse(osd.notice || "{}") } catch (e) { return {} } }
    property string text: ""
    property bool shown: false
    property real lastId: -1
    // Toutes les données d'affichage partagent un seul signal (ui.py) : n est relu à chaque changement (bandeau d'infos…),
    // on n'affiche que pour une nouvelle notification
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
