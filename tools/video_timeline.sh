#!/usr/bin/env bash
# Nhip video HAI DAU tren mot truc thoi gian, roi tom tat ca phien:
#   pi   camera + nen (journal cua mjpeg-stream.service, 5 s/dong), crash, reset USB
#   gui  khung THUC SU toi GUI (logs/video.log do laptop/widgets/video.py ghi)
#
#   tools/video_timeline.sh              # tu luc GUI bat dau ghi log
#   tools/video_timeline.sh 13:00        # tu moc khac — cu phap `date -d`
#   tools/video_timeline.sh "-30 min"
#
# Hai may deu dong bo NTP (lech < 1 s) nen ghep theo gio la du. `pi nen` cao ma
# `gui fps` thap -> mat tren WiFi; ca hai cung tut -> camera/Pi.
# ponytail: ssh user co dinh `hoaibac`, IP lay tu connections.yaml nhu GUI.
cd "$(dirname "$0")/.." || exit 1
export LC_ALL=C
LOG=logs/video.log
HOST=$(grep -m1 -oP 'remote: "ws://\K[0-9.]+' config/connections.yaml)
SINCE=$(date -d "${1:-$(head -1 "$LOG" 2>/dev/null | cut -d' ' -f1)}" '+%F %T') || exit 1

TL=$({
  [ -f "$LOG" ] && awk -v s="${SINCE/ /T}" '$1 >= s' "$LOG"
  ssh -o BatchMode=yes -o ConnectTimeout=5 "${PI_USER:-hoaibac}@$HOST" \
    "journalctl _SYSTEMD_UNIT=mjpeg-stream.service + UNIT=mjpeg-stream.service \
       + _TRANSPORT=kernel --since '$SINCE' -o short-iso --no-pager" |
    grep -E '\[mjpeg\]|Error|exited|usb [0-9-]+: (reset|USB disconnect)|uvcvideo' |
    sed -E 's/^([0-9T:-]{19})[+-][0-9:]+ [^ ]+ [^:]+: /\1 pi  /'
} | sort -s -k1,1)

echo "$TL"
echo "$TL" | awk '
  $2 == "pi" && /nguon/ { pn++; src += $5; enc += $9 }
  $2 == "pi" && /exited/ { crash++ }
  $2 == "pi" && /usb/    { usb++ }
  $2 == "gui" && $3 == "fps" { gn++; g += $4; if (gmin == "" || $4 < gmin) gmin = $4 }
  $2 == "gui" && ($3 == "lost" || $3 == "error") { lost++ }
  END {
    print "---"
    if (pn) printf "pi   camera %.1f Hz, nen %.1f fps (tb %d mau)   dung/restart %d   reset USB %d\n", src/pn, enc/pn, pn, crash, usb
    if (gn) printf "gui  toi GUI %.1f fps tb, thap nhat %.1f (%d mau)   mat/loi %d lan\n", g/gn, gmin, gn, lost
    else    print  "gui  chua co log — GUI chua mo, hoac chua bam ket noi video"
  }'
