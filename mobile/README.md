# Wardrobe AI - Android app

The app is the same React frontend, packaged with Capacitor.

Build (needs Node 18+, JDK 21, Android SDK):

    cd frontend && REACT_APP_API_URL=https://YOUR-SERVER npm run build
    cd ../mobile && npm install && npx cap add android   # first time only
    npx cap sync android
    cd android && ./gradlew assembleDebug
    # -> android/app/build/outputs/apk/debug/app-debug.apk

The server address can also be changed inside the app: login screen -> "Server".
Camera permission is declared in android/app/src/main/AndroidManifest.xml.
