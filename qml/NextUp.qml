// Carte « Épisode suivant » (Jellyfin) dans les dernières secondes d'un épisode : miniature, titre, compte à rebours ;
// OK lance tout de suite, Retour reste (stream-box.lua, user-data/streambox/next_card). En bas à droite, au-dessus de
// la barre de lecture quand elle est affichée.
import QtQuick
import QtQuick.Effects

Item {
    id: root
    anchors.fill: parent
    readonly property var n: { try { return JSON.parse(osd.nextCard || "{}") } catch (e) { return {} } }
    readonly property bool barShown: { try { return !!JSON.parse(osd.bar || "{}").bar } catch (e) { return false } }
    readonly property bool shown: n.seconds !== undefined
    property var last: ({})
    onNChanged: if (shown) last = n

    Item {
        id: card
        width: 620; height: 170
        x: root.shown ? root.width - width - 70 : root.width + 40
        y: root.barShown ? root.height - 540 - height : root.height - 70 - height
        opacity: root.shown ? 1 : 0
        Behavior on x { NumberAnimation { duration: 380; easing.type: Easing.OutCubic } }
        Behavior on y { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
        Behavior on opacity { NumberAnimation { duration: 250 } }
        RectangularShadow { anchors.fill: parent; radius: 24; blur: 50; color: "black"; opacity: 0.6 }
        Rectangle { anchors.fill: parent; radius: 24; color: "#f0141820"; border.color: "#331565c0"; border.width: 1 }
        RoundImage {
            x: 20; anchors.verticalCenter: parent.verticalCenter
            width: 230; height: 130; radius: 14; placeholder: "#1b3c54"
            source: root.last.thumb || ""
        }
        Column {
            x: 272; width: card.width - 292
            anchors.verticalCenter: parent.verticalCenter
            spacing: 6
            Text { text: "ÉPISODE SUIVANT DANS " + (root.last.seconds || 0) + " S"; color: "#4a90e2"; font.pixelSize: 17; font.bold: true; font.letterSpacing: 2 }
            Text { width: parent.width; elide: Text.ElideRight; text: root.last.title || ""; color: "white"; font.pixelSize: 26; font.bold: true }
            Text { width: parent.width; elide: Text.ElideRight; text: root.last.episode || ""; color: "#d0c8e0"; font.pixelSize: 21 }
            Text { text: "OK : lancer  ·  Retour : rester"; color: "#a0ffffff"; font.pixelSize: 18 }
        }
        Rectangle {   // temps restant
            x: 20; y: card.height - 10; height: 4; radius: 2; color: "#1565c0"
            width: (card.width - 40) * Math.min(1, (root.last.seconds || 0) / 20)
            Behavior on width { NumberAnimation { duration: 1000 } }
        }
    }
}
