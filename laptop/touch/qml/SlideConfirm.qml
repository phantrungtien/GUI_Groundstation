import QtQuick

// Thanh truot xac nhan kieu DJI/QGC. Truot num het ve phai moi phat `confirmed`;
// tha giua chung thi num troi ve cho cu, khong co gi xay ra.
Item {
    id: root
    property string text: ""
    property color tint: "#35d7ff"
    property color textColor: "white"
    readonly property real maxX: width - knob.width - 4
    readonly property bool atEnd: knob.x >= maxX - 1
    signal confirmed()

    implicitWidth: 380
    implicitHeight: 60

    function reset() {
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
            color: Qt.rgba(root.tint.r, root.tint.g, root.tint.b, 0.25)
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
        }
        onReleased: {
            if (!dragging)
                return
            dragging = false
            if (root.atEnd)
                root.confirmed()
            root.reset()
        }
        onCanceled: {
            dragging = false
            root.reset()
        }
    }
}
