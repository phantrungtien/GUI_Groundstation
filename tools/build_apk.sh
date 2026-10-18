#!/bin/bash
# Dong goi app thanh APK Android (arm64) bang pyside6-android-deploy.
#
#   tools/build_apk.sh stage   # chi dung thu muc build + thu chay tren may tinh
#   tools/build_apk.sh         # stage + build APK
#
# Build trong thu muc RIENG ngoai repo ($STAGE): buildozer gom moi .png/.py duoi
# thu muc chay vao APK — o repo la 344 MB tile + 121 MB giong Piper + tlog. O day
# chi co code chay that, va ban THUAN PYTHON cua pymavlink/yaml/websockets/serial
# (bo .so cua laptop x86_64; ca bon deu tu roi ve ban Python khi thieu .so).
# Cong cu build (NDK r27c, SDK, JDK 17, wheel Qt 6.11.1 aarch64) o ~/.pyside6_android_deploy.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
C=~/.pyside6_android_deploy
# KHONG dat duoi thu muc an (~/.pyside6_android_deploy): buildozer bo qua moi file co
# mot thanh phan duong dan bat dau bang "." -> APK khong co main.py (do 18/10).
STAGE=~/android_build/gcs_app
SP=$(python3 -c "import pymavlink, os; print(os.path.dirname(os.path.dirname(pymavlink.__file__)))")

# Giu .buildozer (Python da dich cho Android, gradle) va bin (APK) giua cac lan:
# xoa la lan nao cung dich lai Python tu dau.
mkdir -p "$STAGE"
find "$STAGE" -mindepth 1 -maxdepth 1 ! -name .buildozer ! -name bin -exec rm -rf {} +
rsync -a --exclude __pycache__ --exclude '*.pyc' \
    "$ROOT/main.py" "$ROOT/laptop" "$ROOT/core" "$ROOT/config" "$STAGE/"
for p in yaml websockets serial; do
    rsync -a --exclude __pycache__ --exclude '*.so' "$SP/$p" "$STAGE/"
done
# pymavlink: 64 MB la dialect; app chi dung ardupilotmega (mavutil mac dinh).
rsync -a --exclude __pycache__ --exclude '*.so' --exclude dialects \
    "$SP/pymavlink" "$STAGE/"
for v in v10 v20; do
    mkdir -p "$STAGE/pymavlink/dialects/$v"
    cp "$SP/pymavlink/dialects/$v/__init__.py" "$SP/pymavlink/dialects/$v/ardupilotmega.py" \
        "$STAGE/pymavlink/dialects/$v/"
done
cp "$SP/pymavlink/dialects/__init__.py" "$STAGE/pymavlink/dialects/"
mkdir -p "$STAGE/logs"
echo "stage: $STAGE $(du -sh "$STAGE" | cut -f1)"

# Thu chay ban da dung bang Python CO LAP (-I -S: bo ~/.local va dist-packages he thong, nhu gi/GStreamer ma Android khong co) — thieu gi la lo o day,
# khong phai sau 30 phut build. PySide6 thi muon tu ~/.local qua PYTHONPATH rieng.
PYSIDE=$(python3 -c "import PySide6, os; print(os.path.dirname(os.path.dirname(PySide6.__file__)))")
mkdir -p "$C/pyside_only"
for p in PySide6 shiboken6; do ln -sfn "$PYSIDE/$p" "$C/pyside_only/$p"; done
(cd "$STAGE" && QT_QPA_PLATFORM=offscreen timeout 8 \
    env PYTHONPATH="$STAGE:$C/pyside_only" python3 -I -S -c "
import sys; sys.path[:0] = ['$STAGE', '$C/pyside_only']
import runpy; runpy.run_path('main.py', run_name='__main__')" ) && rc=0 || rc=$?
[ $rc -eq 124 ] && echo "stage: app chay duoc 8 s tu thu muc build" || { echo "stage: app chet, exit $rc"; exit 1; }
# Luc chay thu, ban do tu tai tile vao $STAGE/assets — khong duoc lot vao APK.
rm -rf "$STAGE/assets" "$STAGE/logs"
[ "${1:-}" = stage ] && exit 0

cd "$STAGE"
export JAVA_HOME=$C/jdk-17 PATH=$C/jdk-17/bin:$PATH
# Buoc 1: cong cu cua Qt chi sinh cau hinh (--init). Chay that thi no XOA
# buildozer.spec truoc (deploy_util.cleanup), nen moi chinh sua o buoc 2 se mat.
pyside6-android-deploy --init --name GCS -f --keep-deployment-files \
    --wheel-pyside "$C/wheels/pyside6-6.11.1-6.11.1-cp311-cp311-android_aarch64.whl" \
    --wheel-shiboken "$C/wheels/shiboken6-6.11.1-6.11.1-cp311-cp311-android_aarch64.whl" \
    --ndk-path "$C/android-ndk/android-ndk-r27c" --sdk-path "$C/android-sdk"
# Buoc 2: va cau hinh. include_exts mac dinh khong co json/yaml -> thieu
# config/connections.yaml va core/param_meta*.json la app chet luc mo.
# qjpeg: khung MJPEG cua camera va tile Google la JPEG, PNG thi Qt co san.
mkdir -p "$C/androidlibs"
unzip -j -o -q "$C/wheels/pyside6-6.11.1-6.11.1-cp311-cp311-android_aarch64.whl" \
    PySide6/Qt/plugins/imageformats/libplugins_imageformats_qjpeg_arm64-v8a.so -d "$C/androidlibs"
ROOT="$ROOT" C="$C" python3 - <<'PY'
import configparser, os, re, shlex
p = "buildozer.spec"; c = configparser.ConfigParser(interpolation=None); c.optionxform = str
c.read(p); a = c["app"]
# Wheel Qt la cp311; p4a nhanh develop mac dinh Python 3.14 -> phai ghim, khong
# thi APK build xong nhung PySide6 khong nap duoc (do 18/10: hostpython 3.14.2).
a["requirements"] = "python3==3.11.13,hostpython3==3.11.13,shiboken6,PySide6"
a.update({"package.name": "gcs", "package.domain": "org.trungtien",
          "source.include_exts": a["source.include_exts"] + ",json,yaml,ttf",  # ttf: laptop/fonts (ky hieu)
          "source.exclude_dirs": "deployment,bin,.buildozer",
          "orientation": "landscape", "fullscreen": "1",
          "android.api": "35", "android.minapi": "28", "android.ndk_api": "28",
          "android.accept_sdk_license": "True"})
a["p4a.extra_args"] = re.sub(r"(--load-local-libs=\S+)", r"\1,plugins_imageformats_qjpeg", a["p4a.extra_args"])
# ...nhung recipe PySide6 do Qt sinh chi chep vao lib/ cac plugin trong danh sach cua
# no (khong co imageformats) -> QtLoader "Can't find libplugins_imageformats_qjpeg",
# app chet ngay luc mo (do 18/10). Tu chep .so tu wheel (shell, ngay tren day).
a["android.add_libs_arm64_v8a"] = os.environ["C"] + "/androidlibs/*.so"
# Thu tu --qt-libs = thu tu QtLoader nap, ma cong cu Qt sinh tu mot set (lan 18/10:
# QuickWidgets dau, Core thu 10) -> JNI_OnLoad cua libQt6Quick chay khi QtCore chua
# giu JavaVM: SIGSEGV QJniEnvironment::getJniEnv, app chet sau 0,5 s. Xep theo phu thuoc.
ORDER = ("Core Concurrent Network Gui OpenGL Widgets OpenGLWidgets Qml Quick "
         "QuickControls2 QuickWidgets Multimedia TextToSpeech Charts").split()
a["p4a.extra_args"] = re.sub(
    r"--qt-libs=(\S+)",
    lambda m: "--qt-libs=" + ",".join(sorted(
        m.group(1).split(","), key=lambda x: ORDER.index(x) if x in ORDER else len(ORDER))),
    a["p4a.extra_args"])
# Radio SiK cam OTG: lop Java mo USB, dua ra tcp:127.0.0.1:5760 (xem SikBridge.java).
# Khoi dong no bang mot ContentProvider (Android tao luc mo tien trinh) — --init-classes
# thi Qt 6.11 bo qua. buildozer khong co khoa cho XML trong <application>, nen di
# thang qua p4a; buildozer tach extra_args bang shlex -> phai quote.
provider = ('<provider android:name="org.trungtien.gcs.SikBridge$Init" '
            'android:authorities="org.trungtien.gcs.sikbridge" android:exported="false"/>')
a["p4a.extra_args"] += " --extra-manifest-application-xml=" + shlex.quote(provider)
a.update({"android.add_src": os.environ["ROOT"] + "/android/java",
          "android.gradle_dependencies": "com.github.mik3y:usb-serial-for-android:3.8.1",
          "android.add_gradle_repositories": "maven { url 'https://jitpack.io' }",
          "android.wakelock": "True"})  # dang bay ma man hinh tat la mat nut do
# Ban do offline dong chung APK (nguoi dung chot 19/10) dang ASSET, khong vao
# private.tar: p4a giai nen private.tar tren luong chinh -> +345 MB la ANR (do 19/10).
# main.py chep assets:/tiles ra bo nho trong o thread nen. aapt khong nen .png.
a["android.add_assets"] = os.environ["ROOT"] + "/assets/tiles:tiles"
# Cam radio telemetry la app tu nhan (va tu duoc cap quyen sau lan "Luon" dau tien).
# singleTask: app dang chay ma cam radio thi Android goi lai CHINH activity nay —
# mac dinh "standard" la tao activity thu hai = khoi dong Python/Qt lan nua.
a.update({"android.manifest.intent_filters": os.environ["ROOT"] + "/android/usb_intent.xml",
          "android.res_xml": os.environ["ROOT"] + "/android/device_filter.xml",
          "android.manifest.launch_mode": "singleTask"})
c["buildozer"]["log_level"] = "2"
c["buildozer"]["bin_dir"] = "./bin"  # --init dat ngay $STAGE, lan stage sau xoa mat APK
c.write(open(p, "w"))
PY
# Gradle: services.gradle.org chuyen sang GitHub releases, do 18/10 chi ~60 KB/s
# (220 MB ~ 1 gio); downloads.gradle.org cung file 2,7 MB/s. Dat san zip vao dung
# cho wrapper tim thi no khong tai nua.
# ponytail: thu muc bam theo URL + ban 8.14.3 cua p4a hien tai; p4a doi ban gradle
# thi wrapper tu tai lai (cham) — doc duong .part trong log roi sua hai dong nay.
G=~/.gradle/wrapper/dists/gradle-8.14.3-all/10utluxaxniiv4wxiphsi49nj
if [ ! -s "$G/gradle-8.14.3-all.zip" ]; then
    mkdir -p "$G" && rm -f "$G"/*.part
    curl -4 -sSfL --retry 3 -o "$G/gradle.tmp" https://downloads.gradle.org/distributions/gradle-8.14.3-all.zip
    mv "$G/gradle.tmp" "$G/gradle-8.14.3-all.zip"
fi
# Buoc 3: build (lan dau dich Python + tai gradle: lau).
python3 -m buildozer android debug
ls -la "$STAGE"/bin/*.apk
