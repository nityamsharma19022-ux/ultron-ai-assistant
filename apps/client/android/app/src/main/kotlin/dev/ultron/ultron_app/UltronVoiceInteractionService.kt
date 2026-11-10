package dev.ultron.ultron_app

import android.service.voice.VoiceInteractionService

/**
 * Lets the user pick ULTRON as the phone's digital assistant. Android starts
 * it while ULTRON holds the assistant role; the actual work happens in
 * [UltronSession], which opens ULTRON's assistant screen.
 */
class UltronVoiceInteractionService : VoiceInteractionService()
