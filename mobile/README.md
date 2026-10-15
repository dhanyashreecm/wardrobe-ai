# Wardrobe AI - phone app

The app is the same React frontend, packaged with Capacitor 7.
Native plugins: @capacitor/camera (rear camera, multi-select gallery)
and @capacitor/status-bar.

## Android APK (free)

Needs Node 18+, JDK 21 and the Android SDK.

    cd frontend && npm install && npm run build
    cd ../mobile && npm install
    npx cap sync android
    cd android && ./gradlew assembleRelease
    # -> android/app/build/outputs/apk/release/app-release.apk

The release APK is signed with the key in `mobile/keystore/` (git-ignored).
Keep a backup of that folder: phones only accept an update signed with the
same key. Bump `versionCode` in android/app/build.gradle for every new APK.

The server address is set inside the app: login screen -> "Server".
For the Play Store you would build an AAB instead (`./gradlew bundleRelease`)
and need a Play Console account (one-time fee) - not needed for sharing the APK.

## iPhone (free)

Apple only lets a free account install an app on your own iPhone for 7 days,
so for other iPhone users the free route is the web app:
open the backend's https address in Safari -> Share -> "Add to Home Screen".
The backend serves the built frontend itself (see serve_web_app in backend/app.py),
so camera, gallery and multi-select all work from Safari too.
