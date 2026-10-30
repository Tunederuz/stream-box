// Inlet logo (assets/brand/inlet-mark.svg, drawn for dark backgrounds): a screen open on its left side, a wave
// flowing into it. Made by tools/brand/make.py
import QtQuick

Image {
    width: 60; height: 60
    source: Qt.resolvedUrl("../assets/brand/inlet-mark.svg")
    sourceSize: Qt.size(width * 2, height * 2)   // sharp at 4K as well
    smooth: true
}
