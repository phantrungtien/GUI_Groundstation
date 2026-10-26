import QtQuick
import QtQuick.Controls
import QtMultimedia
import Gcs 1.0

// Man bay cam ung kieu DJI. Moi lenh deu phai TRUOT de xac nhan (nguoi dung chot
// 15/09/2026, ke ca RTL/LAND/DISARM). Cat dong co cung chi truot, hau qua ghi ngay tren thanh.
//
// Khong co logic an toan nao o file nay: bam nut chi mo thanh truot, truot het
// thi goi backend.act() -> laptop/commands.py.
// Goc la Item chu khong phai ApplicationWindow: man nay nam trong mot tab cua
// app laptop (QQuickWidget). Dong goi rieng thi boc them mot cua so ben ngoai.
Item {
    id: win
    width: 1280
    height: 720

    Rectangle { anchors.fill: parent; color: theme.BG_DEEP }

    readonly property var st: backend.state
    // Mot don vi co gian theo CA HAI chieu (thieu chieu nao lay chieu do): laptop
    // ~1260x620 -> ~1; dien thoai ngang ~800x330 dp -> ~0.52. San 0.5 chu khong 0.7:
    // 0.7 tren man 330 dp la cot nut dai hon man hinh, de len la ban va o camera.
    readonly property real s: Math.max(0.5, Math.min(1.4, Math.min(height / 640, width / 1138)))
    // Chu khong nho theo s xuong duoi 0.85 — nho hon nua la khong doc noi khi bay.
    readonly property real f: Math.max(s, 0.85)
    // Man thap (dien thoai ngang): bo chan troi, nut phai xep 2x2, bot HDG (da co
    // la ban), bang duong bay cuon duoc. Cao hon 480 dp thi giu bo cuc laptop.
    readonly property bool compact: height < 480
    // Dong ho tu the: tinh o day de ca no lan dai canh bao ban do cung dung. Doc
    // `x`/`width` cua chinh WidgetItem tu binding khac ra null luc nap (kieu Python).
    readonly property real dialW: compact ? Math.max(84, 110 * s) : 100 * s
    readonly property real dialX: !compact ? width - dialW - 14 * s
                                  : pip.visible ? pip.x + pip.width + 10 * s : 14 * s
    property bool camBig: false
    property string pending: ""      // lenh dang cho truot
    property string pendingArg: ""
    property real takeoffAlt: 5
    // Do cao task Chua chay: cat canh + bay tim, va ha cach lua bao nhieu m de tha. Rieng
    // voi takeoffAlt. Gioi han + mac dinh lay tu node (st.fireLim, bridge doc YAML cua
    // drone): openFire() dua ve mac dinh khi so dang nho nam ngoai khoang (doi drone).
    property real fireAlt: 20
    property real fireDrop: 20
    onFireAltChanged: if (fireDrop > fireAlt) fireDrop = fireAlt  // khong leo len de tha
    function openFire() {
        var L = st.fireLim
        if (fireAlt < L.min || fireAlt > L.max) {  // doi drone: ca hai ve mac dinh cua node
            fireAlt = L.search
            fireDrop = Math.min(L.drop, L.search)
        } else if (fireDrop < L.min || fireDrop > fireAlt)
            fireDrop = Math.min(L.drop, fireAlt)
        ask("fire")
    }
    // Cham-giu ban do thay cho menu chuot phai cua tab Bay cu: nho lai diem vua
    // cham de "dat waypoint o day" / "bay toi day" con biet la o dau.
    property bool wpOpen: false
    readonly property int holdMs: 2000  // giu bao lau moi chon diem tren ban do
    property real wpX: 0
    property real wpY: 0
    // [lat, lon] cua diem "bay toi day" dang cho truot. Chot bang toa do chu
    // khong giu pixel: ban do bam theo drone, pixel cu = cho khac sau vai giay.
    property var gotoAt: null
    // Can ao. Giu o day chu khong trong MouseArea de hai nut leo/ha dung chung.
    property real stickX: 0
    property real stickY: 0
    property real climb: 0

    function tr(key, args) { return backend.tf(key, args || {}, backend.lang) }
    function pushStick() { backend.stick(stickX, stickY, climb) }
    function lvl(l) {
        return l === "crit" ? theme.CRIT : l === "warn" ? theme.WARN
             : l === "ok" ? theme.OK : theme.MUTED
    }
    function num(v, d, unit) {
        return (v === undefined || v === null) ? "--" : v.toFixed(d) + (unit || "")
    }
    function mmss(sec) {
        return Math.floor(sec / 60) + ":" + ("0" + (sec % 60)).slice(-2)
    }
    function ask(action, arg) {
        wpOpen = false      // hai bang cung o mot cho, khong duoc chong len nhau
        pending = action
        pendingArg = arg || ""
        askTimer.restart()
    }
    function danger(a) { return ["disarm", "land", "rtl", "kill"].indexOf(a) >= 0 }
    function titleText() {
        return {
            "arm": "ARM", "disarm": "DISARM", "takeoff": tr("touch.btn_takeoff"),
            "land": tr("touch.btn_land"), "rtl": tr("touch.btn_rtl") + " (RTL)",
            "kill": tr("touch.do_kill"), "modePick": tr("touch.btn_mode") + "  (" + st.fcMode + ")",
            "mode": tr("touch.btn_mode") + ":  " + st.fcMode + "  →  " + pendingArg,
            // Toa do tren tieu de la cho DUY NHAT nguoi bay doi chieu duoc diem
            // vua chi: diem do khong ve ra ban do, va ban do thi dang chay theo
            // drone. Dung chung dong chu voi vet ghi o tab Thong bao.
            "goto": gotoAt ? tr("act.goto", {"lat": gotoAt[0], "lon": gotoAt[1],
                                             "alt": st.wpAlt}) : "",
            "fire": gotoAt ? tr("act.fire_target", {"lat": gotoAt[0], "lon": gotoAt[1],
                                                    "alt": fireAlt, "drop": fireDrop}) : "",
            "taskStart": tr("touch.task_start_title"),
            "taskStop": tr("touch.task_stop_title")
        }[pending] || ""
    }
    function openWp(x, y) {
        win.wpX = x
        win.wpY = y
        win.pending = ""
        win.wpOpen = true
    }
    function slideText() {
        var what = {
            "arm": tr("touch.do_arm"), "disarm": tr("touch.do_disarm"),
            "takeoff": tr("touch.do_takeoff", {"alt": takeoffAlt}),
            "land": tr("touch.do_land"), "rtl": tr("touch.do_rtl"),
            "kill": tr("touch.do_kill"), "mode": tr("touch.do_mode", {"name": pendingArg}),
            "goto": tr("touch.do_goto", {"alt": st.wpAlt}),
            "fire": tr("touch.do_fire", {"alt": fireAlt, "drop": fireDrop}),
            "taskStart": tr("touch.do_task_start"), "taskStop": tr("touch.do_task_stop")
        }[pending] || ""
        return tr("touch.slide", {"what": what})
    }

    // Het duong xuong drone (ngat, SiK dut, REPLAY) thi lenh dang cho bi huy:
    // truot xong ma lenh roi vao khoang khong con te hon khong cho truot.
    Connections {
        target: backend
        // Dong o camera va bang duong bay khi VUA dut ket noi — SUON XUONG, khong
        // phai theo muc. `stateChanged` ban 5 Hz: kiem theo muc thi luc chua ket
        // noi, bang duong bay vua mo bang cham-giu la 200 ms sau tu dong dong,
        // nhin nhu cham-giu khong an gi. Soan duong bay khi chua cam radio la
        // viec binh thuong; chot an toan nam o `sendWp()` chu khong o cho mo bang.
        property bool wasConnected: false
        function onStateChanged() {
            if (!backend.state.live && win.pending !== "")
                win.pending = ""
            if (wasConnected && !backend.state.connected) {
                win.camBig = false
                win.wpOpen = false
            }
            wasConnected = backend.state.connected
        }
    }
    Timer { id: askTimer; interval: 15000; onTriggered: win.pending = "" }

    // ---- nen: ban do hoac camera -------------------------------------------
    WidgetItem {
        id: mainView
        anchors.fill: parent
        name: win.camBig ? (backend.phone ? "" : "video") : "map"
        fps: win.camBig ? 30 : 5
    }
    MouseArea {  // GIU 2 s de chon diem, keo de di, cham dup de bam theo drone
        id: mapArea
        anchors.fill: parent
        enabled: !win.camBig
        pressAndHoldInterval: win.holdMs
        property point last
        property point down
        property bool dragged: false
        onPressed: (m) => {
            last = Qt.point(m.x, m.y); down = last; dragged = false
            holdRing.start()
        }
        onReleased: holdRing.stop()
        onCanceled: holdRing.stop()
        onPositionChanged: (m) => {
            // Chua qua nguong keo thi KHONG pan: pan (du 1 px) la tat bam theo
            // drone. Do that: cham dup ma ngon tay rung 2 px o lan cham thu hai
            // -> ban do khong ve cho drone, follow=False.
            if (!dragged && Math.abs(m.x - down.x) + Math.abs(m.y - down.y)
                    <= Qt.styleHints.startDragDistance)
                return
            dragged = true
            holdRing.stop()  // keo ban do = khong chon diem
            backend.mapPan(m.x - last.x, m.y - last.y)
            last = Qt.point(m.x, m.y)
            mainView.update()
        }
        // Chon diem (dat waypoint / bay toi day) phai GIU holdMs — nguoi dung
        // chot 19/09: cham mot cai la nhan ngay thi de cham nham. Vong tron
        // quanh ngon tay chay du mot vong trong luc giu, de biet con bao lau va
        // biet tha ra la huy. Keo ban do thi khong tinh.
        onDoubleClicked: { win.wpOpen = false; backend.mapFollow(); mainView.update() }
        onWheel: (w) => { backend.mapZoom(w.angleDelta.y > 0 ? 1 : -1); mainView.update() }
        onPressAndHold: (m) => {
            holdRing.stop()
            if (!dragged)
                win.openWp(m.x, m.y)
        }
    }
    Item {  // vong tron dem nguoc luc giu de chon diem
        id: holdRing
        objectName: "holdRing"
        property real p: 0
        width: 76 * s; height: width
        x: mapArea.down.x - width / 2
        y: mapArea.down.y - height / 2
        visible: p > 0
        function start() { anim.restart() }
        function stop() { anim.stop(); p = 0 }
        NumberAnimation on p { id: anim; running: false; from: 0; to: 1; duration: win.holdMs }
        onPChanged: ring.requestPaint()
        Canvas {
            id: ring
            anchors.fill: parent
            onPaint: {
                var c = getContext("2d"), r = width / 2 - 5 * s
                c.reset()
                c.lineWidth = 6 * s
                c.strokeStyle = "#66000000"
                c.beginPath(); c.arc(width / 2, height / 2, r, 0, 2 * Math.PI); c.stroke()
                c.strokeStyle = theme.ACCENT
                c.beginPath()
                c.arc(width / 2, height / 2, r, -Math.PI / 2, -Math.PI / 2 + 2 * Math.PI * holdRing.p)
                c.stroke()
            }
        }
        Rectangle {  // cham giua: dung cho se chon
            anchors.centerIn: parent
            width: 8 * s; height: width; radius: width / 2
            color: theme.ACCENT
        }
    }
    PinchHandler {  // hai ngon: moi lan to/nho 1,5 lan = mot bac zoom
        target: null
        enabled: !win.camBig
        property real base: 1
        onActiveChanged: base = 1
        onActiveScaleChanged: {
            if (activeScale / base > 1.5) { backend.mapZoom(1); base = activeScale }
            else if (activeScale / base < 0.67) { backend.mapZoom(-1); base = activeScale }
            mainView.update()
        }
    }

    // ---- thanh tren cung ----------------------------------------------------
    Rectangle {
        id: topBar
        anchors { left: parent.left; right: parent.right; top: parent.top }
        height: Math.max(52 * s, 34 * f)
        gradient: Gradient {
            GradientStop { position: 0; color: "#f008111a" }
            GradientStop { position: 1; color: "#9908111a" }
        }
        Row {
            anchors { left: parent.left; leftMargin: 10 * s; verticalCenter: parent.verticalCenter }
            spacing: 12 * s
            // Dien thoai: thanh nay LA thanh cong cu duy nhat (kieu QGC/DJI) — nut ☰
            // mo menu cac trang khac (app.py), thay hang tab + banner cua laptop.
            Rectangle {
                objectName: "menuBtn"
                visible: backend.phone
                anchors.verticalCenter: parent.verticalCenter
                height: pill.height; width: height
                radius: 8 * s
                color: theme.SURFACE
                border.color: theme.BORDER
                Text { anchors.centerIn: parent; text: "☰"; color: theme.TEXT; font.pixelSize: 18 * f }
                MouseArea { anchors.fill: parent; anchors.margins: -6; onClicked: backend.menu() }
            }
            Rectangle {
                id: pill
                height: Math.max(34 * s, pillText.implicitHeight + 6)
                width: pillText.implicitWidth + 24 * s
                radius: height / 2
                anchors.verticalCenter: parent.verticalCenter
                color: lvl(st.statusLevel)
                Text {
                    id: pillText
                    anchors.centerIn: parent
                    text: st.status
                    color: theme.BG_DEEP
                    font.pixelSize: 15 * f
                    font.bold: true
                }
            }
            Rectangle {  // che do bay — cham de doi, nhu "Flight Mode" tren thanh cong cu QGC
                objectName: "modeChip"
                anchors.verticalCenter: parent.verticalCenter
                height: pill.height
                width: modeText.implicitWidth + 20 * s
                radius: 8 * s
                color: "transparent"
                border.color: st.live ? theme.BORDER : "transparent"
                Text {
                    id: modeText
                    anchors.centerIn: parent
                    text: (st.fcMode || "--") + (st.live ? " ▾" : "")
                    color: theme.TEXT
                    font.pixelSize: 18 * f
                    font.bold: true
                }
                MouseArea { anchors.fill: parent; enabled: st.live; onClicked: ask("modePick") }
            }
            // ---- so nguoi: giao dien cuu ho, day la con so nguoi lai can thay
            // nhat. Co nguoi -> nen ACCENT dac (khac han mau trang thai OK/WARN/
            // CRIT cua vien ben trai). Khong biet (mat hinh / dung hinh / /status
            // im) -> "--" vien xam, KHONG an: o bien mat de bi bo qua hon o ghi "--".
            Rectangle {
                id: personsBar
                objectName: "persons"
                property bool known: st.persons !== null && st.persons !== undefined
                property string value: known ? String(st.persons) : "--"
                property color word: known && st.persons > 0 ? theme.BG_DEEP : theme.TEXT_DIM
                visible: !!st.hasVideo
                anchors.verticalCenter: parent.verticalCenter
                height: Math.max(40 * s, personsRow.implicitHeight + 4)
                width: personsRow.implicitWidth + 28 * s
                radius: 8 * s
                color: !known ? "transparent" : st.persons > 0 ? theme.ACCENT : theme.SURFACE_HI
                border.width: known ? 0 : 2 * s
                border.color: theme.BORDER
                Row {
                    id: personsRow
                    anchors.centerIn: parent
                    spacing: 10 * s
                    Text {
                        visible: !win.compact
                        anchors.verticalCenter: parent.verticalCenter
                        text: tr("fly.persons_pre")
                        color: personsBar.word
                        font.pixelSize: 15 * f
                        font.bold: true
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: personsBar.value
                        color: !personsBar.known ? theme.MUTED
                               : st.persons > 0 ? theme.BG_DEEP : theme.TEXT
                        font.pixelSize: 28 * f
                        font.bold: true
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: tr("fly.persons_post")
                        color: personsBar.word
                        font.pixelSize: 15 * f
                        font.bold: true
                    }
                }
            }
        }
        // Chi bao kieu QGC/DJI: cham mau = muc, nhan, gia tri. Mau lay tu lan cuoi THAT
        // SU co goi (backend._links), khong tu viec adapter con chay.
        Row {
            anchors { right: parent.right; rightMargin: 12 * s; verticalCenter: parent.verticalCenter }
            spacing: 16 * s
            Ind {  // duong MAVLink dang dung: SiK hay 4G (DualLink), % mat goi
                objectName: "linkInd"
                label: st.linkPath || "SiK"
                value: st.linkLevel === "ok" || st.linkLevel === "warn" ? num(st.linkLoss, 0, "%") : ""
                lv: st.linkLevel
            }
            Ind {  // nua companion (task/video/so nguoi) qua Tailscale
                visible: st.remoteLevel !== null && st.remoteLevel !== undefined
                label: "Jetson"
                lv: st.remoteLevel || "none"
            }
            Ind {
                label: "GPS"
                value: st.sats === null || st.sats === undefined ? "--" : String(st.sats)
                lv: st.sats === null || st.sats === undefined ? "none" : st.gpsLevel
            }
            Ind {
                label: "PIN"
                value: st.battPct === null || st.battPct === undefined ? num(st.volt, 1, "V")
                       : st.battPct + "% " + num(st.volt, 1, "V")
                lv: st.battPct === null || st.battPct === undefined ? "none" : st.battLevel
            }
        }
    }

    // ---- hai nguon vi tri lech nhau (kich ban #8) ---------------------------
    // Dong rieng chu khong lan vao AlertBook: no dung suot trong luc con lech,
    // vao do la dem "xN" chay loan trong khi noi dung chi la mot.
    Rectangle {
        id: divergeBar
        visible: st.diverge !== null && st.diverge !== undefined
        anchors { top: topBar.bottom; topMargin: visible ? 6 * s : 0
                  horizontalCenter: parent.horizontalCenter }
        width: dvText.implicitWidth + 24 * s
        height: visible ? 28 * s : 0
        radius: 8 * s
        color: theme.CRIT
        Text {
            id: dvText
            anchors.centerIn: parent
            text: tr("fly.diverge", {"m": st.diverge || 0})
            color: theme.BG_DEEP
            font.pixelSize: 14 * f
            font.bold: true
        }
    }

    // ---- dong ho tu the: chan troi (pitch/roll) trong vong la ban (yaw), kieu QGC ----
    // Mot dong ho thay hai o cu (chan troi goc trai + la ban goc phai). Man thap: o goc
    // duoi, giua o camera va thanh so lieu (cum dong ho kieu DJI) — cot nut phai can
    // ca chieu cao. Man cao: goc tren-phai nhu la ban cu.
    WidgetItem {
        objectName: "dial"
        name: "dial"
        fps: 10
        width: win.dialW
        height: width
        x: win.dialX
        y: win.compact ? win.height - height - 10 * s : topBar.height + 8 * s
    }

    // ---- dong "san sang ARM": nam CO DINH o day, loi noi len thi DE LEN no ----
    Rectangle {
        id: readyBar
        objectName: "readyBar"
        visible: !!st.ready
        anchors { top: divergeBar.bottom; topMargin: 6 * s; horizontalCenter: parent.horizontalCenter }
        width: Math.min(560 * s, win.width * 0.5)
        height: rt.implicitHeight + 10 * s
        radius: 8 * s
        color: st.ready && st.ready.ok ? theme.OK : theme.WARN
        Text {
            id: rt
            anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 8 * s }
            text: st.ready ? st.ready.text : ""
            // Mot dong: cao bang dong loi thi dong loi dau tien che kin no.
            elide: Text.ElideRight
            horizontalAlignment: Text.AlignHCenter
            color: theme.BG_DEEP
            font.pixelSize: 14 * f
            font.bold: true
        }
    }

    // ---- canh bao DUNG YEN: failsafe/pin luc chua ARM, "ve nha ngay" luc bay ---
    // Khac AlertBook: khong tu tat, con dung thi con hien. Dong loi noi len thi
    // de len o day nhu de len dong san sang ARM.
    Column {
        objectName: "warnCol"
        anchors { top: readyBar.visible ? readyBar.bottom : divergeBar.bottom; topMargin: 4 * s
                  horizontalCenter: parent.horizontalCenter }
        width: Math.min(560 * s, win.width * 0.5)
        spacing: 4 * s
        Repeater {
            model: st.warns || []
            delegate: Rectangle {
                width: parent.width
                height: wt.implicitHeight + 10 * s
                radius: 8 * s
                color: modelData.crit ? theme.CRIT : "#e6f4d35e"
                Text {
                    id: wt
                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 8 * s }
                    text: modelData.text
                    wrapMode: Text.Wrap
                    horizontalAlignment: Text.AlignHCenter
                    color: theme.BG_DEEP
                    font.pixelSize: (modelData.crit ? 16 : 13) * f
                    font.bold: true
                }
            }
        }
    }

    // ---- dong loi (AlertBook dung chung voi app laptop) ----------------------
    Column {
        z: 1  // de len dong "san sang ARM" o cung cho
        anchors { top: divergeBar.bottom; topMargin: 6 * s; horizontalCenter: parent.horizontalCenter }
        width: Math.min(560 * s, win.width * 0.5)
        spacing: 4 * s
        Repeater {
            model: st.alerts
            delegate: Rectangle {
                width: parent.width
                height: at.implicitHeight + 10 * s
                radius: 8 * s
                color: modelData.crit ? theme.CRIT : theme.WARN
                // Cham = mo tab Thong bao toi dung dong nay, doc ca lich su quanh no
                MouseArea { anchors.fill: parent; onClicked: backend.showMessage(modelData.text) }
                Text {
                    id: at
                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 8 * s }
                    text: modelData.text
                    wrapMode: Text.Wrap
                    horizontalAlignment: Text.AlignHCenter
                    color: theme.BG_DEEP
                    font.pixelSize: 14 * f
                    font.bold: true
                }
            }
        }
    }

    // ---- nut lenh: trai = bay, phai = dong co / che do ----------------------
    Column {
        id: leftCol
        anchors { left: parent.left; leftMargin: 14 * s }
        // Man thap: ngay duoi thanh tren (giua man thi de len o camera). Cao: giua man.
        y: win.compact ? topBar.height + 6 * s : (win.height - height) / 2
        spacing: 8 * s
        ActBtn { glyph: "▲"; label: tr("touch.btn_takeoff"); onTap: ask("takeoff") }
        ActBtn { glyph: "▼"; label: tr("touch.btn_land"); danger: true; onTap: ask("land") }
        ActBtn { glyph: "⌂"; label: tr("touch.btn_rtl"); danger: true; onTap: ask("rtl") }
    }
    Grid {
        id: rightCol
        columns: win.compact ? 2 : 1
        anchors { right: parent.right; rightMargin: 14 * s }
        // Man thap: ngay duoi la ban. Cao: giua man nhu ban laptop.
        // Man thap: ngay duoi thanh tren (dong ho tu the da xuong goc duoi). Cao: giua man.
        y: win.compact ? topBar.height + 6 * s : (win.height - height) / 2
        spacing: 8 * s
        ActBtn {
            glyph: st.armed ? "■" : "●"
            label: st.armed ? "DISARM" : "ARM"
            danger: st.armed
            onTap: ask(st.armed ? "disarm" : "arm")
        }
        ActBtn { glyph: "M"; label: tr("touch.btn_mode"); visible: !backend.phone; onTap: ask("modePick") }
        // Task Chua chay: bat roi moi chi diem chay duoc tren ban do (cham-giu).
        ActBtn {
            objectName: "taskBtn"
            glyph: "⚑"
            label: st.taskFire ? tr("touch.btn_task_stop") : tr("touch.btn_task")
            onTap: ask(st.taskFire ? "taskStop" : "taskStart")
        }
        ActBtn { glyph: "✕"; label: tr("touch.btn_kill"); danger: true; onTap: ask("kill") }
    }

    // ---- o camera / ban do nho: cham de doi cho ------------------------------
    Rectangle {
        id: pip
        objectName: "pip"
        visible: st.hasVideo || win.camBig
        anchors { left: parent.left; leftMargin: 14 * s; bottom: parent.bottom; bottomMargin: 10 * s }
        width: 240 * s
        height: 135 * s
        radius: 10 * s
        color: theme.BG
        border.color: theme.BORDER
        border.width: 2
        WidgetItem {
            id: pipItem
            anchors { fill: parent; margins: 2 }
            name: win.camBig ? "map" : (backend.phone ? "" : "video")
            fps: win.camBig ? 5 : 15
        }
        MouseArea { anchors.fill: parent; onClicked: win.camBig = !win.camBig }
    }

    // ---- video dien thoai: VideoOutput (GPU) thay WidgetItem "video" -------------
    // MediaCodec giai ma phan cung ra texture, scene graph ve thang — xem
    // VideoSource.set_output. MOT VideoOutput (player chi co mot sink), doi cha theo
    // camBig. Mat/dung hinh thi PHU o xam len chu KHONG an no: an thi khong ai lay
    // khung, bo giai ma dung — va VideoOutput giu khung cuoi, dung cai video.py cam.
    Item {
        parent: win.camBig ? mainView : pipItem
        anchors.fill: parent
        visible: backend.phone
        VideoOutput {
            objectName: "videoOut"
            anchors.fill: parent
            fillMode: VideoOutput.PreserveAspectFit
        }
        Rectangle {
            anchors.fill: parent
            visible: !st.vidLive
            color: theme.BG
            Text {
                anchors { fill: parent; margins: 6 }
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                wrapMode: Text.WordWrap
                text: st.vidNote || ""
                color: st.vidWarn ? theme.WARN : theme.MUTED
                font.pixelSize: 13 * f
            }
        }
        Text {  // nhip khung NGAY tren hinh, nhu VideoView
            visible: !!st.vidLive
            x: 6; y: 4
            text: (st.vidFps || 0).toFixed(1) + " fps"
            color: st.vidFps < 8 ? theme.WARN : theme.OK
            font.pixelSize: 12 * f
        }
    }

    // ---- so lieu duoi cung ---------------------------------------------------
    Rectangle {
        id: tele
        anchors { bottom: parent.bottom; bottomMargin: 10 * s; horizontalCenter: parent.horizontalCenter }
        height: Math.max(54 * s, teleRow.implicitHeight + 8)
        width: teleRow.implicitWidth + 32 * s
        radius: 14 * s
        color: "#ee0d1722"
        border.color: theme.BORDER
        Row {
            id: teleRow
            anchors.centerIn: parent
            spacing: 22 * s
            Stat { label: "H"; value: num(st.alt, 1, " m") }
            Stat { label: "D"; value: num(st.dist, 0, " m") }
            Stat { label: "H.S"; value: num(st.hs, 1, " m/s") }
            Stat { label: "V.S"; value: num(st.vs, 1, " m/s") }
            Stat { label: "HDG"; value: num(st.heading, 0, "°"); visible: !win.compact }
            Stat { label: "T"; value: st.flightTime ? mmss(st.flightTime) : "--"; tint: st.armed ? theme.CRIT : theme.TEXT }
            Stat {
                label: tr("touch.left")
                value: st.battLeft === null || st.battLeft === undefined ? "--" : mmss(st.battLeft)
                tint: st.battLeft === null || st.battLeft === undefined ? theme.TEXT : lvl(st.leftLevel)
            }
        }
    }

    // ---- canh bao cua ban do (dien thoai): ngay tren thanh so lieu ---------
    Rectangle {
        objectName: "mapNote"
        visible: !!st.mapNote
        // Nam giua dong ho (man thap: goc duoi trai) va cum can ao/nut leo-ha ben phai.
        readonly property real minX: win.compact ? win.dialX + win.dialW + 8 * s : win.width * 0.2
        readonly property real maxX: climbCol.visible ? climbCol.x - 8 * s : win.width - 14 * s
        anchors { bottom: tele.top; bottomMargin: 4 * s }
        width: Math.min(noteText.implicitWidth + 16 * s, maxX - minX)
        x: Math.max(minX, Math.min(tele.x + (tele.width - width) / 2, maxX - width))
        height: noteText.implicitHeight + 6 * s
        radius: 6 * s
        color: "#b0000000"
        Text {
            id: noteText
            anchors { fill: parent; leftMargin: 8 * s; rightMargin: 8 * s }
            verticalAlignment: Text.AlignVCenter
            text: st.mapNote || ""
            elide: Text.ElideRight
            color: theme.TEXT
            font.pixelSize: 11 * f
        }
    }

    // ---- can ao: nhich vi tri ------------------------------------------------
    //
    // Thay cho bon phim mui ten cua tab Bay cu. Do lech ngon tay CHINH LA do lon,
    // nen khong ramp theo thoi gian giu: cham nhe la di cham, day het moi toi tran.
    // Nhac tay -> backend gui van toc 0, khong doi lenh GUIDED het han 3 s.
    Item {
        id: stick
        visible: st.live
        opacity: st.nudgeWhy === "" ? 1 : 0.35
        anchors { right: parent.right; rightMargin: 14 * s
                  bottom: parent.bottom; bottomMargin: 10 * s }
        width: Math.max(win.compact ? 100 : 120, 136 * s)
        height: width
        Rectangle {
            anchors.fill: parent
            radius: width / 2
            color: "#b00d1722"
            border.color: st.nudgeWhy === "" ? theme.ACCENT : theme.BORDER
            border.width: 2
        }
        Rectangle {
            width: 46 * s          // duoi ~46 px la ngon tay bam truot
            height: width
            radius: width / 2
            x: stick.width / 2 - width / 2 + win.stickX * (stick.width - width) / 2
            y: stick.height / 2 - height / 2 - win.stickY * (stick.height - height) / 2
            color: theme.ACCENT
            opacity: 0.9
        }
        MouseArea {
            anchors.fill: parent
            enabled: st.nudgeWhy === ""
            function grab(mx, my) {
                var r = stick.width / 2
                var ux = (mx - r) / r
                var uy = (r - my) / r        // man hinh: len tren la bac
                var m = Math.sqrt(ux * ux + uy * uy)
                if (m > 1) { ux /= m; uy /= m }   // ngoai vanh khong duoc nhanh hon
                win.stickX = ux
                win.stickY = uy
                win.pushStick()
            }
            onPressed: (m) => grab(m.x, m.y)
            onPositionChanged: (m) => grab(m.x, m.y)
            // `canceled` cung phai buong: ngon tay truot ra ngoai cua so giua chung
            // thi khong co `released`, va drone giu nguyen van toc cuoi.
            onReleased: { win.stickX = 0; win.stickY = 0; win.pushStick() }
            onCanceled: { win.stickX = 0; win.stickY = 0; win.pushStick() }
        }
    }
    Column {   // leo / ha, ngay canh can ao
        id: climbCol
        visible: stick.visible
        opacity: stick.opacity
        anchors { right: stick.left; rightMargin: 8 * s; verticalCenter: stick.verticalCenter }
        spacing: 8 * s
        HoldBtn { glyph: "↑"; value: 1 }
        HoldBtn { glyph: "↓"; value: -1 }
    }
    Text {
        visible: stick.visible && st.nudgeWhy !== ""
        anchors { right: stick.right; bottom: stick.top; bottomMargin: 2 * s }
        text: st.nudgeWhy
        color: theme.WARN
        font.pixelSize: 12 * f
    }

    // ---- bang duong bay: mo bang cham-giu tren ban do ------------------------
    Rectangle {
        id: wpSheet
        visible: win.wpOpen
        anchors { horizontalCenter: parent.horizontalCenter; bottom: tele.top; bottomMargin: 12 * s }
        width: Math.min(Math.max(560 * s, 360), win.width - 2 * (leftCol.width + 44 * s))
        // Man thap: 4 hang chip + nut cao hon cho trong -> cat chieu cao, cuon ben trong.
        height: Math.min(wpCol.implicitHeight + 24 * s, tele.y - topBar.height - 16 * s)
        radius: 16 * s
        color: "#f00d1722"
        border.color: theme.BORDER
        border.width: 2
        MouseArea { anchors.fill: parent }  // cham vao bang khong roi xuong ban do
        Flickable {
            id: wpFlick
            anchors { fill: parent; margins: 12 * s }
            contentWidth: width  // khong de contentItem suy rong tu con: vong lap voi wpCol
            contentHeight: wpCol.implicitHeight
            flickableDirection: Flickable.VerticalFlick
            boundsBehavior: Flickable.StopAtBounds
            clip: true
        Column {
            id: wpCol
            width: wpFlick.width
            spacing: 10 * s
            Item {
                width: parent.width
                height: Math.max(30 * s, 22)
                Text {
                    anchors { left: parent.left; right: wpClose.left; verticalCenter: parent.verticalCenter }
                    text: tr("touch.wp_title") + (st.draftN ? "  ·  " + st.draftN : "")
                    color: theme.TEXT
                    font.pixelSize: 16 * f
                    font.bold: true
                    elide: Text.ElideRight
                }
                Text {
                    id: wpClose
                    anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                    text: "✕"
                    color: theme.MUTED
                    font.pixelSize: 22 * f
                    MouseArea { anchors.fill: parent; anchors.margins: -10; onClicked: win.wpOpen = false }
                }
            }
            Text {
                visible: st.draftN === 0
                width: parent.width
                text: tr("touch.wp_hint")
                wrapMode: Text.Wrap
                color: theme.MUTED
                font.pixelSize: 13 * f
            }
            Flow {
                width: parent.width
                spacing: 8 * s
                Chip {
                    text: tr("touch.wp_add", {"n": st.draftN + 1})
                    enabled: !st.draftFull
                    opacity: enabled ? 1 : 0.4
                    onTap: backend.addWp(win.wpX, win.wpY)
                }
                Chip {
                    objectName: "wpGoto"
                    // Task dang lai thi node de len lenh nay ngay (commands.task_block).
                    text: st.task ? tr("touch.wp_goto_task") : tr("touch.wp_goto", {"alt": st.wpAlt})
                    enabled: st.live && !st.task
                    opacity: enabled ? 1 : 0.4
                    onTap: { win.gotoAt = backend.pickGoto(win.wpX, win.wpY); ask("goto") }
                }
                // Chi co khi task Chua chay dang chay: diem chay la DU LIEU cua task,
                // khong phai mot lenh bay thuong tren ban do.
                Chip {
                    objectName: "wpFire"
                    visible: st.taskFire === true
                    text: tr("touch.wp_fire")
                    enabled: st.live
                    opacity: enabled ? 1 : 0.4
                    onTap: { win.gotoAt = backend.pickGoto(win.wpX, win.wpY); openFire() }
                }
            }
            Flow {
                width: parent.width
                spacing: 8 * s
                Text {
                    text: tr("touch.wp_alt")
                    color: theme.MUTED
                    font.pixelSize: 13 * f
                }
                Repeater {
                    model: backend.wpAlts
                    delegate: Chip {
                        text: modelData + " m"
                        selected: st.wpAlt === modelData
                        onTap: backend.setWpAlt(modelData)
                    }
                }
                // O nhap: sau chip khong phu duoc moi bai (tran rao, dia hinh
                // doc). Nut +/- de tren man cam ung khong phai goi ban phim ao
                // len che mat man hinh bay; go so chi la duong nhanh khi co ban
                // phim. Kep hai dau ngay o day, va backend kep lai lan nua.
                SpinBox {
                    id: altBox
                    objectName: "wpAltBox"
                    editable: true
                    from: backend.wpAltMin
                    to: backend.wpAltMax
                    stepSize: 1
                    height: Math.max(38 * s, 34)
                    font.pixelSize: 14 * f
                    textFromValue: function (v) { return v + " m" }
                    valueFromText: function (txt) { return parseInt(txt) || altBox.value }
                    // Chip va o nhap la HAI cua vao mot con so: bam chip thi o
                    // nhap phai doi theo. `Binding` chu khong gan tay — nguoi
                    // dung go mot lan la binding khai bao bi dut.
                    Binding on value { value: st.wpAlt }
                    onValueModified: backend.setWpAlt(value)
                }
            }
            Flow {
                width: parent.width
                spacing: 8 * s
                Btn { text: tr("touch.wp_undo"); enabled: st.draftN > 0; onTap: backend.undoWp() }
                Btn { text: tr("touch.wp_clear"); enabled: st.draftN > 0; onTap: backend.clearWp() }
                Btn {
                    objectName: "wpSend"
                    text: st.wpOver ? tr("touch.wp_send_over", {"n": st.draftN})
                                    : tr("touch.wp_send", {"n": st.draftN})
                    enabled: st.draftN > 0 && st.live
                    onTap: backend.sendWp()
                }
                Btn {
                    text: tr("touch.wp_wipe")
                    enabled: st.hasWp && st.live
                    onTap: backend.wipeWp()
                }
            }
        }
        }
    }

    // ---- bang xac nhan: chon tham so + thanh truot ---------------------------
    Rectangle {
        id: confirm
        visible: win.pending !== ""
        anchors { horizontalCenter: parent.horizontalCenter; bottom: tele.top; bottomMargin: 12 * s }
        width: Math.min(Math.max(540 * s, 360), win.width - 2 * (leftCol.width + 44 * s))
        height: col.implicitHeight + 24 * s
        radius: 16 * s
        color: "#f00d1722"
        border.color: danger(win.pending) ? theme.CRIT : theme.BORDER
        border.width: 2
        MouseArea { anchors.fill: parent }  // cham vao bang khong roi xuong ban do
        Column {
            id: col
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 12 * s }
            spacing: 10 * s
            Item {
                width: parent.width
                height: Math.max(30 * s, 22)
                Text {
                    anchors { left: parent.left; right: closeBtn.left; verticalCenter: parent.verticalCenter }
                    text: titleText()
                    color: theme.TEXT
                    font.pixelSize: 16 * f
                    font.bold: true
                    elide: Text.ElideRight
                }
                Text {
                    id: closeBtn
                    anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                    text: "✕"
                    color: theme.MUTED
                    font.pixelSize: 22 * f
                    MouseArea { anchors.fill: parent; anchors.margins: -10; onClicked: win.pending = "" }
                }
            }
            // Cung mot hang chon do cao cho cat canh tay va task Chua chay, moi cai
            // nho so rieng cua minh.
            Flow {
                id: altRow
                visible: win.pending === "takeoff" || win.pending === "fire"
                readonly property bool fire: win.pending === "fire"
                readonly property real alt: fire ? win.fireAlt : win.takeoffAlt
                function pick(v) {
                    if (fire) win.fireAlt = v; else win.takeoffAlt = v
                    askTimer.restart()
                }
                width: parent.width
                spacing: 8 * s
                Text {
                    visible: altRow.fire
                    height: takeoffBox.height
                    verticalAlignment: Text.AlignVCenter
                    text: tr("touch.fire_alt")
                    color: theme.MUTED
                    font.pixelSize: 13 * f
                }
                Repeater {
                    model: altRow.fire ? backend.fireChips(st.fireLim.min, st.fireLim.max)
                                       : [3, 5, 10, 20, 30]
                    delegate: Chip {
                        text: modelData + " m"
                        selected: altRow.alt === modelData
                        onTap: altRow.pick(modelData)
                    }
                }
                // Go so tuy y, giong o do cao waypoint. Kep hai dau o day, va
                // backend.act kep lai lan nua — con so nay di thang xuong FC.
                SpinBox {
                    id: takeoffBox
                    objectName: "takeoffAltBox"
                    editable: true
                    from: altRow.fire ? st.fireLim.min : backend.wpAltMin
                    to: altRow.fire ? st.fireLim.max : backend.wpAltMax
                    stepSize: 1
                    height: Math.max(38 * s, 34)
                    font.pixelSize: 14 * f
                    textFromValue: function (v) { return v + " m" }
                    valueFromText: function (txt) { return parseInt(txt) || takeoffBox.value }
                    Binding on value { value: altRow.alt }
                    onValueModified: altRow.pick(value)
                }
            }
            // Ha cach lua bao nhieu m roi tha: tu min_alt cua node toi do cao bay.
            Flow {
                id: dropRow
                visible: win.pending === "fire"
                function pick(v) { win.fireDrop = v; askTimer.restart() }
                width: parent.width
                spacing: 8 * s
                Text {
                    height: dropBox.height
                    verticalAlignment: Text.AlignVCenter
                    text: tr("touch.fire_drop")
                    color: theme.MUTED
                    font.pixelSize: 13 * f
                }
                Repeater {
                    model: dropRow.visible ? backend.fireChips(st.fireLim.min, win.fireAlt) : []
                    delegate: Chip {
                        text: modelData + " m"
                        selected: win.fireDrop === modelData
                        onTap: dropRow.pick(modelData)
                    }
                }
                SpinBox {
                    id: dropBox
                    objectName: "fireDropBox"
                    editable: true
                    from: st.fireLim.min
                    to: win.fireAlt
                    stepSize: 1
                    height: Math.max(38 * s, 34)
                    font.pixelSize: 14 * f
                    textFromValue: function (v) { return v + " m" }
                    valueFromText: function (txt) { return parseInt(txt) || dropBox.value }
                    Binding on value { value: win.fireDrop }
                    onValueModified: dropRow.pick(value)
                }
            }
            Flow {
                visible: win.pending === "modePick"
                width: parent.width
                spacing: 8 * s
                Repeater {
                    model: backend.modes
                    delegate: Chip {
                        text: modelData
                        selected: modelData === st.fcMode
                        onTap: ask("mode", modelData)
                    }
                }
            }
            Text {
                visible: win.pending === "kill"
                width: parent.width
                text: tr("touch.kill_note")
                wrapMode: Text.Wrap
                color: theme.CRIT
                font.pixelSize: 15 * f
                font.bold: true
            }
            SlideConfirm {
                id: slider
                objectName: "slider"
                visible: win.pending !== "" && win.pending !== "modePick"
                width: parent.width
                height: Math.max(60 * s, 44)
                text: slideText()
                tint: danger(win.pending) ? theme.CRIT : theme.ACCENT
                onConfirmed: {
                    var a = win.pending
                    var arg = a === "takeoff" ? String(win.takeoffAlt) : win.pendingArg
                    win.pending = ""
                    if (a === "goto")
                        backend.gotoAt(win.gotoAt[0], win.gotoAt[1])
                    else if (a === "fire")
                        backend.fireAt(win.gotoAt[0], win.gotoAt[1], win.fireAlt, win.fireDrop)
                    else if (a === "taskStart")
                        backend.task("fire_mission")
                    else if (a === "taskStop")
                        backend.task("")
                    else
                        backend.act(a, arg)
                }
            }
        }
    }

    // ---- khoi dung chung -----------------------------------------------------
    component Ind: Row {
        property string label
        property string value: ""
        property string lv: "none"
        spacing: 5 * s
        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: 9 * f; height: width; radius: width / 2
            color: lvl(lv)
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: label; color: theme.MUTED
            font.pixelSize: 12 * f; font.bold: true
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            visible: value !== ""
            text: value; color: theme.TEXT
            font.pixelSize: 15 * f; font.bold: true
        }
    }

    component Stat: Column {
        property string label
        property string value
        property color tint: theme.TEXT
        Text { text: label; color: theme.MUTED; font.pixelSize: 11 * f }
        Text { text: value; color: tint; font.pixelSize: 17 * f; font.bold: true }
    }

    component ActBtn: Item {
        id: ab
        property string glyph
        property string label
        property bool danger: false
        signal tap()
        width: Math.max(66 * s, circle.width + 6, lbl.width + 4)  // nhan dai khong tran sang nut ke
        height: circle.height + lbl.height + 2 * s
        opacity: st.live ? 1 : 0.35
        Rectangle {
            id: circle
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.max(46, 54 * s)  // duoi ~46 px la ngon tay bam truot
            height: width
            radius: width / 2
            color: "#cc0d1722"
            border.color: ab.danger ? theme.CRIT : theme.ACCENT
            border.width: 2
            Text {
                anchors.centerIn: parent
                text: ab.glyph
                color: ab.danger ? theme.CRIT : theme.TEXT
                font.pixelSize: 22 * f
                font.bold: true
            }
        }
        Rectangle {
            id: lbl
            anchors { top: circle.bottom; topMargin: 3 * s; horizontalCenter: parent.horizontalCenter }
            width: lblText.implicitWidth + 10 * s
            height: lblText.implicitHeight + 2 * s
            radius: height / 2
            color: "#cc08111a"
            Text {
                id: lblText
                anchors.centerIn: parent
                text: ab.label
                color: theme.TEXT
                font.pixelSize: 11 * f
                font.bold: true
            }
        }
        MouseArea { anchors.fill: circle; enabled: st.live; onClicked: ab.tap() }
    }

    // Leo/ha: giu la di, buong la thoi — giong PageUp/PageDown cua tab Bay cu,
    // KHONG phai bam mot cai roi drone tu leo mai.
    component HoldBtn: Rectangle {
        property string glyph
        property real value: 0
        width: Math.max(40, 46 * s)
        height: width
        radius: width / 2
        color: hb.pressed ? theme.ACCENT : "#cc0d1722"
        border.color: theme.ACCENT
        border.width: 2
        Text {
            anchors.centerIn: parent
            text: glyph
            color: hb.pressed ? theme.BG_DEEP : theme.TEXT
            font.pixelSize: 20 * f
            font.bold: true
        }
        MouseArea {
            id: hb
            anchors.fill: parent
            enabled: st.nudgeWhy === ""
            onPressed: { win.climb = value; win.pushStick() }
            onReleased: { win.climb = 0; win.pushStick() }
            onCanceled: { win.climb = 0; win.pushStick() }
        }
    }

    component Chip: Rectangle {
        id: chip
        property string text
        property bool selected: false
        signal tap()
        width: ct.implicitWidth + 24 * s
        height: Math.max(36 * s, 32)
        radius: height / 2
        color: selected ? theme.ACCENT : theme.SURFACE
        border.color: selected ? theme.ACCENT : theme.BORDER
        Text {
            id: ct
            anchors.centerIn: parent
            text: chip.text
            color: chip.selected ? theme.BG_DEEP : theme.TEXT
            font.pixelSize: 14 * f
            font.bold: true
        }
        MouseArea { anchors.fill: parent; onClicked: chip.tap() }
    }

    component Btn: Rectangle {
        id: btn
        property string text
        signal tap()
        width: bt.implicitWidth + 28 * s
        height: Math.max(44 * s, 40)
        radius: 10 * s
        color: enabled ? theme.SURFACE : "#0b1117"
        border.color: enabled ? theme.ACCENT : theme.BORDER
        opacity: enabled ? 1 : 0.5
        Text { id: bt; anchors.centerIn: parent; text: btn.text; color: theme.TEXT; font.pixelSize: 15 * f }
        MouseArea { anchors.fill: parent; enabled: btn.enabled; onClicked: btn.tap() }
    }
}
