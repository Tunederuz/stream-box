// Stream Box : scène de l'appli (ui.py). Pour l'instant la vidéo seule ; le menu viendra se poser par-dessus.
import QtQuick
import StreamBox 1.0

Item {
    MpvVideo {
        anchors.fill: parent
    }
}
