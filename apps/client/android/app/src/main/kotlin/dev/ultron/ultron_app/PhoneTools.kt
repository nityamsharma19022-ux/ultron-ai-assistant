package dev.ultron.ultron_app

import android.Manifest
import android.app.Activity
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.BatteryManager
import android.os.Build
import android.provider.AlarmClock
import androidx.core.app.ActivityCompat
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat

/**
 * Phone actions ULTRON's tasks can run (the "phone.*" tools), using only
 * public Android APIs. Alarms and timers go through the clock app.
 */
class PhoneTools(private val activity: Activity) {
    private val context: Context get() = activity

    fun status(): Map<String, Any?> {
        val battery = context.getSystemService(Context.BATTERY_SERVICE) as BatteryManager
        val level = battery.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
        val charging = battery.isCharging
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val caps = cm.getNetworkCapabilities(cm.activeNetwork)
        val network = when {
            caps == null -> "offline"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "Wi-Fi"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "mobile data"
            else -> "connected"
        }
        return mapOf(
            "battery_percent" to level,
            "charging" to charging,
            "network" to network,
            "android" to Build.VERSION.RELEASE,
            "model" to "${Build.MANUFACTURER} ${Build.MODEL}",
            "summary" to "Battery $level%${if (charging) " (charging)" else ""}, $network",
            "verified" to true,
        )
    }

    /** Apps with a launcher icon, by label. */
    fun launchableApps(): Map<String, String> {
        val pm = context.packageManager
        val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        return pm.queryIntentActivities(intent, 0).associate {
            it.loadLabel(pm).toString() to it.activityInfo.packageName
        }
    }

    fun openApp(name: String): Map<String, Any?> {
        val apps = launchableApps()
        val key = name.trim().lowercase()
        val match = apps.entries.firstOrNull { it.key.lowercase() == key }
            ?: apps.entries.filter { it.key.lowercase().contains(key) }.singleOrNull()
            ?: return mapOf("ok" to false, "error" to "No app called '$name' on this phone")
        val launch = context.packageManager.getLaunchIntentForPackage(match.value)
            ?: return mapOf("ok" to false, "error" to "${match.key} can't be opened")
        launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        activity.startActivity(launch)
        return mapOf("ok" to true, "summary" to "Opened ${match.key}", "verified" to true)
    }

    fun setAlarm(hour: Int, minute: Int, label: String): Map<String, Any?> {
        val intent = Intent(AlarmClock.ACTION_SET_ALARM)
            .putExtra(AlarmClock.EXTRA_HOUR, hour)
            .putExtra(AlarmClock.EXTRA_MINUTES, minute)
            .putExtra(AlarmClock.EXTRA_MESSAGE, label)
            .putExtra(AlarmClock.EXTRA_SKIP_UI, true)
        return startClock(intent, "Alarm set for %02d:%02d".format(hour, minute))
    }

    fun setTimer(seconds: Int, label: String): Map<String, Any?> {
        val intent = Intent(AlarmClock.ACTION_SET_TIMER)
            .putExtra(AlarmClock.EXTRA_LENGTH, seconds)
            .putExtra(AlarmClock.EXTRA_MESSAGE, label)
            .putExtra(AlarmClock.EXTRA_SKIP_UI, true)
        return startClock(intent, "Timer started for ${seconds / 60} min ${seconds % 60} s")
    }

    private fun startClock(intent: Intent, summary: String): Map<String, Any?> {
        if (intent.resolveActivity(context.packageManager) == null) {
            return mapOf("ok" to false, "error" to "No clock app can do that")
        }
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        activity.startActivity(intent)
        return mapOf("ok" to true, "summary" to summary, "verified" to true)
    }

    fun canNotify(): Boolean =
        Build.VERSION.SDK_INT < 33 ||
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) ==
            PackageManager.PERMISSION_GRANTED

    fun requestNotifications() {
        if (Build.VERSION.SDK_INT >= 33 && !canNotify()) {
            ActivityCompat.requestPermissions(activity, arrayOf(Manifest.permission.POST_NOTIFICATIONS), 41)
        }
    }

    fun notify(id: Int, title: String, text: String): Map<String, Any?> {
        if (!canNotify()) {
            return mapOf("ok" to false, "error" to "Notifications are off for ULTRON (allow them in Settings)")
        }
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= 26 && manager.getNotificationChannel(CHANNEL) == null) {
            manager.createNotificationChannel(
                NotificationChannel(
                    CHANNEL,
                    context.getString(R.string.notification_channel_name),
                    NotificationManager.IMPORTANCE_HIGH,
                ).apply { description = context.getString(R.string.notification_channel_description) },
            )
        }
        val open = PendingIntent.getActivity(
            context, 0, Intent(context, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val notification = NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setContentIntent(open)
            .setAutoCancel(true)
            .build()
        @Suppress("MissingPermission")
        NotificationManagerCompat.from(context).notify(id, notification)
        return mapOf("ok" to true, "summary" to "Notification shown", "verified" to true)
    }

    companion object {
        const val CHANNEL = "ultron"
    }
}
