// Video card while its row loads (skeleton): the shapes of the thumbnail, the title and the info line of VideoCard,
// breathing; a delay per card makes the pulse travel along the row
import QtQuick

Item {
    id: root
    property int delay: 0   // ms
    property color shade: "#2a2034"
    readonly property int picH: Math.round(width * 9 / 16)
    width: 456; height: picH + 106
    Rectangle { width: root.width; height: root.picH; radius: 16; color: root.shade }
    Rectangle { y: root.picH + 34; width: root.width * 0.72; height: 22; radius: 11; color: root.shade }
    Rectangle { y: root.picH + 78; width: root.width * 0.42; height: 16; radius: 8; color: root.shade }
    SequentialAnimation on opacity {
        running: root.visible; loops: Animation.Infinite
        PauseAnimation { duration: root.delay }
        NumberAnimation { from: 1; to: 0.4; duration: 700; easing.type: Easing.InOutSine }
        NumberAnimation { from: 0.4; to: 1; duration: 700; easing.type: Easing.InOutSine }
        PauseAnimation { duration: 450 - root.delay }
    }
}
