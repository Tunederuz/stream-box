// Muted live preview in the grown card of the Live tab (cardPreview of ui.py, third libmpv player): placed by
// TvMenu.startPreview, rounded like the card, faded in once the first frame is there.
import QtQuick
import QtQuick.Effects
import StreamBox 1.0

Item {
    id: root
    required property var menu
    readonly property var r: menu.previewRect
    property var last: ({ x: 0, y: 0, width: 160, height: 90 })   // stays put while fading out
    onRChanged: if (r) last = r
    x: last.x; y: last.y; width: last.width; height: last.height
    // Never fully invisible: libmpv needs its render context (created on the first frame drawn) before a video
    // starts, otherwise the player has no video output
    opacity: cardPreview.ready && r ? 1 : 0.001
    Behavior on opacity { NumberAnimation { duration: 300 } }

    MpvVideo {
        anchors.fill: parent
        which: "preview"
        layer.enabled: true
        layer.effect: MultiEffect {
            maskEnabled: true
            maskSource: mask
            maskThresholdMin: 0.5
            maskSpreadAtMin: 1.0
        }
    }
    Item {
        id: mask
        anchors.fill: parent
        layer.enabled: true
        layer.smooth: true
        visible: false
        Rectangle { anchors.fill: parent; radius: 16; color: "black" }   // same corners as the card (VideoCard)
    }
}
