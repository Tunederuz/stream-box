// QR code drawn from its rows of "0" and "1" (remote.py, segno), on a rounded light background
import QtQuick

Rectangle {
    id: root
    property var rows: []
    property real size: 300
    readonly property int n: rows ? rows.length : 0
    readonly property real module: n > 0 ? Math.floor(size / (n + 4)) : 0
    width: module * (n + 4)
    height: width
    radius: 18
    color: "#e8e8e8"
    visible: n > 0

    Canvas {
        id: canvas
        anchors.fill: parent
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            ctx.fillStyle = "#101010"
            var m = root.module
            for (var r = 0; r < root.n; r++)
                for (var c = 0; c < root.rows[r].length; c++)
                    if (root.rows[r][c] === "1") ctx.fillRect((c + 2) * m, (r + 2) * m, m, m)
        }
        Connections { target: root; function onRowsChanged() { canvas.requestPaint() } }
    }
}
