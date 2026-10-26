// Stream Box logo: white tile, charcoal play triangle with rounded corners. Neutral, it fits the purple background
// as well as the red background of the YouTube tab (same drawing as the companion app icons)
import QtQuick
import QtQuick.Shapes

Rectangle {
    id: root
    width: 52; height: 52
    radius: width * 0.27
    color: "#f4f2f7"
    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            fillColor: "#17151c"; strokeColor: "#17151c"
            strokeWidth: root.width * 0.09
            joinStyle: ShapePath.RoundJoin
            startX: root.width * 0.39; startY: root.height * 0.32
            PathLine { x: root.width * 0.69; y: root.height * 0.5 }
            PathLine { x: root.width * 0.39; y: root.height * 0.68 }
            PathLine { x: root.width * 0.39; y: root.height * 0.32 }
        }
    }
}
