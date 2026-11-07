import base64, glob, hashlib, html, json, os, re, shlex, shutil, subprocess, sys

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


def unzip():
    import zipfile
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


def prep():
    kind, work = "generated", "."
    if c.get("sr") in ("repo", "zip"):
        root = W
        if c["sr"] == "zip":
            root = unzip()
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
        kind = detect(work)
        if not kind:
            fail("Jenis proyek tidak dikenali (Flutter, Capacitor, React Native, Gradle Android, atau web).")
        print("Jenis proyek terdeteksi:", kind)
    json.dump({"kind": kind, "work": work}, open(STATE, "w"))
    open(os.environ["GITHUB_OUTPUT"], "a").write("kind=%s\n" % kind)
    V = c["var"].capitalize()
    aab = c["fmt"] == "aab"
    task = ("bundle" if aab else "assemble") + V
    args = c.get("args", "")
    me = 'python3 "$GITHUB_WORKSPACE/tools/generate.py"'
    gw = "./gradlew %s %s --no-daemon --stacktrace" % (task, args)
    native = "gradle -p %s %s %s --no-daemon --stacktrace" % (D, task, args)
    split = "--split-per-abi" if c.get("abi") and not aab else ""
    scripts = {
        "generated": native,
        "web": native,
        "gradle": 'cd "%s"\n%s patch "$PWD"\nif [ -f gradlew ]; then chmod +x gradlew; %s; else gradle %s %s --no-daemon --stacktrace; fi' % (work, me, gw, task, args),
        "capacitor": 'cd "%s"\n(npm ci || npm install)\nnpm run build --if-present\nnpx cap sync android\n%s patch "$PWD/android"\ncd android\nchmod +x gradlew\n%s' % (work, me, gw),
        "rn": 'cd "%s"\n(npm ci || npm install)\n[ -d android ] || npx expo prebuild --platform android --no-install\n%s patch "$PWD/android"\ncd android\nchmod +x gradlew\n%s' % (work, me, gw),
        "flutter": 'cd "%s"\n[ -d android ] || flutter create --platforms=android .\n%s patch "$PWD/android"\nflutter pub get\nflutter build %s --%s --build-name %s --build-number %d %s %s' % (
            work, me, "appbundle" if aab else "apk", c["var"], shlex.quote(c["vn"]), int(c["vc"]), split, args),
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
    aab = c["fmt"] == "aab"
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
    bcf = '        buildConfigField("Boolean", "KIOSK", "%s")\n' % str(bool(c.get("kiosk"))).lower()
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
}
""", PKG=pkg, MIN=max(int(c["min"]), 26), VC=int(c["vc"]), VN=c["vn"].replace('"', ""),
        URL=json.dumps(json.dumps(url)), KP=kp, AL=al, KS=ks.replace("\\", "/"),
        MF=str(minify).lower(), ABI=str(bool(c["abi"]) and not aab).lower(), BCF=bcf, FLV=flv)
    w("app/proguard-rules.pro", "-keep class @PKG@.** { *; }\n-dontwarn **\n", PKG=pkg)
    w("app/src/main/AndroidManifest.xml", """<manifest xmlns:android="http://schemas.android.com/apk/res/android">
@USES@
    <application android:label="@string/app_name" android:icon="@mipmap/ic_launcher" android:theme="@style/AppTheme">
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
import android.os.Bundle
import android.view.View
import android.view.WindowManager
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.TextView
import androidx.webkit.WebViewAssetLoader

class MainActivity : Activity() {
    private var web: WebView? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (BuildConfig.APP_URL.isNotEmpty()) {
            val loader = WebViewAssetLoader.Builder()
                .addPathHandler("/", WebViewAssetLoader.AssetsPathHandler(this)).build()
            val w = WebView(this)
            w.settings.javaScriptEnabled = true
            w.settings.domStorageEnabled = true
            w.webViewClient = object : WebViewClient() {
                override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? =
                    loader.shouldInterceptRequest(request.url)
            }
            web = w
            setContentView(w)
            w.loadUrl(BuildConfig.APP_URL)
        } else {
            val t = TextView(this)
            t.text = getString(R.string.app_name)
            t.textSize = 24f
            t.setPadding(48, 96, 48, 48)
            setContentView(t)
        }
        if (BuildConfig.KIOSK) {
            window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            window.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_FULLSCREEN or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
        }
    }

    override fun onBackPressed() {
        val w = web
        if (w != null && w.canGoBack()) w.goBack() else super.onBackPressed()
    }
}
""", PKG=pkg)
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


def collect():
    st = json.load(open(STATE))
    kind, work = st["kind"], st["work"]
    base = D if kind in ("generated", "web") else work
    ext = "aab" if c["fmt"] == "aab" else "apk"
    fs = [f for f in sorted(glob.glob("%s/**/outputs/**/*.%s" % (base, ext), recursive=True)) if "androidTest" not in f]
    if not fs:
        fail("Output tidak ditemukan. Periksa log tahap Build.")
    ks, kp, al = keystore()
    os.makedirs("dist", exist_ok=True)
    print("::group::Penandatanganan")
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
    files = [{"n": os.path.basename(f), "size": os.path.getsize(f),
              "sha": hashlib.sha256(open(f, "rb").read()).hexdigest()} for f in sorted(glob.glob("dist/*"))]
    gen = json.load(open(D + "/.gen")) if os.path.exists(D + "/.gen") else []
    info = {"name": c["name"], "pkg": c["pkg"], "kind": kind, "files": files, "gen": gen}
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
