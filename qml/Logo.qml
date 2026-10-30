// Owlink logo (assets/brand/owlink-mark.svg, drawn for dark backgrounds): a TV whose corners rise into an owl's
// tufts, its eyes, a signal and a link as the stand. Made by tools/brand/make.py
import QtQuick

Image {
    width: 60; height: 60
    source: Qt.resolvedUrl("../assets/brand/owlink-mark.svg")
    sourceSize: Qt.size(width * 2, height * 2)   // sharp at 4K as well
    smooth: true
}
