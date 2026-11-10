package dev.ultron.ultron_app

import android.content.ComponentName
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognitionService
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer

/**
 * Required by Android for a digital assistant. From Android 12 the system
 * ignores it; on Android 11 and older, choosing ULTRON as the assistant
 * also makes this the phone's default speech recognizer. So it must work:
 * it passes requests on to the phone's own recognizer (the on-device one
 * when the caller prefers offline and the phone has one).
 */
class UltronRecognitionService : RecognitionService() {
    private var delegate: SpeechRecognizer? = null

    override fun onStartListening(recognizerIntent: Intent, listener: Callback) {
        delegate?.destroy()
        val preferOffline = recognizerIntent.getBooleanExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, false)
        val recognizer = when {
            preferOffline && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S &&
                SpeechRecognizer.isOnDeviceRecognitionAvailable(this) ->
                SpeechRecognizer.createOnDeviceSpeechRecognizer(this)
            else -> otherRecognizer()?.let { SpeechRecognizer.createSpeechRecognizer(this, it) }
        }
        if (recognizer == null) {
            listener.error(SpeechRecognizer.ERROR_CLIENT)
            return
        }
        delegate = recognizer
        recognizer.setRecognitionListener(Forwarder(listener))
        recognizer.startListening(recognizerIntent)
    }

    override fun onStopListening(listener: Callback) {
        delegate?.stopListening()
    }

    override fun onCancel(listener: Callback) {
        delegate?.cancel()
    }

    override fun onDestroy() {
        delegate?.destroy()
        delegate = null
        super.onDestroy()
    }

    /** Another installed recognizer, never this one (no loop). Google's first. */
    private fun otherRecognizer(): ComponentName? {
        val services = packageManager.queryIntentServices(
            Intent(SERVICE_INTERFACE), PackageManager.MATCH_ALL,
        ).mapNotNull { it.serviceInfo }.filter { it.packageName != packageName }
        val preferred = services.firstOrNull {
            it.packageName == "com.google.android.googlequicksearchbox" ||
                it.packageName == "com.google.android.tts" ||
                it.packageName == "com.google.android.as"
        } ?: services.firstOrNull()
        return preferred?.let { ComponentName(it.packageName, it.name) }
    }

    private class Forwarder(private val out: Callback) : RecognitionListener {
        override fun onReadyForSpeech(params: Bundle?) = out.readyForSpeech(params ?: Bundle())
        override fun onBeginningOfSpeech() = out.beginningOfSpeech()
        override fun onRmsChanged(rmsdB: Float) = out.rmsChanged(rmsdB)
        override fun onBufferReceived(buffer: ByteArray?) { if (buffer != null) out.bufferReceived(buffer) }
        override fun onEndOfSpeech() = out.endOfSpeech()
        override fun onError(error: Int) = out.error(error)
        override fun onResults(results: Bundle?) = out.results(results ?: Bundle())
        override fun onPartialResults(partialResults: Bundle?) = out.partialResults(partialResults ?: Bundle())
        override fun onEvent(eventType: Int, params: Bundle?) {}
    }
}
