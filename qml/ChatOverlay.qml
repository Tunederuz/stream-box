// Chat Twitch avec émotes (appli Qt) : messages de chat_qt.py (via l'objet « chat » de ui.py), dans le coin choisi,
// avec les réglages de la télécommande (fond, taille). Mots et émotes s'enchaînent dans un Flow ; les émotes animées
// (GIF, WebP) bougent. Coordonnées en 1920x1080.
import QtQuick

Item {
    id: root
    anchors.fill: parent
    readonly property var messages: { try { return JSON.parse(chat.messages || "[]") } catch (e) { return [] } }
    readonly property bool atLeft: chat.corner === "tl" || chat.corner === "bl"
    readonly property bool atTop: chat.corner === "tl" || chat.corner === "tr"
    // Taille réglée pour le chat ASS (\fs) : Qt dessine plus grand pour la même valeur
    readonly property real fontSize: chat.size * 0.78
    readonly property real maxWidth: 820
    visible: chat.visible && messages.length > 0
    opacity: visible ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: 200 } }

    Rectangle {   // fond semi-transparent
        x: column.x - 14; y: column.y - 14
        width: column.width + 28; height: column.height + 28
        radius: 12
        color: "black"
        opacity: chat.bg / 100
        visible: chat.bg > 0
    }
    Column {
        id: column
        x: root.atLeft ? 40 : root.width - 40 - width
        y: root.atTop ? 40 : root.height - 40 - height
        spacing: 4
        Repeater {
            model: root.messages
            // Enveloppe à la largeur réellement occupée par le message (fond ajusté, alignement à droite possible) ;
            // le Flow dedans passe à la ligne à maxWidth
            Item {
                width: line.childrenRect.width
                height: line.height
                x: 0   // texte aligné à gauche dans le cadre, même dans un coin droit
                Flow {
                    id: line
                    readonly property var m: modelData
                    width: root.maxWidth
                    spacing: root.fontSize * 0.28
                    Text {
                        text: line.m.name
                        color: line.m.color
                        font.pixelSize: root.fontSize
                        font.bold: true
                        height: root.fontSize * 1.45
                        verticalAlignment: Text.AlignVCenter
                        style: Text.Outline
                        styleColor: "#cc000000"
                    }
                    Repeater {
                        model: line.m.parts
                        Loader {
                            sourceComponent: modelData.t === "e" ? emote : word
                            property var part: modelData
                        }
                    }
                }
            }
        }
    }
    Component {
        id: word
        Text {
            text: part.v
            color: "white"
            font.pixelSize: root.fontSize
            height: root.fontSize * 1.45
            verticalAlignment: Text.AlignVCenter
            style: Text.Outline
            styleColor: "#cc000000"
        }
    }
    Component {
        id: emote
        AnimatedImage {
            source: part.u
            height: root.fontSize * 1.45
            width: status === AnimatedImage.Ready && implicitHeight > 0 ? implicitWidth * height / implicitHeight : height
            fillMode: Image.PreserveAspectFit
            asynchronous: true
            cache: true
            playing: root.visible
        }
    }
}
