package dev.ultron.ultron_app

import android.app.role.RoleManager
import android.content.Intent
import android.os.Build
import android.provider.Settings
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

/**
 * The ULTRON app. Besides the Flutter UI it exposes two channels:
 *
 * - "ultron/assistant": whether the app was opened as the assistant, whether
 *   ULTRON is the default assistant, and the system settings to choose it;
 * - "ultron/phone": the phone actions in [PhoneTools].
 */
class MainActivity : FlutterActivity() {
    private var assistChannel: MethodChannel? = null
    private var pendingAssist = false
    private val phone by lazy { PhoneTools(this) }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        pendingAssist = isAssist(intent)
        val messenger = flutterEngine.dartExecutor.binaryMessenger
        assistChannel = MethodChannel(messenger, "ultron/assistant").apply {
            setMethodCallHandler { call, result ->
                when (call.method) {
                    // True once if the app was started by an assistant invocation.
                    "takeLaunchAssist" -> { result.success(pendingAssist); pendingAssist = false }
                    "isDefaultAssistant" -> result.success(isDefaultAssistant())
                    "openAssistantSettings" -> { openAssistantSettings(); result.success(null) }
                    else -> result.notImplemented()
                }
            }
        }
        MethodChannel(messenger, "ultron/phone").setMethodCallHandler { call, result ->
            try {
                when (call.method) {
                    "status" -> result.success(phone.status())
                    "apps" -> result.success(phone.launchableApps().keys.sorted())
                    "openApp" -> result.success(phone.openApp(call.argument<String>("app") ?: ""))
                    "setAlarm" -> result.success(
                        phone.setAlarm(
                            call.argument<Int>("hour") ?: 0,
                            call.argument<Int>("minute") ?: 0,
                            call.argument<String>("label") ?: "ULTRON",
                        ),
                    )
                    "setTimer" -> result.success(
                        phone.setTimer(call.argument<Int>("seconds") ?: 60, call.argument<String>("label") ?: "ULTRON"),
                    )
                    "notify" -> result.success(
                        phone.notify(
                            call.argument<Int>("id") ?: 1,
                            call.argument<String>("title") ?: "ULTRON",
                            call.argument<String>("text") ?: "",
                        ),
                    )
                    "canNotify" -> result.success(phone.canNotify())
                    "requestNotifications" -> { phone.requestNotifications(); result.success(null) }
                    else -> result.notImplemented()
                }
            } catch (e: Exception) {
                result.error("phone_error", e.message ?: e.javaClass.simpleName, null)
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (isAssist(intent)) {
            // Already running: tell Flutter to open the assistant screen now.
            assistChannel?.invokeMethod("assist", null) ?: run { pendingAssist = true }
        }
    }

    private fun isAssist(intent: Intent?): Boolean =
        intent?.action == ACTION_ULTRON_ASSIST || intent?.action == Intent.ACTION_ASSIST ||
            intent?.action == Intent.ACTION_VOICE_COMMAND

    private fun isDefaultAssistant(): Boolean {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val roles = getSystemService(RoleManager::class.java)
            if (roles != null && roles.isRoleAvailable(RoleManager.ROLE_ASSISTANT)) {
                return roles.isRoleHeld(RoleManager.ROLE_ASSISTANT)
            }
        }
        val current = Settings.Secure.getString(contentResolver, "voice_interaction_service")
        return current?.startsWith("$packageName/") == true
    }

    /** The user chooses the assistant in system settings; apps can't take the role themselves. */
    private fun openAssistantSettings() {
        val candidates = listOf(
            Intent(Settings.ACTION_VOICE_INPUT_SETTINGS),
            Intent("android.settings.MANAGE_DEFAULT_APPS_SETTINGS"),
            Intent(Settings.ACTION_SETTINGS),
        )
        val intent = candidates.first { it.resolveActivity(packageManager) != null }
        startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    companion object {
        const val ACTION_ULTRON_ASSIST = "dev.ultron.ultron_app.ASSIST"
    }
}
