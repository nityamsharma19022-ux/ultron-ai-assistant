# ULTRON on Android (iQOO)

## 1. Install
- **Easiest:** download the APK built on GitHub (Actions → **ULTRON App
  CI** → artifact **ultron-android-apk**), copy it to the phone and
  install (allow "Install unknown apps" for your file manager).
- **Or build it:** `cd apps\client` then `flutter build apk --release`
  → `build\app\outputs\flutter-apk\app-release.apk`; or with the phone on
  USB (USB debugging on): `flutter run -d <device>`.

The APK is signed with the debug key: fine for your own phone; create a
release key before sharing it.

## 2. Connect to your PC
1. Do [setup step 4](ULTRON_SETUP_GUIDE.md#4-let-the-phone-reach-the-pc-optional-recommended-with-https)
   on the PC (HTTPS, LAN access, firewall).
2. On the PC app: **System → Devices → Pair a device**.
3. On the phone: **Pair with a code instead** → address
   `https://<PC's IPv4>:8000` → code → check the **security code** matches
   the PC → done. (Or sign in with email and password.)

## 3. Make ULTRON your assistant
Android lets **you** choose the digital assistant; apps can't take the
role themselves.

1. In ULTRON: **System → Assistant → Choose default assistant**, or
   Settings → Apps → Default apps → **Digital assistant app** (on iQOO /
   Funtouch / OriginOS the path may be Settings → Apps → Default apps →
   Assist & voice input).
2. Pick **ULTRON**.
3. Invoke it with your phone's assistant gesture: long-press the power or
   home button, or swipe up from a bottom corner (depends on the phone
   and its settings). ULTRON's assistant screen opens and says "Yes, I'm
   listening. What do you need?".
4. Say a command ("set an alarm for 6:30", "open Spotify", "remind me to
   call mom at 9 pm", "organize my downloads"). Say "stop", "never mind"
   or "go to sleep" to close it.

The System page shows whether ULTRON is the current assistant.

## 4. Wake word ("Hey ULTRON") — limitation
Not implemented, on purpose:
- Always-listening hotword detection on Android
  (`AlwaysOnHotwordDetector`, `HotwordDetectionService`) is reserved for
  privileged/system assistants (it needs system permissions an ordinary
  app can't get).
- The alternative, keeping the microphone open in a foreground service,
  drains the battery, shows a permanent notification, and on many phones
  (including vivo/iQOO's battery management) gets stopped anyway.

The supported replacement is the **system assistant gesture** above,
which works from anywhere, including the lock screen where Android allows
it. This has **not** been tested on the iQOO yet.

## 5. What the phone can do for ULTRON
While the app is open (Android limits background work), the phone runs
these task steps: open an app by name, set an alarm or timer (clock app),
show a notification, report battery and network. Due reminders appear as
notifications. Allow them in Tasks → Permissions (phone section).

## 6. Privacy on the phone
- Voice input in **private** chats is off on Android (the phone's
  recognizer may use an online service); read-aloud in private chats uses
  only offline voices.
- Notifications need Android 13+'s notification permission (asked when
  first needed).

## 7. Verification checklist (on the iQOO)
- [ ] APK installs; app opens; pairing works over HTTPS (security code matches)
- [ ] Chat streams replies; CLOUD/LOCAL badge shows
- [ ] ULTRON appears in the Digital assistant app list and can be selected
- [ ] The assistant gesture opens ULTRON's assistant screen and it listens
- [ ] From the lock screen (if the phone allows assistant there)
- [ ] "set an alarm for 6:30" creates the alarm; "open <app>" opens it
- [ ] A reminder shows as a notification when due (app open)
- [ ] Read-aloud works; private chat blocks voice input with an explanation
- [ ] Battery: no unusual drain with ULTRON as assistant
