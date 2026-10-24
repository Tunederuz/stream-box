// Écran de chargement entre deux vidéos ou deux chaînes (stream-box.lua, user-data/streambox/loading : title, thumb,
// kind). Le logo de la box au centre : une lueur de la couleur de la source (violet Twitch, rouge YouTube, bleu
// Jellyfin) court sur le contour du triangle, des ondes partent de la tuile comme un signal qu'on capte, et la tuile
// respire. Fond : miniature floutée et assombrie. Fondu à l'entrée et à la sortie.
import QtQuick
import QtQuick.Effects
import QtQuick.Shapes

Item {
    id: root
    anchors.fill: parent
    readonly property var l: { try { return JSON.parse(osd.loading || "{}") } catch (e) { return {} } }
    readonly property bool shown: !!l.title
    property var last: ({})
    onLChanged: if (l.title) last = l
    readonly property color accent: last.kind === "youtube" ? "#ff0033" : last.kind === "jellyfin" ? "#1565c0"
                                  : last.kind === "twitch" ? "#9146ff" : "#e8e8ee"
    readonly property string source: last.kind === "youtube" ? "YouTube" : last.kind === "jellyfin" ? "Jellyfin"
                                   : last.kind === "twitch" ? "Twitch" : "Vidéo"
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
    RectangularShadow {   // halo de la couleur de la source derrière le logo
        anchors.centerIn: logo
        width: 360; height: 360; radius: 180
        blur: 200; spread: 0
        color: root.accent; opacity: 0.35
        Behavior on color { ColorAnimation { duration: 300 } }
    }

    // Ondes : trois anneaux qui grandissent et s'effacent, décalés
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

    // Logo : tuile blanche, triangle anthracite, et une lueur qui court sur son contour
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
        Rectangle { anchors.fill: parent; radius: width * 0.27; color: "#f4f2f7" }
        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                fillColor: "#17151c"; strokeColor: "#17151c"
                strokeWidth: 13; joinStyle: ShapePath.RoundJoin
                startX: 58; startY: 48
                PathLine { x: 104; y: 75 }
                PathLine { x: 58; y: 102 }
                PathLine { x: 58; y: 48 }
            }
        }
        Shape {   // lueur : un trait coloré qui fait le tour du triangle
            anchors.fill: parent
            layer.enabled: true; layer.samples: 4
            ShapePath {
                fillColor: "transparent"; strokeColor: root.accent
                strokeWidth: 7; capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
                strokeStyle: ShapePath.DashLine
                dashPattern: [5, 20]   // en largeurs de trait : un trait de 35 px sur un tour de ~160 px
                NumberAnimation on dashOffset { from: 25; to: 0; duration: 1100; loops: Animation.Infinite; running: root.visible }
                startX: 58; startY: 48
                PathLine { x: 104; y: 75 }
                PathLine { x: 58; y: 102 }
                PathLine { x: 58; y: 48 }
            }
        }
    }

    Column {
        anchors.horizontalCenter: parent.horizontalCenter
        y: logo.y + logo.height + 140   // sous les ondes
        spacing: 14
        // ombre sous les textes : lisibles quelle que soit la miniature derrière
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
