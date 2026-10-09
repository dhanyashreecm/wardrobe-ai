import "./styles/mobile.css";
import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import './App.css';
import './styles/aw.css';
import App from './App';
import reportWebVitals from './reportWebVitals';

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

// If you want to start measuring performance in your app, pass a function
// to log results (for example: reportWebVitals(console.log))
// or send to an analytics endpoint. Learn more: https://bit.ly/CRA-vitals
reportWebVitals();

// Makes the app installable ("Add to Home Screen" / "Install app").
// Only in the production build - in `npm start` dev mode a service
// worker would serve stale code while you're editing.
// Not inside the installed phone app: its files already ship with the APK.
const insideNativeApp = Boolean(window.Capacitor && window.Capacitor.isNativePlatform
  && window.Capacitor.isNativePlatform());
if ("serviceWorker" in navigator && process.env.NODE_ENV === "production" && !insideNativeApp) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/service-worker.js")
      .then((reg) => reg.update())
      .catch((err) => {
        console.warn("Service worker registration failed:", err);
      });
    // A newer build took over: reload once so no old screen stays open.
    let reloaded = false;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (!reloaded) { reloaded = true; window.location.reload(); }
    });
  });
}
