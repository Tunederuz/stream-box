// Icônes de la barre de lecture, dessinées (pas de caractères Unicode, dont le rendu dépend des polices : emoji…) :
// back (−10 s), fwd (+10 s), play, pause, tracks (sous-titres), chapter (chapitre suivant), next (épisode suivant).
import QtQuick
import QtQuick.Shapes

Item {
    id: root
    property string name: "play"
    property color color: "white"
    width: 34; height: 34

    // Lecture : triangle
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
    // Pause : deux barres
    Row {
        visible: root.name === "pause"
        anchors.centerIn: parent
        spacing: 7
        Rectangle { width: 8; height: 26; radius: 2; color: root.color }
        Rectangle { width: 8; height: 26; radius: 2; color: root.color }
    }
    // −10 s / +10 s : flèche en arc et « 10 »
    Item {
        visible: root.name === "back" || root.name === "fwd"
        anchors.fill: parent
        transform: Scale { origin.x: 17; xScale: root.name === "fwd" ? -1 : 1 }
        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                fillColor: "transparent"; strokeColor: root.color; strokeWidth: 3; capStyle: ShapePath.RoundCap
                startX: 8; startY: 9
                PathArc { x: 17; y: 31; radiusX: 13; radiusY: 13; useLargeArc: true; direction: PathArc.Counterclockwise }
            }
            ShapePath {   // pointe de la flèche
                fillColor: root.color; strokeColor: "transparent"
                startX: 3; startY: 3
                PathLine { x: 13; y: 6 }
                PathLine { x: 5; y: 13 }
                PathLine { x: 3; y: 3 }
            }
        }
    }
    Text {
        visible: root.name === "back" || root.name === "fwd"
        anchors.centerIn: parent; anchors.verticalCenterOffset: 2
        text: "10"; color: root.color; font.pixelSize: 11; font.bold: true
    }
    // Sous-titres : cadre arrondi et deux lignes de texte
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
    // Chapitre suivant / épisode suivant : triangle et barre (épisode : deux triangles)
    Shape {
        visible: root.name === "chapter" || root.name === "next"
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            fillColor: root.color; strokeColor: "transparent"
            startX: root.name === "next" ? 3 : 7; startY: 6
            PathLine { x: root.name === "next" ? 15 : 22; y: 17 }
            PathLine { x: root.name === "next" ? 3 : 7; y: 28 }
            PathLine { x: root.name === "next" ? 3 : 7; y: 6 }
        }
        ShapePath {
            fillColor: root.name === "next" ? root.color : "transparent"; strokeColor: "transparent"
            startX: 15; startY: 6
            PathLine { x: 27; y: 17 }
            PathLine { x: 15; y: 28 }
            PathLine { x: 15; y: 6 }
        }
    }
    Rectangle {
        visible: root.name === "chapter" || root.name === "next"
        x: root.name === "next" ? 27 : 23; y: 6
        width: 4; height: 22; radius: 1; color: root.color
    }
}
