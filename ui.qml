// Stream Box : scène de l'appli (ui.py) : la vidéo de mpv, et par-dessus l'interface en QML (grand menu de la TV),
// dessinée en 1920x1080 et mise à l'échelle de l'écran.
import QtQuick
import StreamBox 1.0
import "qml"

Item {
    MpvVideo {
        anchors.fill: parent
    }
    Item {
        width: 1920
        height: 1080
        scale: Math.min(parent.width / 1920, parent.height / 1080)
        transformOrigin: Item.TopLeft
        TvMenu {
            objectName: "tvMenu"
        }
    }
}
