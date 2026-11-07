import base64, glob, html, json, os, re, shutil, subprocess, sys

c = json.loads(os.environ["CFG"])
D = "build_app"


def w(p, t, **k):
    for a, b in k.items():
        t = t.replace("@" + a + "@", str(b))
    p = os.path.join(D, p)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write(t)


if len(sys.argv) > 1:
    ext = "aab" if c["fmt"] == "aab" else "apk"
    fs = sorted(glob.glob(f"{D}/app/build/outputs/**/*.{ext}", recursive=True))
    if not fs:
        sys.exit("Output tidak ditemukan")
    os.makedirs("dist", exist_ok=True)
    for f in fs:
        n = c["out"] + ("-" + os.path.basename(f)[:-4] if len(fs) > 1 else "")
        shutil.copy(f, f"dist/{n}.{ext}")
    with open(os.environ["GITHUB_OUTPUT"], "a") as o:
        o.write(f"tag=v{c['vn']}-{os.environ['RUN']}\n")
    sys.exit()

pkg, name = c["pkg"], html.escape(c["name"], quote=False).replace("'", "\\'")
V = c["var"].capitalize()
aab = c["fmt"] == "aab"
minify = bool(c["minify"]) and c["var"] == "release"
color = c["color"] if re.fullmatch(r"#[0-9a-fA-F]{6}", c["color"]) else "#FFD600"
perms = set(c["perms"])
if c["url"]:
    perms.add("internet")
PM = {"internet": "INTERNET", "camera": "CAMERA", "storage": "READ_EXTERNAL_STORAGE",
      "location": "ACCESS_FINE_LOCATION", "notifications": "POST_NOTIFICATIONS"}
uses = "\n".join(f'    <uses-permission android:name="android.permission.{PM[p]}"/>' for p in sorted(perms) if p in PM)
orient = {"portrait": "portrait", "landscape": "landscape"}.get(c["orient"], "unspecified")

# keystore
ks = f"{D}/app/release.jks"
os.makedirs(f"{D}/app", exist_ok=True)
if os.environ.get("KS_B64"):
    open(ks, "wb").write(base64.b64decode(os.environ["KS_B64"]))
    kp, alias = os.environ.get("KS_PASS") or "android123", os.environ.get("KEY_ALIAS") or "key"
else:
    kp, alias = "android123", "key"
    subprocess.run(["keytool", "-genkeypair", "-keystore", ks, "-alias", alias, "-keyalg", "RSA",
                    "-keysize", "2048", "-validity", "10000", "-storepass", kp, "-keypass", kp,
                    "-dname", "CN=App"], check=True)

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
w("gradle.properties", "org.gradle.jvmargs=-Xmx3g\nandroid.nonTransitiveRClass=true\n")
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
    }
    signingConfigs {
        create("rel") {
            storeFile = file("release.jks")
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
""", PKG=pkg, MIN=max(int(c["min"]), 26), VC=int(c["vc"]), VN=c["vn"].replace('"', ""),
    URL=json.dumps(json.dumps(c["url"])), KP=kp, AL=alias,
    MF=str(minify).lower(), ABI=str(bool(c["abi"]) and not aab).lower())
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
import android.webkit.WebView
import android.widget.TextView

class MainActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (BuildConfig.APP_URL.isNotEmpty()) {
            val web = WebView(this)
            web.settings.javaScriptEnabled = true
            web.settings.domStorageEnabled = true
            setContentView(web)
            web.loadUrl(BuildConfig.APP_URL)
        } else {
            val t = TextView(this)
            t.text = getString(R.string.app_name)
            t.textSize = 24f
            t.setPadding(48, 96, 48, 48)
            setContentView(t)
        }
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
if c["fb"]:
    w("app/google-services.json", json.dumps({
        "project_info": {"project_number": "000000000000", "project_id": "dummy-project"},
        "client": [{"client_info": {"mobilesdk_app_id": "1:000000000000:android:0000000000000000",
                                    "android_client_info": {"package_name": pkg}},
                    "api_key": [{"current_key": "dummy"}]}],
        "configuration_version": "1"}))

task = ("bundle" if aab else "assemble") + V
open(f"{D}/.args", "w").write(task + " " + c["args"])
