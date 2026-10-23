// Écran de chargement entre deux vidéos ou deux chaînes : l'image précédente s'efface derrière un voile, avec la
// miniature floutée, le titre et un anneau qui tourne, jusqu'à la première image (stream-box.lua, user-data/streambox/loading)
import QtQuick
import QtQuick.Effects

Item {
    id: root
    anchors.fill: parent
    readonly property var l: { try { return JSON.parse(osd.loading || "{}") } catch (e) { return {} } }
    readonly property bool shown: !!l.title
    property var last: ({})
    onLChanged: if (l.title) last = l
    opacity: shown ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: root.shown ? 180 : 450; easing.type: Easing.InOutQuad } }

    Rectangle { anchors.fill: parent; color: "#08060c" }
    Image {   // miniature, floutée et assombrie, en fond
        id: thumb
        anchors.fill: parent
        source: root.last.thumb || ""
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        visible: false
    }
    MultiEffect {
        anchors.fill: parent
        source: thumb
        visible: thumb.status === Image.Ready
        blurEnabled: true; blur: 1.0; blurMax: 64
        brightness: -0.45
    }
    Column {
        anchors.centerIn: parent
        spacing: 34
        Item {   // anneau qui tourne
            anchors.horizontalCenter: parent.horizontalCenter
            width: 84; height: 84
            Rectangle { anchors.fill: parent; radius: 42; color: "transparent"; border.color: "#33ffffff"; border.width: 7 }
            Item {
                anchors.fill: parent
                RotationAnimator on rotation { from: 0; to: 360; duration: 900; loops: Animation.Infinite; running: root.visible }
                Rectangle { x: parent.width / 2 - 7; y: 0; width: 14; height: 14; radius: 7; color: "white" }
            }
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "Chargement…"
            color: "#c8c4d0"; font.pixelSize: 26
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(implicitWidth, 1400); elide: Text.ElideRight; horizontalAlignment: Text.AlignHCenter
            text: root.last.title || ""
            color: "white"; font.pixelSize: 38; font.bold: true
        }
    }
}
