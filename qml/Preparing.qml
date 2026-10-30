// Shown at start until the box's server (remote.py, the companion app API the menu and the home screen read) answers:
// on a first start, or from a slow USB stick or SD card, it can take a few seconds, and the home screen stayed empty
// meanwhile. The logo and "Getting ready…", on the home screen's background; fades out at the first answer (60 s at
// most).
import QtQuick
import "i18n.js" as I18n

Rectangle {
    id: root
    anchors.fill: parent
    color: "#0b0710"   // (the boot screen's background, assets/boot-splash.png)
    function tr(s, a) { return I18n.t(i18n.dict, s, a) }
    property bool ready: false
    opacity: ready ? 0 : 1
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 500; easing.type: Easing.InOutQuad } }

    function ask() {
        var r = new XMLHttpRequest()
        r.onreadystatechange = function () {
            if (r.readyState === XMLHttpRequest.DONE && r.status === 200) root.ready = true
        }
        r.open("GET", "http://127.0.0.1:8080/api/state")
        r.send()
    }
    Timer { interval: 700; repeat: true; running: !root.ready; triggeredOnStart: true; onTriggered: root.ask() }
    Timer { interval: 60000; running: true; onTriggered: root.ready = true }   // (the server never came: no veil forever)

    Column {
        anchors.centerIn: parent
        spacing: 34
        Logo {
            anchors.horizontalCenter: parent.horizontalCenter
            width: 150; height: 150
            SequentialAnimation on opacity {   // breathes while waiting
                running: root.visible; loops: Animation.Infinite
                NumberAnimation { from: 1; to: 0.55; duration: 1100; easing.type: Easing.InOutSine }
                NumberAnimation { from: 0.55; to: 1; duration: 1100; easing.type: Easing.InOutSine }
            }
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.tr("Getting ready…")
            color: "#d8d4e0"; font.pixelSize: 32
        }
    }
}
