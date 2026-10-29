// TV menu with a mouse (Stream Player on a desktop): a click on an element focuses it as the arrows would (pick),
// then left click = OK and right click = ≡ (its options; rightKey "back" where there are none; "" = no key after
// pick). Off while the element is hidden or faded out (cards scrolled outside their area).
import QtQuick

MouseArea {
    required property var tv   // the menu (TvMenu)
    property string leftKey: "ok"
    property string rightKey: "menu"
    signal pick()
    anchors.fill: parent
    enabled: parent.visible && parent.opacity > 0.5
    acceptedButtons: Qt.LeftButton | Qt.RightButton
    cursorShape: Qt.PointingHandCursor
    onClicked: function (m) {
        pick()
        var k = m.button === Qt.RightButton ? rightKey : leftKey
        if (k) tv.key(k)
    }
}
