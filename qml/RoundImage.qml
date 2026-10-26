// Rounded image (disc or rounded corners), loaded in the background and revealed with a fade. Mask computed by the
// GPU (MultiEffect); while waiting for the image, a colored background.
import QtQuick
import QtQuick.Effects

Item {
    id: root
    property alias source: img.source
    property real radius: 0
    property bool circle: false
    property color placeholder: "#3a2c4e"
    readonly property real r: circle ? Math.min(width, height) / 2 : radius

    Rectangle {
        anchors.fill: parent
        radius: root.r
        color: root.placeholder
    }
    Image {
        id: img
        anchors.fill: parent
        visible: false
        asynchronous: true
        fillMode: Image.PreserveAspectCrop
        sourceSize.width: root.width * 1.5   // a bit more than the displayed size: sharp when the card grows
        sourceSize.height: root.height * 1.5
    }
    Item {
        id: mask
        anchors.fill: parent
        layer.enabled: true
        layer.smooth: true
        visible: false
        Rectangle {
            anchors.fill: parent
            radius: root.r
            color: "black"
        }
    }
    MultiEffect {
        anchors.fill: parent
        source: img
        maskEnabled: true
        maskSource: mask
        maskThresholdMin: 0.5
        maskSpreadAtMin: 1.0
        opacity: img.status === Image.Ready ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 250 } }
    }
}
