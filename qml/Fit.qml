// The interface's drawing area: 1920 wide and 1080 high at least, the other side stretched to the screen's shape
// (1920x1200 on a 16:10 screen such as the Steam Deck's, wider than 1920 in a wide window), then scaled to fill it
// exactly: no bands. What is pinned to an edge (help at the bottom, QR code, clock) follows it; the rest keeps its
// 1920x1080 coordinates, from the top left.
import QtQuick

Item {
    width: Math.max(1920, Math.round(1080 * parent.width / Math.max(1, parent.height)))
    height: Math.max(1080, Math.round(1920 * parent.height / Math.max(1, parent.width)))
    scale: parent.width / width
    transformOrigin: Item.TopLeft
}
