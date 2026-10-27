// Muted live of the chosen streamer (livePreview of ui.py, third libmpv player), in the background of the whole menu
// (TvMenu.bgLive), faded in once the first frame is there.
import QtQuick
import StreamBox 1.0

MpvVideo {
    required property var menu
    anchors.fill: parent
    which: "preview"
    // Never fully invisible: libmpv needs its render context (created on the first frame drawn) before a video
    // starts, otherwise the player has no video output
    opacity: livePreview.ready && menu.previewFor ? 1 : 0.001
    Behavior on opacity { NumberAnimation { duration: 300 } }
}
