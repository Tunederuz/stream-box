// Fond animé de l'écran d'accueil et du menu sans vidéo derrière, au choix (Réglages → « Fond animé », /api/state
// backdrop) : taches floues qui dérivent, nappes de couleur fluides, aurore boréale, fils de soie (shaders compilés
// dans shaders/, voir build.sh), bulles lumineuses. Les shaders sont calculés en basse résolution (layer.textureSize)
// puis agrandis : le flou ne se voit pas, la puce graphique travaille quatre fois moins. Rien de fixe : pas de marquage
// de la TV. Coordonnées en 1920x1080.
import QtQuick
import QtQuick.Effects
import QtQuick.Particles

Item {
    id: root
    property string style: "aurora"
    property color c1: "#9146ff"
    property color c2: "#2b4bdc"
    property color c3: "#b03a7a"
    property color bg: "#0b0710"
    property bool running: visible
    readonly property var shaders: ({ fluid: true, borealis: true, silk: true })

    Rectangle { anchors.fill: parent; color: root.bg }

    Loader {
        anchors.fill: parent
        sourceComponent: root.shaders[root.style] ? shaderBg : root.style === "bubbles" ? bubblesBg : blobsBg
    }

    // Taches de couleur très floues qui dérivent lentement (ombres rectangulaires arrondies en disque)
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

    // Shader plein écran, rendu au quart de la résolution puis agrandi en douceur
    Component {
        id: shaderBg
        Item {
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
                fragmentShader: "shaders/" + root.style + ".frag.qsb"
                NumberAnimation on time {
                    from: 0; to: 100000; duration: 100000000; loops: Animation.Infinite; running: root.running
                }
            }
        }
    }

    // Bulles lumineuses qui montent doucement, par-dessus deux taches floues
    Component {
        id: bubblesBg
        Item {
            Loader { anchors.fill: parent; sourceComponent: blobsBg; opacity: 0.6 }
            ParticleSystem { id: ps; running: root.running }
            Emitter {
                system: ps
                width: parent.width; height: 200; y: parent.height - 50
                emitRate: 3; lifeSpan: 22000; startTime: 22000; lifeSpanVariation: 6000
                size: 70; sizeVariation: 60; endSize: 120
                velocity: AngleDirection { angle: -90; angleVariation: 25; magnitude: 55; magnitudeVariation: 30 }
                acceleration: AngleDirection { angle: 0; angleVariation: 180; magnitude: 4 }
            }
            Wander { system: ps; xVariance: 60; pace: 30 }
            ImageParticle {
                system: ps
                source: "qrc:///particleresources/glowdot.png"
                color: root.c1; colorVariation: 0.1
                redVariation: 0.2; blueVariation: 0.3
                alpha: 0.3; alphaVariation: 0.2
                entryEffect: ImageParticle.Fade
            }
        }
    }
}
