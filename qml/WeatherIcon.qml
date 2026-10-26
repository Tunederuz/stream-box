// Drawn and animated weather icon from the Open-Meteo WMO code: sun (or moon at night), sunny spells, clouds,
// fog, rain, snow, storm. The rays turn, the drops and flakes fall, the lightning flashes.
import QtQuick

Item {
    id: root
    property int code: 0
    property bool night: false
    width: 96
    height: 96
    readonly property string kind: code === 0 ? "clear" : code <= 2 ? "partly" : code === 3 ? "cloudy"
        : code === 45 || code === 48 ? "fog" : (code >= 71 && code <= 77) || code === 85 || code === 86 ? "snow"
        : code >= 95 ? "storm" : (code >= 51 && code <= 67) || (code >= 80 && code <= 82) ? "rain" : "cloudy"
    readonly property bool showSun: kind === "clear" || kind === "partly"
    readonly property bool showCloud: kind !== "clear"

    // Sun: disc and rays turning slowly
    Item {
        id: sun
        visible: root.showSun && !root.night
        width: root.kind === "clear" ? root.width * 0.8 : root.width * 0.55
        height: width
        x: root.kind === "clear" ? (root.width - width) / 2 : root.width * 0.05
        y: root.kind === "clear" ? (root.height - height) / 2 : root.height * 0.02
        Item {
            anchors.fill: parent
            RotationAnimation on rotation { from: 0; to: 360; duration: 60000; loops: Animation.Infinite }
            Repeater {
                model: 8
                Rectangle {
                    width: sun.width * 0.09; height: sun.width * 0.2; radius: width / 2
                    color: "#ffc94a"
                    x: sun.width / 2 - width / 2; y: 0
                    transform: Rotation { origin.x: width / 2; origin.y: sun.height / 2; angle: index * 45 }
                }
            }
        }
        Rectangle {
            anchors.centerIn: parent
            width: parent.width * 0.52; height: width; radius: width / 2
            color: "#ffc94a"
        }
    }
    // Moon (at night, clear sky or sunny spells): crescent
    Canvas {
        visible: root.showSun && root.night
        width: root.kind === "clear" ? root.width * 0.7 : root.width * 0.5
        height: width
        x: root.kind === "clear" ? (root.width - width) / 2 : root.width * 0.06
        y: root.kind === "clear" ? (root.height - height) / 2 : root.height * 0.04
        onPaint: {
            var c = getContext("2d"), r = width / 2
            c.reset()
            c.fillStyle = "#e8e2f4"
            c.beginPath(); c.arc(r, r, r, 0, 2 * Math.PI); c.fill()
            c.globalCompositeOperation = "destination-out"
            c.beginPath(); c.arc(r * 1.45, r * 0.7, r * 0.85, 0, 2 * Math.PI); c.fill()
        }
    }
    // Cloud: three discs and a rounded base, drifting a little
    Item {
        id: cloud
        visible: root.showCloud && root.kind !== "fog"
        width: root.width * 0.86
        height: root.height * 0.5
        x: root.width * 0.1
        y: root.kind === "partly" ? root.height * 0.38 : root.height * 0.18
        readonly property color tint: root.kind === "storm" ? "#8a85a0" : root.kind === "cloudy" ? "#b4afc2" : "#e0daea"
        SequentialAnimation on x {
            loops: Animation.Infinite
            NumberAnimation { to: root.width * 0.14; duration: 4000; easing.type: Easing.InOutSine }
            NumberAnimation { to: root.width * 0.06; duration: 4000; easing.type: Easing.InOutSine }
        }
        Rectangle { x: 0; y: cloud.height * 0.45; width: cloud.width; height: cloud.height * 0.55; radius: height / 2; color: cloud.tint }
        Rectangle { x: cloud.width * 0.12; y: cloud.height * 0.22; width: cloud.height * 0.6; height: width; radius: width / 2; color: cloud.tint }
        Rectangle { x: cloud.width * 0.36; y: 0; width: cloud.height * 0.85; height: width; radius: width / 2; color: cloud.tint }
    }
    // Rain and snow: drops or flakes falling under the cloud
    Repeater {
        model: root.kind === "rain" || root.kind === "snow" ? 3 : 0
        Rectangle {
            readonly property bool snow: root.kind === "snow"
            width: snow ? root.width * 0.09 : root.width * 0.05
            height: snow ? width : root.width * 0.16
            radius: width / 2
            color: snow ? "white" : "#7fb2ff"
            rotation: snow ? 0 : 15
            x: root.width * (0.28 + index * 0.2)
            SequentialAnimation on y {
                loops: Animation.Infinite
                PauseAnimation { duration: index * 300 }
                NumberAnimation { from: root.height * 0.62; to: root.height * 0.95; duration: snow ? 1800 : 900 }
            }
            SequentialAnimation on opacity {
                loops: Animation.Infinite
                PauseAnimation { duration: index * 300 }
                NumberAnimation { from: 1; to: 0; duration: snow ? 1800 : 900 }
            }
        }
    }
    // Storm: flashing lightning
    Canvas {
        visible: root.kind === "storm"
        width: root.width * 0.3; height: root.height * 0.4
        x: root.width * 0.38; y: root.height * 0.55
        onPaint: {
            var c = getContext("2d"), w = width, h = height
            c.reset()
            c.fillStyle = "#ffd84a"
            c.beginPath(); c.moveTo(w * 0.55, 0); c.lineTo(0, h * 0.58); c.lineTo(w * 0.45, h * 0.58)
            c.lineTo(w * 0.3, h); c.lineTo(w, h * 0.38); c.lineTo(w * 0.55, h * 0.38); c.closePath(); c.fill()
        }
        SequentialAnimation on opacity {
            loops: Animation.Infinite
            PauseAnimation { duration: 2200 }
            NumberAnimation { to: 0.2; duration: 80 }
            NumberAnimation { to: 1; duration: 80 }
            NumberAnimation { to: 0.2; duration: 80 }
            NumberAnimation { to: 1; duration: 120 }
        }
    }
    // Fog: sliding bands
    Repeater {
        model: root.kind === "fog" ? 3 : 0
        Rectangle {
            width: root.width * 0.8; height: root.height * 0.08; radius: height / 2
            color: "#b4afc2"; opacity: 0.85
            y: root.height * (0.3 + index * 0.18)
            SequentialAnimation on x {
                loops: Animation.Infinite
                NumberAnimation { to: root.width * (index % 2 ? 0.16 : 0.04); duration: 3000 + index * 500; easing.type: Easing.InOutSine }
                NumberAnimation { to: root.width * (index % 2 ? 0.04 : 0.16); duration: 3000 + index * 500; easing.type: Easing.InOutSine }
            }
        }
    }
}
