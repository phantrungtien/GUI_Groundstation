package org.trungtien.gcs;

import android.app.Activity;
import android.app.Application;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.Bundle;
import android.os.IBinder;
import android.os.Process;
import android.util.Log;

/**
 * Foreground service: giu GCS song khi nguoi bay chuyen sang app khac.
 *
 * Khong co no, app o nen la tien trinh "cached" — Android cho toi da 2 % CPU moi 5
 * phut roi giet. Do 23/10 tren Lenovo: 22:13:08 "Killing ... excessive cpu 23440
 * during 300067 ... limit=2", sau 18,6 phut o nen. Do 24/10 tren laptop, cua so an:
 * rieng thread doc MAVLink da 1,6-2,5 % mot loi x86 — tren ARM con cao hon, giam CPU
 * khong xuong duoi 2 % duoc. Co foreground service thi tien trinh khong con "cached",
 * luat do khong ap: tlog van ghi, canh bao giong noi van doc khi o nen.
 *
 * Loai connectedDevice (radio SiK qua USB, FC qua mang); Android 14+ doi them quyen
 * FOREGROUND_SERVICE_CONNECTED_DEVICE va mot quyen dieu kien (CHANGE_NETWORK_STATE)
 * — khai trong tools/build_apk.sh.
 */
public class GcsService extends Service {
    static final String TAG = "GcsService";
    static final String CHANNEL = "gcs";

    /** Goi tu SikBridge.Init. Service chi duoc mo khi activity da len (Android 12+ cam
     *  mo foreground service tu nen), nen cho onActivityResumed dau tien. */
    static void install(Context c) {
        Context app = c.getApplicationContext();
        if (app instanceof Application) {
            ((Application) app).registerActivityLifecycleCallbacks(new Starter());
        }
    }

    static class Starter implements Application.ActivityLifecycleCallbacks {
        private boolean started;

        @Override
        public void onActivityResumed(Activity a) {
            if (started) return;
            started = true;
            try {
                a.startForegroundService(new Intent(a, GcsService.class));
            } catch (Exception e) {  // khong mo duoc: app chay nhu truoc, chi mat che do nen
                Log.e(TAG, "khong mo duoc foreground service", e);
            }
        }

        @Override
        public void onActivityDestroyed(Activity a) {
            if (a.isFinishing()) a.stopService(new Intent(a, GcsService.class));
        }

        @Override public void onActivityCreated(Activity a, Bundle b) { }
        @Override public void onActivityStarted(Activity a) { }
        @Override public void onActivityPaused(Activity a) { }
        @Override public void onActivityStopped(Activity a) { }
        @Override public void onActivitySaveInstanceState(Activity a, Bundle b) { }
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int id) {
        NotificationManager nm = getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel(
                CHANNEL, "GCS đang chạy", NotificationManager.IMPORTANCE_LOW));
        Intent open = getPackageManager().getLaunchIntentForPackage(getPackageName());
        Notification n = new Notification.Builder(this, CHANNEL)
                .setContentTitle("GCS đang chạy")
                .setContentText("Telemetry, tlog và cảnh báo giọng nói vẫn chạy khi ở nền")
                .setSmallIcon(getApplicationInfo().icon)
                .setContentIntent(PendingIntent.getActivity(this, 0, open, PendingIntent.FLAG_IMMUTABLE))
                .setOngoing(true)
                .build();
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE);
        } else {
            startForeground(1, n);
        }
        return START_NOT_STICKY;
    }

    /** Vuot tat app trong danh sach gan day = tat han, nhu truoc khi co service. Khong
     *  thi service giu tien trinh song: Python van ghi tlog ma khong con giao dien. */
    @Override
    public void onTaskRemoved(Intent root) {
        stopSelf();
        Process.killProcess(Process.myPid());
    }

    @Override public IBinder onBind(Intent i) { return null; }
}
