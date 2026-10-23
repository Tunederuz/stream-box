// Carte de streamer (En direct, Suivis) : photo (anneau rouge en live), nom, spectateurs, jeu. Grossit au focus.
import QtQuick
import "fmt.js" as Fmt

Item {
    id: root
    property string name: ""
    property string avatar: ""
    property bool live: false
    property int viewers: 0
    property string game: ""
    property bool focused: false
    property bool current: false   // streamer regardé
    width: 330
    height: 150
    z: focused ? 2 : 1
    scale: focused ? 1.06 : 1
    Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }

    FocusFrame { active: root.focused; radius: 22 }
    Rectangle {
        anchors.fill: parent
        radius: 22
        color: root.current ? "#6b3c8a" : (root.focused ? "#3a2c4e" : "#2a2034")
        opacity: root.focused || root.current ? 1 : 0.85
        Behavior on color { ColorAnimation { duration: 160 } }
    }
    Rectangle {   // anneau rouge des lives
        visible: root.live
        x: 17; y: 25; width: 100; height: 100
        radius: 50
        color: "#ff4f5e"
    }
    RoundImage {
        x: 22; y: 30; width: 90; height: 90
        circle: true
        placeholder: "#4a3d5c"
        source: root.avatar
        Text {
            anchors.centerIn: parent
            z: -1
            text: root.name.charAt(0).toUpperCase()
            color: "#d0c8e0"
            font.pixelSize: 31
            font.bold: true
        }
    }
    Column {
        x: 132
        width: root.width - 148
        anchors.verticalCenter: parent.verticalCenter
        spacing: 4
        Marquee {
            width: parent.width
            text: root.name
            pixelSize: 27
            bold: true
            running: root.focused
        }
        Text {
            text: root.live ? "● " + Fmt.viewers(root.viewers) : "Hors ligne"
            color: root.live ? "#ff4f5e" : "#8a85a0"
            font.pixelSize: 21
            font.bold: root.live
        }
        Marquee {
            visible: root.live
            width: parent.width
            text: root.game
            color: "#b4afc2"
            pixelSize: 20
            running: root.focused
        }
    }
}
