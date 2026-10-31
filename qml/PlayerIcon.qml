// Playback bar icons, drawn (no Unicode characters, whose rendering depends on the fonts: emoji…):
// back (−10 s), fwd (+10 s), play, pause, tracks (subtitles), quality, chapters, next (next episode), like and
// dislike (filled: the account's vote), comments.
import QtQuick
import QtQuick.Shapes

Item {
    id: root
    property string name: "play"
    property color color: "white"
    property bool filled: false   // like, dislike: the vote given
    width: 34; height: 34

    // Play: triangle
    Shape {
        visible: root.name === "play"
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            fillColor: root.color; strokeColor: "transparent"
            startX: 9; startY: 4
            PathLine { x: 30; y: 17 }
            PathLine { x: 9; y: 30 }
            PathLine { x: 9; y: 4 }
        }
    }
    // Pause: two bars
    Row {
        visible: root.name === "pause"
        anchors.centerIn: parent
        spacing: 7
        Rectangle { width: 8; height: 26; radius: 2; color: root.color }
        Rectangle { width: 8; height: 26; radius: 2; color: root.color }
    }
    // −10 s / +10 s: circle open at the top (center 17,17, radius 12), arrowhead at the end, "10" in the center;
    // +10 s is the mirror of −10 s
    Item {
        visible: root.name === "back" || root.name === "fwd"
        anchors.fill: parent
        transform: Scale { origin.x: 17; xScale: root.name === "fwd" ? -1 : 1 }
        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                fillColor: "transparent"; strokeColor: root.color; strokeWidth: 2.6; capStyle: ShapePath.RoundCap
                PathAngleArc { centerX: 17; centerY: 17; radiusX: 12; radiusY: 12; startAngle: -62; sweepAngle: 296 }
            }
            ShapePath {   // arrowhead at the upper end of the arc, along the arc (towards the left: back)
                fillColor: root.color; strokeColor: "transparent"
                startX: 15.6; startY: 4.0
                PathLine { x: 24.7; y: 1.9 }
                PathLine { x: 21.8; y: 10.5 }
                PathLine { x: 15.6; y: 4.0 }
            }
        }
    }
    Text {
        visible: root.name === "back" || root.name === "fwd"
        anchors.centerIn: parent; anchors.verticalCenterOffset: 1
        text: "10"; color: root.color; font.pixelSize: 11; font.bold: true
    }
    // Subtitles: rounded frame and two lines of text
    Rectangle {
        visible: root.name === "tracks"
        anchors.centerIn: parent
        width: 30; height: 22; radius: 4
        color: "transparent"; border.color: root.color; border.width: 3
        Column {
            anchors.centerIn: parent; anchors.verticalCenterOffset: 2
            spacing: 3
            Row { spacing: 3; Rectangle { width: 6; height: 3; color: root.color } Rectangle { width: 10; height: 3; color: root.color } }
            Row { spacing: 3; Rectangle { width: 10; height: 3; color: root.color } Rectangle { width: 6; height: 3; color: root.color } }
        }
    }
    // Quality: "HD" in a rounded frame
    Rectangle {
        visible: root.name === "quality"
        anchors.centerIn: parent
        width: 32; height: 22; radius: 5
        color: "transparent"; border.color: root.color; border.width: 3
        Text { anchors.centerIn: parent; text: "HD"; color: root.color; font.pixelSize: 12; font.bold: true }
    }
    // Chapters: a list, a dot and a line per chapter
    Column {
        visible: root.name === "chapters"
        anchors.centerIn: parent
        spacing: 4
        Repeater {
            model: 3
            Row {
                spacing: 4
                Rectangle { width: 5; height: 5; radius: 2.5; color: root.color; anchors.verticalCenter: parent.verticalCenter }
                Rectangle { width: index === 1 ? 16 : 20; height: 3; radius: 1.5; color: root.color; anchors.verticalCenter: parent.verticalCenter }
            }
        }
    }
    // Next episode: two triangles and a bar
    Shape {
        visible: root.name === "next"
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            fillColor: root.color; strokeColor: "transparent"
            startX: 3; startY: 6
            PathLine { x: 15; y: 17 }
            PathLine { x: 3; y: 28 }
            PathLine { x: 3; y: 6 }
        }
        ShapePath {
            fillColor: root.color; strokeColor: "transparent"
            startX: 15; startY: 6
            PathLine { x: 27; y: 17 }
            PathLine { x: 15; y: 28 }
            PathLine { x: 15; y: 6 }
        }
    }
    Rectangle {
        visible: root.name === "next"
        x: 27; y: 6
        width: 4; height: 22; radius: 1; color: root.color
    }
    // Like: a thumb up, outlined, filled once given; dislike: the same upside down
    Shape {
        visible: root.name === "like" || root.name === "dislike"
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        transform: Scale { origin.y: 17; yScale: root.name === "dislike" ? -1 : 1 }
        ShapePath {   // cuff
            fillColor: root.filled ? root.color : "transparent"; strokeColor: root.color; strokeWidth: 2.4
            joinStyle: ShapePath.RoundJoin
            startX: 3.5; startY: 14
            PathLine { x: 8.5; y: 14 }
            PathLine { x: 8.5; y: 29 }
            PathLine { x: 3.5; y: 29 }
            PathLine { x: 3.5; y: 14 }
        }
        ShapePath {   // hand
            fillColor: root.filled ? root.color : "transparent"; strokeColor: root.color; strokeWidth: 2.4
            joinStyle: ShapePath.RoundJoin
            startX: 11.5; startY: 14
            PathLine { x: 16; y: 5 }
            PathQuad { x: 20.5; y: 6.5; controlX: 19.5; controlY: 2.5 }
            PathLine { x: 19.5; y: 12 }
            PathLine { x: 27.5; y: 12 }
            PathQuad { x: 30.5; y: 15.5; controlX: 31; controlY: 12 }
            PathLine { x: 28.5; y: 27 }
            PathQuad { x: 25.5; y: 29; controlX: 28; controlY: 29 }
            PathLine { x: 11.5; y: 29 }
            PathLine { x: 11.5; y: 14 }
        }
    }
    // Comments: a speech bubble and two lines
    Shape {
        visible: root.name === "comments"
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            fillColor: "transparent"; strokeColor: root.color; strokeWidth: 2.6; joinStyle: ShapePath.RoundJoin
            startX: 8; startY: 5
            PathLine { x: 27; y: 5 }
            PathQuad { x: 31; y: 9; controlX: 31; controlY: 5 }
            PathLine { x: 31; y: 20 }
            PathQuad { x: 27; y: 24; controlX: 31; controlY: 24 }
            PathLine { x: 14; y: 24 }
            PathLine { x: 7; y: 30 }
            PathLine { x: 7.5; y: 24 }
            PathQuad { x: 3; y: 20; controlX: 3; controlY: 24 }
            PathLine { x: 3; y: 9 }
            PathQuad { x: 8; y: 5; controlX: 3; controlY: 5 }
        }
    }
    Column {
        visible: root.name === "comments"
        x: 9; y: 11; spacing: 4
        Rectangle { width: 16; height: 2.6; radius: 1.3; color: root.color }
        Rectangle { width: 11; height: 2.6; radius: 1.3; color: root.color }
    }
}
