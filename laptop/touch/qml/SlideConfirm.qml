import QtQuick

// Thanh truot xac nhan kieu DJI/QGC. Truot num het ve phai moi phat `confirmed`;
// tha giua chung thi num troi ve cho cu, khong co gi xay ra.
//
// holdMs > 0: truot het roi phai GIU them chung do (cat dong co tren khong la roi
// may bay — phai la dong tac co chu y, cung quy tac nut giu 2 s cua app laptop).
Item {
    id: root
    property string text: ""
    property color tint: "#35d7ff"
    property color textColor: "white"
    property int holdMs: 0
    property real progress: 0          // 0..1 trong luc dang giu
    readonly property real maxX: width - knob.width - 4
    readonly property bool atEnd: knob.x >= maxX - 1
    signal confirmed()

    implicitWidth: 380
    implicitHeight: 60

    function reset() {
        holdTimer.stop()
        holdAnim.stop()
        progress = 0
        back.start()
    }

    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: "#e60b1117"
        border.color: root.tint
        border.width: 2
        opacity: root.enabled ? 1 : 0.4

        Rectangle {  // phan da truot
            x: 2; y: 2
            height: parent.height - 4
            width: knob.x + knob.width - 2
            radius: height / 2
            color: Qt.rgba(root.tint.r, root.tint.g, root.tint.b, 0.25 + 0.5 * root.progress)
        }
        Text {
            anchors.fill: parent
            anchors.leftMargin: knob.width + 12
            anchors.rightMargin: 14
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            text: root.text
            color: root.textColor
            font.pixelSize: Math.max(12, root.height * 0.28)
            font.bold: true
            elide: Text.ElideRight
            opacity: 1 - 0.8 * knob.x / Math.max(1, root.maxX)
        }
    }

    Rectangle {
        id: knob
        x: 4; y: 4
        width: root.height - 8
        height: width
        radius: width / 2
        color: root.tint
        Text {
            anchors.centerIn: parent
            text: "»"
            font.pixelSize: parent.height * 0.55
            font.bold: true
            color: "#08111a"
        }
        NumberAnimation on x { id: back; to: 4; duration: 180; running: false }
    }

    MouseArea {
        id: area
        anchors.fill: parent
        enabled: root.enabled
        property real grab: 0
        property bool dragging: false
        // Chi bat khi cham DUNG num: vuot ngang qua thanh khong duoc tinh la truot.
        onPressed: (m) => {
            if (m.x < knob.x - 10 || m.x > knob.x + knob.width + 10) {
                m.accepted = false
                return
            }
            dragging = true
            grab = m.x - knob.x
            back.stop()
        }
        onPositionChanged: (m) => {
            if (!dragging)
                return
            knob.x = Math.max(4, Math.min(root.maxX, m.x - grab))
            if (root.atEnd && root.holdMs > 0) {
                if (!holdTimer.running) {
                    holdTimer.start()
                    holdAnim.start()
                }
            } else if (holdTimer.running) {
                holdTimer.stop()
                holdAnim.stop()
                root.progress = 0
            }
        }
        onReleased: {
            if (!dragging)
                return
            dragging = false
            if (root.atEnd && root.holdMs === 0)
                root.confirmed()
            root.reset()
        }
        onCanceled: {
            dragging = false
            root.reset()
        }
    }

    Timer {
        id: holdTimer
        interval: Math.max(1, root.holdMs)
        onTriggered: root.confirmed()   // van dang giu — tha tay sau do thi chi reset
    }
    NumberAnimation {
        id: holdAnim
        target: root; property: "progress"
        from: 0; to: 1; duration: root.holdMs
    }
}
