// Waiting for the video's data, over it: a turning ring, and the buffer's percentage while it
// fills. After a seek forward, or when the stream slows down (mpv's paused-for-cache, seeking, and core-idle without
// pause: after a seek, mpv waits for the data without paused-for-cache; relay osd.waiting).
// Not before 0.4 s (a short seek shows nothing), not while paused (the pause screen has the center) nor during the
// loading screen between two videos.
import QtQuick
import QtQuick.Shapes

Item {
    id: root
    anchors.fill: parent
    readonly property var w: { try { return JSON.parse(osd.waiting || "{}") } catch (e) { return {} } }
    readonly property bool loadingShown: { try { return !!JSON.parse(osd.loading || "{}").title } catch (e) { return false } }
    readonly property bool waiting: box.videoActive && !w.pause && !loadingShown && (!!w.cache || !!w.seeking || !!w.idle)
    property bool shown: false
    onWaitingChanged: if (waiting) later.restart(); else { later.stop(); shown = false }
    Timer { id: later; interval: 400; onTriggered: root.shown = root.waiting }
    opacity: shown ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 200 } }

    Rectangle {   // a soft dark disc: the ring reads over a bright picture
        anchors.centerIn: parent
        width: 150; height: 150; radius: 75
        color: "black"; opacity: 0.35
    }
    Shape {
        id: ring
        anchors.centerIn: parent
        width: 96; height: 96
        preferredRendererType: Shape.CurveRenderer
        RotationAnimation on rotation { from: 0; to: 360; duration: 1000; loops: Animation.Infinite; running: root.visible }
        ShapePath {
            fillColor: "transparent"; strokeColor: "white"; strokeWidth: 8; capStyle: ShapePath.RoundCap
            PathAngleArc { centerX: 48; centerY: 48; radiusX: 42; radiusY: 42; startAngle: -90; sweepAngle: 260 }
        }
    }
    Text {
        anchors.centerIn: parent
        visible: !!root.w.cache && root.w.pct > 0 && root.w.pct < 100
        text: Math.round(root.w.pct) + " %"
        color: "white"; font.pixelSize: 22; font.bold: true
    }
}
