// Loading screen between two videos or two channels (stream-box.lua, user-data/streambox/loading: title, thumb,
// kind). The Inlet logo in the center (assets/brand: a screen open on its left side, a wave flowing into it): the wave
// takes the color of the source (Twitch purple, YouTube red, Jellyfin blue, Plex yellow) and a glow runs along it into
// the screen, rings leave the logo like a signal being received, and the logo breathes. Background: blurred and
// darkened thumbnail. Fade in and out.
import QtQuick
import QtQuick.Effects
import QtQuick.Shapes
import "i18n.js" as I18n

Item {
    id: root
    anchors.fill: parent
    function tr(s, a) { return I18n.t(i18n.dict, s, a) }
    readonly property var l: { try { return JSON.parse(osd.loading || "{}") } catch (e) { return {} } }
    readonly property bool shown: !!l.title
    property var last: ({})
    onLChanged: if (l.title) last = l
    readonly property color accent: last.kind === "youtube" ? "#ff0033" : last.kind === "jellyfin" ? "#1565c0"
                                  : last.kind === "plex" ? "#e5a00d"
                                  : last.kind === "twitch" ? "#9146ff" : "#e8e8ee"
    readonly property string source: last.kind === "youtube" ? "YouTube" : last.kind === "jellyfin" ? "Jellyfin"
                                   : last.kind === "plex" ? "Plex"
                                   : last.kind === "twitch" ? "Twitch" : tr("Video")
    opacity: shown ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: root.shown ? 200 : 500; easing.type: Easing.InOutQuad } }

    Rectangle { anchors.fill: parent; color: "#07060a" }
    Image {
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
        brightness: -0.62
    }
    RectangularShadow {   // glow in the color of the source behind the logo
        anchors.centerIn: logo
        width: 360; height: 360; radius: 180
        blur: 200; spread: 0
        color: root.accent; opacity: 0.35
        Behavior on color { ColorAnimation { duration: 300 } }
    }

    // Waves: three rings that grow and fade, staggered
    Repeater {
        model: 3
        Rectangle {
            anchors.centerIn: logo
            width: 150; height: 150; radius: 75
            color: "transparent"
            border.color: root.accent; border.width: 3
            opacity: 0
            scale: 1
            SequentialAnimation on scale {
                running: root.visible; loops: Animation.Infinite
                PauseAnimation { duration: index * 700 }
                NumberAnimation { from: 0.9; to: 2.6; duration: 2100; easing.type: Easing.OutCubic }
            }
            SequentialAnimation on opacity {
                running: root.visible; loops: Animation.Infinite
                PauseAnimation { duration: index * 700 }
                NumberAnimation { from: 0.7; to: 0; duration: 2100; easing.type: Easing.OutQuad }
            }
        }
    }

    // Logo: the screen, the wave in the source's color, and a glow flowing along the wave into the screen (the
    // drawing of assets/brand/inlet-mark.svg, scaled 1.5)
    Item {
        id: logo
        width: 150; height: 150
        anchors.horizontalCenter: parent.horizontalCenter
        y: parent.height / 2 - 150
        SequentialAnimation on scale {
            running: root.visible; loops: Animation.Infinite
            NumberAnimation { from: 1; to: 1.05; duration: 1050; easing.type: Easing.InOutSine }
            NumberAnimation { from: 1.05; to: 1; duration: 1050; easing.type: Easing.InOutSine }
        }
        Shape {   // the screen, open on its left side
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                fillColor: "transparent"; strokeColor: "#e8eef0"
                strokeWidth: 12; capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
                startX: 54; startY: 33
                PathLine { x: 111; y: 33 }
                PathArc { x: 132; y: 54; radiusX: 21; radiusY: 21 }
                PathLine { x: 132; y: 96 }
                PathArc { x: 111; y: 117; radiusX: 21; radiusY: 21 }
                PathLine { x: 54; y: 117 }
            }
        }
        Shape {   // the wave, in the source's color, dimmed
            anchors.fill: parent
            opacity: 0.5
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                fillColor: "transparent"; strokeColor: root.accent
                strokeWidth: 12; capStyle: ShapePath.RoundCap
                startX: 15; startY: 75
                PathQuad { controlX: 29.25; controlY: 58.5; x: 43.5; y: 75 }
                PathQuad { controlX: 57.75; controlY: 91.5; x: 72; y: 75 }
                PathQuad { controlX: 86.25; controlY: 58.5; x: 100.5; y: 75 }
            }
        }
        Shape {   // glow: a bright piece of the wave flowing into the screen
            anchors.fill: parent
            layer.enabled: true; layer.samples: 4
            ShapePath {
                fillColor: "transparent"; strokeColor: root.accent
                strokeWidth: 12; capStyle: ShapePath.RoundCap
                strokeStyle: ShapePath.DashLine
                dashPattern: [2, 8]   // in stroke widths: a 24 px piece every 120 px, about the wave's length
                NumberAnimation on dashOffset { from: 10; to: 0; duration: 1100; loops: Animation.Infinite; running: root.visible }
                startX: 15; startY: 75
                PathQuad { controlX: 29.25; controlY: 58.5; x: 43.5; y: 75 }
                PathQuad { controlX: 57.75; controlY: 91.5; x: 72; y: 75 }
                PathQuad { controlX: 86.25; controlY: 58.5; x: 100.5; y: 75 }
            }
        }
    }

    Column {
        anchors.horizontalCenter: parent.horizontalCenter
        y: logo.y + logo.height + 140   // below the waves
        spacing: 14
        // shadow under the texts: readable whatever the thumbnail behind
        layer.enabled: true
        layer.effect: MultiEffect { shadowEnabled: true; shadowColor: "black"; shadowBlur: 0.8; shadowOpacity: 0.9; shadowVerticalOffset: 2 }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.source.toUpperCase()
            color: "#d8d4e0"; font.pixelSize: 20; font.bold: true; font.letterSpacing: 4
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(implicitWidth, 1400); elide: Text.ElideRight; horizontalAlignment: Text.AlignHCenter
            text: root.last.title || ""
            color: "white"; font.pixelSize: 40; font.bold: true
        }
    }
}
