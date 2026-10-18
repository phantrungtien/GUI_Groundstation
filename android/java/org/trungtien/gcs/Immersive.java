package org.trungtien.gcs;

import android.app.Activity;
import android.app.Application;
import android.content.Context;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowInsetsController;

/**
 * Toan man hinh "dinh" (immersive sticky): vuot tu mep thi thanh he thong hien TAM roi tu an.
 *
 * Qt showFullScreen() chi an thanh kieu "lean back": cham man hinh la thanh trang thai
 * hien lai va O LUON (do 19/10 tren OPPO, Android 11) — mat ~33 dp cua ~360 dp chieu
 * cao man bay, va moi lan bam nut lai mat tiep. Dat co immersive moi khi activity resume,
 * va dat lai sau 1,5 s moi khi thanh hien len (Qt cung tu dat co cua no luc doi trang
 * thai cua so — dat lai la thang no).
 */
public class Immersive implements Application.ActivityLifecycleCallbacks {
    static final int FLAGS = View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY | View.SYSTEM_UI_FLAG_FULLSCREEN
            | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
            | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION;

    static void install(Context c) {
        Context app = c.getApplicationContext();
        if (app instanceof Application) {
            ((Application) app).registerActivityLifecycleCallbacks(new Immersive());
        }
    }

    static void apply(Activity a) {
        Window w = a.getWindow();
        if (Build.VERSION.SDK_INT >= 30) {
            WindowInsetsController ic = w.getInsetsController();
            if (ic != null) {
                ic.hide(WindowInsets.Type.systemBars());
                ic.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
                return;
            }
        }
        w.getDecorView().setSystemUiVisibility(FLAGS);
    }

    /** Dang o che do "dinh" chua? Qt showFullScreen() (chay SAU onResume, luc Python len)
     *  dat lai che do "cham la hien" — do 19/10: chi lan cham DAU sau khi mo bi lo thanh. */
    static boolean sticky(Activity a) {
        Window w = a.getWindow();
        if (Build.VERSION.SDK_INT >= 30 && w.getInsetsController() != null) {
            return w.getInsetsController().getSystemBarsBehavior()
                    == WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE;
        }
        return (w.getDecorView().getSystemUiVisibility() & View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY) != 0;
    }

    private Activity hooked;  // resume nhieu lan — gan listener mot lan cho moi activity

    @Override
    public void onActivityResumed(Activity a) {
        apply(a);
        if (a == hooked) return;
        hooked = a;
        View d = a.getWindow().getDecorView();
        d.setOnSystemUiVisibilityChangeListener(vis -> {
            if ((vis & View.SYSTEM_UI_FLAG_FULLSCREEN) == 0) {  // thanh vua hien
                d.postDelayed(() -> apply(a), 1500);
            }
        });
        // Qt doi trang thai cua so (toan man hinh luc khoi dong...) -> bo cuc dan lai -> dat lai.
        d.getViewTreeObserver().addOnGlobalLayoutListener(() -> {
            if (!sticky(a)) d.post(() -> apply(a));
        });
        d.getViewTreeObserver().addOnWindowFocusChangeListener(focus -> {
            if (focus) apply(a);  // dong hop thoai (quyen USB...) xong
        });
    }

    @Override public void onActivityCreated(Activity a, Bundle b) { }
    @Override public void onActivityStarted(Activity a) { }
    @Override public void onActivityPaused(Activity a) { }
    @Override public void onActivityStopped(Activity a) { }
    @Override public void onActivitySaveInstanceState(Activity a, Bundle b) { }
    @Override public void onActivityDestroyed(Activity a) { }
}
