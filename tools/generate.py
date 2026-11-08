import base64, glob, hashlib, html, json, os, re, shlex, shutil, subprocess, sys

NEXA_TPL = 5

c = json.loads(os.environ["CFG"])
D, W, STATE = "build_app", "src_work", ".nexa.json"
GEN = []


def sh(*a):
    subprocess.run(list(a), check=True)


def fail(m):
    print("::error::" + m)
    sys.exit(1)


def w(p, t, **k):
    for a, b in k.items():
        t = t.replace("@" + a + "@", str(b))
    GEN.append(p)
    print("  +", p)
    p = os.path.join(D, p)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write(t)


def detect(r):
    has = lambda f: os.path.exists(os.path.join(r, f))
    pk = json.load(open(os.path.join(r, "package.json"))) if has("package.json") else {}
    deps = {**pk.get("dependencies", {}), **pk.get("devDependencies", {})}
    if has("pubspec.yaml"):
        return "flutter"
    if any(has("capacitor.config." + e) for e in ("ts", "json", "js")):
        return "capacitor"
    if "react-native" in deps or "expo" in deps:
        return "rn"
    if has("gradlew") or has("settings.gradle") or has("settings.gradle.kts"):
        return "gradle"
    if pk or has("index.html"):
        return "web"
    return None


def keystore():
    ks = os.path.abspath("release.jks")
    if os.environ.get("KS_B64"):
        open(ks, "wb").write(base64.b64decode(os.environ["KS_B64"]))
        kp = os.environ.get("KS_PASS") or "android123"
        al = os.environ.get("KEY_ALIAS") or "key"
        print("Keystore: dari secrets")
    else:
        kp, al = "android123", "key"
        if not os.path.exists(ks):
            sh("keytool", "-genkeypair", "-keystore", ks, "-alias", al, "-keyalg", "RSA", "-keysize", "2048",
               "-validity", "10000", "-storepass", kp, "-keypass", kp, "-dname", "CN=NexaBuild")
        print("Keystore: dibuat otomatis")
    return ks, kp, al


def unzip(z=None):
    import zipfile
    if z is None:
        z = c.get("zip", "")
        if not re.match(r"^uploads/[\w.-]+\.zip$", z) or not os.path.exists(z):
            fail("File ZIP tidak ditemukan di repo. Unggah ulang dari tab Build.")
    print("::group::Mengekstrak ZIP")
    zipfile.ZipFile(z).extractall(W)
    items = [x for x in os.listdir(W) if x != "__MACOSX"]
    print("Isi ZIP:", ", ".join(items[:12]))
    print("::endgroup::")
    one = os.path.join(W, items[0]) if len(items) == 1 else ""
    return one if one and os.path.isdir(one) else W


def fetchzip():
    import zipfile
    url = (c.get("src") or "").strip()
    if not re.match(r"^https?://\S+$", url):
        fail("URL ZIP tidak valid.")
    print("::group::Mengunduh ZIP")
    sh("curl", "-fL", "--max-time", "300", "--max-filesize", "209715200", "-o", "dl.zip", url)
    print("::endgroup::")
    if not zipfile.is_zipfile("dl.zip"):
        fail("Tautan itu bukan file ZIP yang valid.")
    return unzip("dl.zip")


def prep():
    sr = c.get("sr")
    if sr not in ("scratch", "repo", "zip", "ziplink"):
        fail("Konfigurasi sumber proyek tidak dikenali. Sinkronkan repo build dengan template terbaru (tombol di tab Build).")
    kind, work = "generated", "."
    if sr in ("repo", "zip", "ziplink"):
        root = W
        if sr == "zip":
            root = unzip()
        elif sr == "ziplink":
            root = fetchzip()
        else:
            url = (c.get("src") or "").strip()
            if not re.match(r"^https://[\w.-]+/[\w./~-]+$", url):
                fail("URL repo tidak valid. Gunakan alamat https.")
            tok = os.environ.get("SRC_TOKEN")
            if tok and url.startswith("https://github.com/"):
                url = url.replace("https://", "https://x-access-token:%s@" % tok, 1)
            print("::group::Mengambil repo")
            sh("git", "clone", "--depth", "1", *(["--branch", c["ref"]] if c.get("ref") else []), url, W)
            print("::endgroup::")
        work = os.path.join(root, c.get("sub") or "").rstrip("/")
        if not os.path.isdir(work):
            fail("Subfolder tidak ditemukan.")
        kind = c.get("kind") or detect(work)
        if not kind:
            fail("Jenis proyek tidak dikenali (Flutter, Capacitor, React Native, Gradle Android, atau web).")
        if kind not in ("web", "flutter", "capacitor", "rn", "gradle"):
            fail("Jenis proyek tidak valid: %s" % kind)
        print("Jenis proyek:", kind)
    json.dump({"kind": kind, "work": work}, open(STATE, "w"))
    open(os.environ["GITHUB_OUTPUT"], "a").write("kind=%s\n" % kind)
    V = c["var"].capitalize()
    aab, both = c["fmt"] == "aab", c["fmt"] == "both"
    task = ("assemble%s bundle%s" % (V, V)) if both else ("bundle" if aab else "assemble") + V
    args = c.get("args", "")
    me = 'python3 "$GITHUB_WORKSPACE/tools/generate.py"'
    gw = "./gradlew %s %s --no-daemon --stacktrace" % (task, args)
    native = "gradle -p %s %s %s --no-daemon --stacktrace" % (D, task, args)
    split = "--split-per-abi" if c.get("abi") and not (aab or both) else ""

    def fl(b):
        return "flutter build %s --%s --build-name %s --build-number %d %s %s" % (
            b, c["var"], shlex.quote(c["vn"]), int(c["vc"]), split if b == "apk" else "", args)

    fcmd = "\n".join(fl(b) for b in (["apk", "appbundle"] if both else ["appbundle"] if aab else ["apk"]))
    scripts = {
        "generated": native,
        "web": native,
        "gradle": 'cd "%s"\n%s patch "$PWD"\nif [ -f gradlew ]; then chmod +x gradlew; %s; else gradle %s %s --no-daemon --stacktrace; fi' % (work, me, gw, task, args),
        "capacitor": 'cd "%s"\n(npm ci || npm install)\nnpm run build --if-present\n([ -d android ] || npx cap add android)\nnpx cap sync android\n%s patch "$PWD/android"\ncd android\nchmod +x gradlew\n%s' % (work, me, gw),
        "rn": 'cd "%s"\n(npm ci || npm install)\n[ -d android ] || npx expo prebuild --platform android --no-install\n%s patch "$PWD/android"\ncd android\nchmod +x gradlew\n%s' % (work, me, gw),
        "flutter": 'cd "%s"\n[ -d android ] || flutter create --platforms=android .\n%s patch "$PWD/android"\nflutter pub get\n%s' % (work, me, fcmd),
    }
    open(".build.sh", "w").write("set -e\n" + scripts[kind] + "\n")


def patch(d):
    if c.get("ov") is False:
        print("Override metadata dimatikan")
        return
    d = os.path.abspath(d)
    files = [f for f in glob.glob(d + "/**/build.gradle*", recursive=True) if "node_modules" not in f]
    files.sort(key=lambda f: ("/app/" not in f, len(f)))
    app = next((f for f in files if "com.android.application" in open(f).read()), None)
    if not app:
        print("Modul aplikasi tidak ditemukan, metadata tidak diubah")
        return
    t = open(app).read()
    if c.get("ps"):
        t = re.sub(r'(applicationId\s*=?\s*)["\'][^"\']*["\']', lambda m: m.group(1) + '"' + c["pkg"] + '"', t)
    t = re.sub(r'(versionCode\s*=?\s*)\d+', lambda m: m.group(1) + str(int(c["vc"])), t)
    t = re.sub(r'(versionName\s*=?\s*)["\'][^"\']*["\']', lambda m: m.group(1) + '"' + c["vn"] + '"', t)
    open(app, "w").write(t)
    nm = html.escape(c["name"], quote=False).replace("'", "\\'")
    for mf in glob.glob(d + "/**/src/main/AndroidManifest.xml", recursive=True):
        x = open(mf).read()
        if "node_modules" in mf or "<application" not in x:
            continue
        if 'android:label="@string/app_name"' in x:
            sf = os.path.join(os.path.dirname(mf), "res/values/strings.xml")
            if os.path.exists(sf):
                s = re.sub(r'(<string name="app_name"[^>]*>)[^<]*', lambda m: m.group(1) + nm, open(sf).read())
                open(sf, "w").write(s)
        else:
            x = re.sub(r'android:label="[^"@][^"]*"', lambda m: 'android:label="%s"' % nm, x, count=1)
            open(mf, "w").write(x)
    print("Metadata diterapkan:", c["name"], c["vn"], c["vc"])


def gen():
    st = json.load(open(STATE))
    kind, work = st["kind"], st["work"]
    pkg = c["pkg"]
    name = html.escape(c["name"], quote=False).replace("'", "\\'")
    aab = c["fmt"] in ("aab", "both")
    minify = bool(c["minify"]) and c["var"] == "release"
    color = c["color"] if re.fullmatch(r"#[0-9a-fA-F]{6}", c["color"]) else "#FFD600"
    perms = set(c["perms"])
    url = c["url"]
    print("::group::Keystore")
    ks, kp, al = keystore()
    GEN.append("release.jks")
    print("::endgroup::")
    print("::group::Berkas proyek")
    if kind == "web":
        pj = os.path.join(work, "package.json")
        if os.path.exists(pj):
            has_build = "build" in json.load(open(pj)).get("scripts", {})
            sh("bash", "-c", 'cd "%s" && (npm ci || npm install)%s' % (work, " && npm run build" if has_build else ""))
        out = next((os.path.join(work, x) for x in ("dist", "build", "out", "public", "www")
                    if os.path.exists(os.path.join(work, x, "index.html"))), work)
        if not os.path.exists(os.path.join(out, "index.html")):
            fail("index.html tidak ditemukan setelah build web.")
        shutil.copytree(out, D + "/app/src/main/assets", dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("node_modules", ".git"))
        GEN.append("app/src/main/assets/ (isi web dari %s)" % out)
        url = "https://appassets.androidplatform.net/index.html"
    if url:
        perms.add("internet")
    PM = {"internet": "INTERNET", "camera": "CAMERA", "storage": "READ_EXTERNAL_STORAGE",
          "location": "ACCESS_FINE_LOCATION", "notifications": "POST_NOTIFICATIONS"}
    uses = "\n".join('    <uses-permission android:name="android.permission.%s"/>' % PM[p] for p in sorted(perms) if p in PM)
    orient = {"portrait": "portrait", "landscape": "landscape"}.get(c["orient"], "unspecified")
    def bb(k, v):
        return '        buildConfigField("Boolean", "%s", "%s")\n' % (k, str(bool(v)).lower())
    sc = c.get("sc") or ""
    bcf = "".join(bb(k, c.get(f)) for k, f in (("KIOSK", "kiosk"), ("FULLSCREEN", "fs"), ("KEEP_ON", "kp"), ("ZOOM", "zm"), ("EXTERNAL", "ex"), ("OFFLINE", "of"), ("PTR", "pt")))
    bcf += '        buildConfigField("String", "STATUS_COLOR", %s)\n' % json.dumps(json.dumps(sc if re.fullmatch(r"#[0-9a-fA-F]{6}", sc) else ""))
    bcf += '        buildConfigField("String", "USER_AGENT", %s)\n' % json.dumps(json.dumps(c.get("ua") or ""))
    for ln in (c.get("bc") or "").splitlines():
        if "=" in ln:
            k, v = ln.split("=", 1)
            k = re.sub(r"[^A-Z0-9_]", "_", k.strip().upper())
            if k:
                bcf += '        buildConfigField("String", "%s", %s)\n' % (k, json.dumps(json.dumps(v.strip())))
    fl = [re.sub(r"[^a-z0-9]", "", x.strip().lower()) for x in (c.get("flv") or "").split(",")]
    fl = [x for x in fl if x and x[0].isalpha()]
    flv = ""
    if fl:
        flv = 'flavorDimensions += "tier"\n    productFlavors {\n' + "".join(
            '        create("%s") { dimension = "tier"; applicationIdSuffix = ".%s" }\n' % (x, x) for x in fl) + "    }"
    w("settings.gradle.kts", """pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }
dependencyResolutionManagement { repositories { google(); mavenCentral() } }
rootProject.name = "app"
include(":app")
""")
    w("build.gradle.kts", """plugins {
    id("com.android.application") version "8.5.2" apply false
    id("org.jetbrains.kotlin.android") version "1.9.24" apply false
}
""")
    w("gradle.properties", "org.gradle.jvmargs=-Xmx3g\nandroid.useAndroidX=true\nandroid.nonTransitiveRClass=true\n")
    w("app/build.gradle.kts", """plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}
android {
    namespace = "@PKG@"
    compileSdk = 34
    defaultConfig {
        applicationId = "@PKG@"
        minSdk = @MIN@
        targetSdk = 34
        versionCode = @VC@
        versionName = "@VN@"
        buildConfigField("String", "APP_URL", @URL@)
@BCF@    }
    signingConfigs {
        create("rel") {
            storeFile = file("@KS@")
            storePassword = "@KP@"
            keyAlias = "@AL@"
            keyPassword = "@KP@"
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = @MF@
            isShrinkResources = @MF@
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.getByName("rel")
        }
        debug { signingConfig = signingConfigs.getByName("rel") }
    }
    buildFeatures { buildConfig = true }
    @FLV@
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    splits {
        abi {
            isEnable = @ABI@
            reset()
            include("arm64-v8a", "armeabi-v7a", "x86_64")
            isUniversalApk = true
        }
    }
}
dependencies {
    implementation("androidx.webkit:webkit:1.11.0")
    implementation("androidx.swiperefreshlayout:swiperefreshlayout:1.1.0")
}
""", PKG=pkg, MIN=max(int(c["min"]), 26), VC=int(c["vc"]), VN=c["vn"].replace('"', ""),
        URL=json.dumps(json.dumps(url)), KP=kp, AL=al, KS=ks.replace("\\", "/"),
        MF=str(minify).lower(), ABI=str(bool(c["abi"]) and not aab).lower(), BCF=bcf, FLV=flv)
    w("app/proguard-rules.pro", "-keep class @PKG@.** { *; }\n-dontwarn **\n", PKG=pkg)
    w("app/src/main/AndroidManifest.xml", """<manifest xmlns:android="http://schemas.android.com/apk/res/android">
@USES@
    <application android:usesCleartextTraffic="true" android:label="@string/app_name" android:icon="@mipmap/ic_launcher" android:theme="@style/AppTheme">
        <activity android:name=".MainActivity" android:exported="true" android:screenOrientation="@OR@">
            <intent-filter>
                <action android:name="android.intent.action.MAIN"/>
                <category android:name="android.intent.category.LAUNCHER"/>
            </intent-filter>
        </activity>
    </application>
</manifest>
""", USES=uses, OR=orient)
    w("app/src/main/kotlin/" + pkg.replace(".", "/") + "/MainActivity.kt", """package @PKG@

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.view.WindowManager
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.TextView
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import androidx.webkit.WebViewAssetLoader

class MainActivity : Activity() {
    private var web: WebView? = null
    private var swipe: SwipeRefreshLayout? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (BuildConfig.STATUS_COLOR.isNotEmpty()) window.statusBarColor = Color.parseColor(BuildConfig.STATUS_COLOR)
        if (BuildConfig.APP_URL.isNotEmpty()) {
            val loader = WebViewAssetLoader.Builder()
                .addPathHandler("/", WebViewAssetLoader.AssetsPathHandler(this)).build()
            val w = WebView(this)
            w.settings.javaScriptEnabled = true
            w.settings.domStorageEnabled = true
            w.settings.setSupportZoom(BuildConfig.ZOOM)
            w.settings.builtInZoomControls = BuildConfig.ZOOM
            w.settings.displayZoomControls = false
            if (BuildConfig.USER_AGENT.isNotEmpty()) w.settings.userAgentString = BuildConfig.USER_AGENT
            w.webViewClient = object : WebViewClient() {
                override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? =
                    loader.shouldInterceptRequest(request.url)

                override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                    val u = request.url
                    val internal = u.host == "appassets.androidplatform.net" || u.host == Uri.parse(BuildConfig.APP_URL).host
                    if (BuildConfig.EXTERNAL && !internal) {
                        startActivity(Intent(Intent.ACTION_VIEW, u))
                        return true
                    }
                    return false
                }

                override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
                    swipe?.isRefreshing = false
                    if (BuildConfig.OFFLINE && request.isForMainFrame) view.loadUrl("https://appassets.androidplatform.net/__offline.html")
                }

                override fun onPageFinished(view: WebView, url: String) {
                    swipe?.isRefreshing = false
                }
            }
            web = w
            if (BuildConfig.PTR) {
                val sr = SwipeRefreshLayout(this)
                sr.addView(w)
                sr.setOnRefreshListener { w.reload() }
                swipe = sr
                setContentView(sr)
            } else {
                setContentView(w)
            }
            w.loadUrl(BuildConfig.APP_URL)
        } else {
            val t = TextView(this)
            t.text = getString(R.string.app_name)
            t.textSize = 24f
            t.setPadding(48, 96, 48, 48)
            setContentView(t)
        }
        if (BuildConfig.KIOSK || BuildConfig.KEEP_ON) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        if (BuildConfig.KIOSK || BuildConfig.FULLSCREEN) {
            window.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_FULLSCREEN or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
        }
    }

    override fun onBackPressed() {
        val w = web
        if (w != null && w.canGoBack()) w.goBack() else super.onBackPressed()
    }
}
""", PKG=pkg)
    if c.get("of"):
        w("app/src/main/assets/__offline.html", '<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><body style="font-family:sans-serif;display:grid;place-items:center;min-height:100vh;margin:0;text-align:center"><div><h2>Tidak ada koneksi</h2><p>Periksa internet lalu coba lagi.</p><button style="padding:12px 20px;font-size:16px" onclick="history.back()">Coba lagi</button></div>')
    w("app/src/main/res/values/strings.xml", '<resources><string name="app_name">@N@</string></resources>\n', N=name)
    w("app/src/main/res/values/colors.xml", '<resources><color name="ic_bg">@C@</color></resources>\n', C=color)
    w("app/src/main/res/values/themes.xml", """<resources>
    <style name="AppTheme" parent="android:Theme.Material.Light.NoActionBar">
        <item name="android:windowBackground">@color/ic_bg</item>
    </style>
</resources>
""")
    w("app/src/main/res/drawable/ic_fg.xml", """<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="108dp" android:height="108dp" android:viewportWidth="108" android:viewportHeight="108">
    <path android:fillColor="#FFFFFF" android:pathData="M34,34h40a6,6 0 0 1 6,6v28a6,6 0 0 1 -6,6h-40a6,6 0 0 1 -6,-6v-28a6,6 0 0 1 6,-6z"/>
</vector>
""")
    w("app/src/main/res/mipmap-anydpi-v26/ic_launcher.xml", """<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@color/ic_bg"/>
    <foreground android:drawable="@drawable/ic_fg"/>
</adaptive-icon>
""")
    if os.path.exists("assets/icon.png"):
        try:
            from PIL import Image
        except ImportError:
            sh(sys.executable, "-m", "pip", "install", "-q", "pillow")
            from PIL import Image
        im = Image.open("assets/icon.png").convert("RGBA").resize((288, 288))
        cv = Image.new("RGBA", (432, 432), (0, 0, 0, 0))
        cv.paste(im, (72, 72), im)
        os.remove(D + "/app/src/main/res/drawable/ic_fg.xml")
        os.makedirs(D + "/app/src/main/res/drawable-nodpi", exist_ok=True)
        cv.save(D + "/app/src/main/res/drawable-nodpi/ic_fg.png")
        GEN.append("app/src/main/res/drawable-nodpi/ic_fg.png (ikon kustom)")
        print("  + ikon kustom dari assets/icon.png")
    if c["fb"]:
        w("app/google-services.json", json.dumps({
            "project_info": {"project_number": "000000000000", "project_id": "dummy-project"},
            "client": [{"client_info": {"mobilesdk_app_id": "1:000000000000:android:0000000000000000",
                                        "android_client_info": {"package_name": pkg}},
                        "api_key": [{"current_key": "dummy"}]}],
            "configuration_version": "1"}))
    os.makedirs(D, exist_ok=True)
    json.dump(GEN, open(D + "/.gen", "w"))
    print("::endgroup::")
    print("Dibuat:", ", ".join(os.path.basename(x.split(" ")[0].rstrip("/")) for x in GEN))


def sign(f, dst, ext, ks, kp, al):
    if ext == "aab":
        shutil.copy(f, dst)
        sh("jarsigner", "-keystore", ks, "-storepass", kp, "-keypass", kp, dst, al)
        return
    bt = sorted(glob.glob(os.environ.get("ANDROID_HOME", "/usr/local/lib/android/sdk") + "/build-tools/*"))[-1]
    tmp = dst + ".aligned"
    sh(bt + "/zipalign", "-f", "-p", "4", f, tmp)
    sh(bt + "/apksigner", "sign", "--ks", ks, "--ks-pass", "pass:" + kp, "--key-pass", "pass:" + kp,
       "--ks-key-alias", al, "--v4-signing-enabled", "false", "--out", dst, tmp)
    os.remove(tmp)


def badging(f):
    import zipfile
    info = {"pkg": "", "vn": "", "vc": "", "label": "", "assets": 0}
    try:
        bt = sorted(glob.glob(os.environ.get("ANDROID_HOME", "/usr/local/lib/android/sdk") + "/build-tools/*"))[-1]
        out = subprocess.run([bt + "/aapt2", "dump", "badging", f], capture_output=True, text=True).stdout
        m = re.search(r"package: name='([^']*)' versionCode='(\d*)' versionName='([^']*)'", out)
        if m:
            info["pkg"], info["vc"], info["vn"] = m.groups()
        lb = re.search(r"application-label:'([^']*)'", out)
        info["label"] = lb.group(1) if lb else ""
    except Exception as e:
        print("aapt2 tidak tersedia:", e)
    info["assets"] = len([n for n in zipfile.ZipFile(f).namelist() if n.startswith("assets/")])
    return info


def collect():
    st = json.load(open(STATE))
    kind, work = st["kind"], st["work"]
    base = D if kind in ("generated", "web") else work
    exts = ["apk", "aab"] if c["fmt"] == "both" else ["aab" if c["fmt"] == "aab" else "apk"]
    ks, kp, al = keystore()
    os.makedirs("dist", exist_ok=True)
    print("::group::Penandatanganan")
    for ext in exts:
        fs = [f for f in sorted(glob.glob("%s/**/outputs/**/*.%s" % (base, ext), recursive=True)) if "androidTest" not in f]
        if not fs:
            fail("Output %s tidak ditemukan. Periksa log tahap Build." % ext.upper())
        for f in fs:
            b = os.path.basename(f)
            n = c["out"] + ("-" + b[:-len(ext) - 1].replace("-unsigned", "") if len(fs) > 1 else "")
            dst = "dist/%s.%s" % (n, ext)
            if "unsigned" in b:
                sign(f, dst, ext, ks, kp, al)
                print("Ditandatangani:", dst)
            else:
                shutil.copy(f, dst)
                print("Disalin:", dst)
    print("::endgroup::")
    for x in glob.glob("dist/*.idsig"):
        os.remove(x)
    apk = []
    if "apk" in exts:
        print("::group::Isi APK")
        for f in sorted(glob.glob("dist/*.apk")):
            b = badging(f)
            b["n"] = os.path.basename(f)
            apk.append(b)
            print(b["n"], b["pkg"], b["vn"], b["vc"], b["label"], "aset:", b["assets"])
        print("::endgroup::")
        if kind == "web" and any(x["assets"] == 0 for x in apk):
            fail("APK tidak memuat berkas web. Proyek tidak ikut terbundel.")
    files = [{"n": os.path.basename(f), "size": os.path.getsize(f),
              "sha": hashlib.sha256(open(f, "rb").read()).hexdigest()} for f in sorted(glob.glob("dist/*"))]
    gen = json.load(open(D + "/.gen")) if os.path.exists(D + "/.gen") else []
    info = {"name": c["name"], "pkg": c["pkg"], "kind": kind, "files": files, "gen": gen, "apk": apk}
    os.makedirs(D, exist_ok=True)
    open(D + "/.notes", "w").write((c.get("notes") or "Build " + os.environ["RUN"]) + "\n\n<!--nexa:" + json.dumps(info) + "-->\n")
    print("::group::Ringkasan")
    for f in files:
        print(f["n"], f["size"], "bytes", f["sha"])
    print("::endgroup::")
    open(os.environ["GITHUB_OUTPUT"], "a").write("tag=v%s-%s\n" % (c["vn"], os.environ["RUN"]))


cmd = sys.argv[1] if len(sys.argv) > 1 else "gen"
if cmd == "prep":
    prep()
elif cmd == "patch":
    patch(sys.argv[2])
elif cmd == "collect":
    collect()
else:
    gen()
