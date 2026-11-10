package dev.ultron.ultron_app

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.service.voice.VoiceInteractionSession
import android.service.voice.VoiceInteractionSessionService

/** Hosts assistant sessions (long-press home, assistant gesture, headset button). */
class UltronSessionService : VoiceInteractionSessionService() {
    override fun onNewSession(args: Bundle?): VoiceInteractionSession = UltronSession(this)
}

/**
 * One assistant invocation. It doesn't draw its own UI: it opens ULTRON's
 * Flutter assistant screen (listening right away) and closes itself.
 * Works from the lock screen where the platform allows it; anything that
 * needs the account still requires the phone to be unlocked.
 */
class UltronSession(context: Context) : VoiceInteractionSession(context) {
    override fun onShow(args: Bundle?, showFlags: Int) {
        super.onShow(args, showFlags)
        val intent = Intent(context, MainActivity::class.java).apply {
            action = MainActivity.ACTION_ULTRON_ASSIST
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        }
        startAssistantActivity(intent)
        hide()
    }
}
