package org.trungtien.gcs;

import android.app.PendingIntent;
import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.database.Cursor;
import android.hardware.usb.UsbDeviceConnection;
import android.hardware.usb.UsbManager;
import android.net.Uri;
import android.os.Build;
import android.util.Log;

import com.hoho.android.usbserial.driver.UsbSerialDriver;
import com.hoho.android.usbserial.driver.UsbSerialPort;
import com.hoho.android.usbserial.driver.UsbSerialProber;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.util.Arrays;
import java.util.List;

/**
 * Radio SiK cam OTG vao dien thoai -> tcp:127.0.0.1:5760 cho phia Python (pymavlink).
 *
 * Python tren Android khong mo duoc USB: pyserial can /dev/tty*, app thuong khong co
 * quyen; pyjnius thi khong chay voi bootstrap "qt" cua python-for-android (start.c
 * khong co WebView_AndroidGetJNIEnv). Nen USB nam o Java (usb-serial-for-android:
 * FTDI FT231X cua radio SiK, CP210x, CH34x, CDC), Python chi thay mot cong TCP.
 *
 * Khoi dong: Android tao SikBridge.Init (ContentProvider khai trong manifest boi
 * tools/build_apk.sh) luc mo tien trinh, Init goi setContext(). KHONG dung
 * static_init_classes / --init-classes: Qt 6.11 khong con doc no (18/10: khong lop
 * nao trong Qt6Android.jar nhac toi, cong 5760 khong bao gio mo).
 */
public class SikBridge {
    static final String TAG = "SikBridge";
    public static final int PORT = 5760;
    // ponytail: baud co dinh = mac dinh SiK. Radio dat baud khac thi sua o day.
    public static final int BAUD = 57600;
    static final String ACTION_PERM = "org.trungtien.gcs.USB_PERMISSION";
    private static Context ctx;

    /** Moc khoi dong, khong phai provider that: Android tao no truoc moi Activity. */
    public static class Init extends ContentProvider {
        @Override public boolean onCreate() {
            setContext(getContext());
            Immersive.install(getContext());  // cung moc khoi dong, xem Immersive.java
            GcsService.install(getContext());  // giu song khi o nen, xem GcsService.java
            return true;
        }
        @Override public Cursor query(Uri u, String[] p, String s, String[] a, String o) { return null; }
        @Override public String getType(Uri u) { return null; }
        @Override public Uri insert(Uri u, ContentValues v) { return null; }
        @Override public int delete(Uri u, String s, String[] a) { return 0; }
        @Override public int update(Uri u, ContentValues v, String s, String[] a) { return 0; }
    }

    public static void setContext(Context c) {
        if (ctx != null) return;
        ctx = c.getApplicationContext() != null ? c.getApplicationContext() : c;
        Thread t = new Thread(SikBridge::serve, TAG);
        t.setDaemon(true);
        t.start();
    }

    private static void serve() {
        try (ServerSocket ss = new ServerSocket(PORT, 1, InetAddress.getByName("127.0.0.1"))) {
            while (true) {
                try (Socket s = ss.accept()) {
                    s.setTcpNoDelay(true);
                    pump(s);
                } catch (Exception e) {
                    Log.w(TAG, "phien ket thuc: " + e);
                }
            }
        } catch (Exception e) {
            Log.e(TAG, "khong mo duoc cong " + PORT, e);
        }
    }

    private static volatile UsbSerialPort port;  // null = chua co radio
    private static boolean asked;  // da hien hop thoai xin quyen cho lan cam nay chua

    /**
     * Mot phien: tu luc Python noi vao toi luc Python dong socket.
     *
     * Chua cam radio, chua co quyen USB, hay rut radio giua chung: GIU socket, chi im.
     * Dong socket thi pymavlink (autoreconnect) noi lai ngay roi EOF ngay — quay tit
     * CPU. Im lang thi app hieu dung nghia "radio khong noi", va profile hai duong
     * (DualLink trong core/adapters/sik.py) chuyen sang duong mang.
     */
    private static void pump(Socket s) throws Exception {
        InputStream in = s.getInputStream();
        OutputStream out = s.getOutputStream();
        Thread up = new Thread(() -> {  // Python -> radio; chua co radio thi bo goi
            byte[] b = new byte[1024];
            try {
                int n;
                while ((n = in.read(b)) > 0) {
                    UsbSerialPort p = port;
                    if (p == null) continue;
                    try {
                        p.write(Arrays.copyOf(b, n), 1000);
                    } catch (IOException e) {
                        Log.w(TAG, "ghi radio loi: " + e);
                    }
                }
            } catch (Exception e) {
                Log.w(TAG, "chieu len dung: " + e);
            }
            try { s.close(); } catch (Exception ignored) { }
        }, TAG + "-up");
        up.setDaemon(true);
        up.start();
        byte[] b = new byte[4096];  // radio -> Python
        while (!s.isClosed()) {
            try {
                port = open();
            } catch (IOException e) {
                Log.w(TAG, "mo radio loi: " + e);
            }
            if (port == null) {
                Thread.sleep(1000);
                continue;
            }
            try {
                while (!s.isClosed()) {
                    int n;
                    try {
                        n = port.read(b, 200);
                    } catch (IOException e) {
                        Log.w(TAG, "radio mat: " + e);  // rut radio: cho cam lai
                        break;
                    }
                    if (n > 0) out.write(b, 0, n);  // loi o day = Python dong -> het phien
                }
            } finally {
                UsbSerialPort p = port;
                port = null;
                try { p.close(); } catch (IOException ignored) { }
            }
        }
    }

    /** Radio dau tien dang cam VA da duoc cap quyen, hoac null. */
    private static UsbSerialPort open() throws IOException {
        UsbManager um = (UsbManager) ctx.getSystemService(Context.USB_SERVICE);
        List<UsbSerialDriver> ds = UsbSerialProber.getDefaultProber().findAllDrivers(um);
        if (ds.isEmpty()) {
            asked = false;  // rut ra roi cam lai thi hoi lai
            return null;
        }
        UsbSerialDriver d = ds.get(0);
        if (!um.hasPermission(d.getDevice())) {
            if (!asked) {
                // Android hoi "Cho phep GCS truy cap thiet bi USB?" MOT lan moi lan cam;
                // bam Cho phep thi vong cho 1 s o pump() tu mo. API 31+ bat buoc MUTABLE
                // (he thong dien ket qua vao intent), API 34 bat buoc intent co dich danh.
                int flags = Build.VERSION.SDK_INT >= 31 ? PendingIntent.FLAG_MUTABLE : 0;
                Intent i = new Intent(ACTION_PERM).setPackage(ctx.getPackageName());
                um.requestPermission(d.getDevice(), PendingIntent.getBroadcast(ctx, 0, i, flags));
                asked = true;
                Log.w(TAG, "dang xin quyen USB");
            }
            return null;
        }
        UsbDeviceConnection conn = um.openDevice(d.getDevice());
        if (conn == null) return null;
        UsbSerialPort p = d.getPorts().get(0);
        p.open(conn);
        try {
            p.setParameters(BAUD, 8, UsbSerialPort.STOPBITS_1, UsbSerialPort.PARITY_NONE);
        } catch (IOException e) {
            p.close();
            throw e;
        }
        Log.i(TAG, "mo " + d.getClass().getSimpleName() + " @" + BAUD);
        return p;
    }
}
