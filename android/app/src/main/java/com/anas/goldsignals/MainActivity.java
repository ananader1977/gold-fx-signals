package com.anas.goldsignals;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;
import android.view.Window;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import androidx.swiperefreshlayout.widget.SwipeRefreshLayout;

/** Full-screen wrapper around the Gold Signals dashboard (GitHub Pages). */
public class MainActivity extends Activity {

    private static final String HOME = "https://ananader1977.github.io/gold-fx-signals/";
    private static final String HOST = "ananader1977.github.io";

    private WebView web;
    private SwipeRefreshLayout swipe;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Window w = getWindow();
        w.setStatusBarColor(Color.parseColor("#0f1115"));
        w.setNavigationBarColor(Color.parseColor("#0f1115"));

        swipe = new SwipeRefreshLayout(this);
        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor("#0f1115"));
        swipe.addView(web);
        setContentView(swipe);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);        // dashboard, charts, login decryption
        s.setDomStorageEnabled(true);        // stay signed in for the session, saved settings
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setMediaPlaybackRequiresUserGesture(true);

        web.setWebChromeClient(new WebChromeClient());
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                Uri u = req.getUrl();
                if (HOST.equals(u.getHost())) return false;          // stay in the app
                try { startActivity(new Intent(Intent.ACTION_VIEW, u)); } catch (Exception ignored) { }
                return true;                                         // other links open in the browser
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                swipe.setRefreshing(false);
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
                if (req.isForMainFrame()) {
                    swipe.setRefreshing(false);
                    view.loadDataWithBaseURL(null,
                        "<html><body style='background:#0f1115;color:#e7e9ee;font-family:sans-serif;"
                      + "display:flex;align-items:center;justify-content:center;height:100vh;text-align:center'>"
                      + "<div><div style='font-size:40px'>📡</div><h3>No connection</h3>"
                      + "<p style='color:#8b93a5'>Check your internet, then pull down to refresh.</p></div></body></html>",
                        "text/html", "utf-8", null);
                }
            }
        });

        // only pull-to-refresh when the page is scrolled to the top
        swipe.setOnChildScrollUpCallback((parent, child) -> web.getScrollY() > 0);
        swipe.setOnRefreshListener(() -> {
            web.clearCache(true);
            String cur = web.getUrl();
            if (cur == null || cur.startsWith("data:") || cur.equals("about:blank")) web.loadUrl(HOME);
            else web.reload();
        });

        if (savedInstanceState != null) web.restoreState(savedInstanceState);
        else web.loadUrl(HOME);
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    @Override
    protected void onResume() {
        super.onResume();
        web.onResume();
    }

    @Override
    protected void onPause() {
        web.onPause();
        super.onPause();
    }
}
