// Animated background of the home screen and of the menu with no video behind: a base (nothing, blurry blobs, fluid
// color sheets, northern lights) and a layer on top (silk threads, stars), chosen in Settings
// (/api/state backdrop). Shaders compiled in shaders/ (see build.sh), computed at
// half resolution (layer.textureSize) then scaled up: the blur hides it, the GPU works four times
// less. Layers add their light to the base (alpha 0: additive blending). Crossfade on each change.
// Nothing still: no burn-in on the TV. Coordinates in 1920x1080.
import QtQuick
import QtQuick.Effects

Item {
    id: root
    property string base: "aurora"
    property string overlay: "none"
    property real overlayOpacity: 1     // menu: softened layer, to keep the cards readable
    property color c1: "#9146ff"
    property color c2: "#2b4bdc"
    property color c3: "#b03a7a"
    property color bg: "#0b0710"
    property bool running: visible
    // Combination shown: follows base / overlay after a fade to black
    property string shownBase: base
    property string shownOverlay: overlay
    readonly property string wanted: base + "/" + overlay
    onWantedChanged: if (wanted !== shownBase + "/" + shownOverlay) swap.restart()

    Rectangle { anchors.fill: parent; color: root.bg }

    Item {
        id: layers
        anchors.fill: parent
        Loader {
            anchors.fill: parent
            active: root.shownBase !== "none"
            sourceComponent: root.shownBase === "aurora" ? blobsBg : baseShader
        }
        Loader {
            anchors.fill: parent
            opacity: root.overlayOpacity
            active: root.shownOverlay !== "none"
            sourceComponent: overlayShader
        }
    }
    SequentialAnimation {
        id: swap
        NumberAnimation { target: layers; property: "opacity"; to: 0; duration: 600; easing.type: Easing.InOutQuad }
        ScriptAction { script: { root.shownBase = root.base; root.shownOverlay = root.overlay } }
        NumberAnimation { target: layers; property: "opacity"; to: 1; duration: 900; easing.type: Easing.InOutQuad }
    }

    // Very blurry color blobs drifting slowly (rectangular shadows rounded into discs)
    Component {
        id: blobsBg
        Item {
            Repeater {
                model: [{ c: root.c1, o: 0.42, s: 700, x0: 200, y0: 120, dx: 520, dy: 260, d: 47000 },
                        { c: root.c2, o: 0.30, s: 640, x0: 1150, y0: 420, dx: -480, dy: -220, d: 61000 },
                        { c: root.c3, o: 0.28, s: 560, x0: 700, y0: 650, dx: 380, dy: -300, d: 53000 },
                        { c: root.c1, o: 0.20, s: 520, x0: 1400, y0: 60, dx: -300, dy: 340, d: 71000 }]
                RectangularShadow {
                    width: modelData.s; height: modelData.s; radius: modelData.s / 2
                    blur: 260; spread: 0
                    color: modelData.c; opacity: modelData.o
                    x: modelData.x0; y: modelData.y0
                    SequentialAnimation on x {
                        loops: Animation.Infinite; running: root.running
                        NumberAnimation { to: modelData.x0 + modelData.dx; duration: modelData.d; easing.type: Easing.InOutSine }
                        NumberAnimation { to: modelData.x0; duration: modelData.d; easing.type: Easing.InOutSine }
                    }
                    SequentialAnimation on y {
                        loops: Animation.Infinite; running: root.running
                        NumberAnimation { to: modelData.y0 + modelData.dy; duration: modelData.d * 0.8; easing.type: Easing.InOutSine }
                        NumberAnimation { to: modelData.y0; duration: modelData.d * 0.8; easing.type: Easing.InOutSine }
                    }
                }
            }
        }
    }

    Component { id: baseShader; ShaderLayer { shader: root.shownBase } }
    Component { id: overlayShader; ShaderLayer { shader: root.shownOverlay } }
    // Full-screen shader (base or layer), rendered at half resolution then smoothly scaled up
    component ShaderLayer: Item {
        property string shader
        layer.enabled: true
        layer.smooth: true
        layer.textureSize: Qt.size(width / 2, height / 2)
        ShaderEffect {
            anchors.fill: parent
            property real time: 0
            property real ratio: width / Math.max(1, height)
            property color c1: root.c1
            property color c2: root.c2
            property color c3: root.c3
            property color bg: root.bg
            fragmentShader: "shaders/" + parent.shader + ".frag.qsb"
            NumberAnimation on time {
                from: 0; to: 100000; duration: 100000000; loops: Animation.Infinite; running: root.running
            }
        }
    }
}
