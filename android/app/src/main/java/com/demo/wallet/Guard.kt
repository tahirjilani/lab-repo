package com.demo.wallet

import android.os.Build
import java.io.File

/**
 * The app's local "is this device rooted?" gate.
 *
 * Deliberately simple: one boolean, decided on the device, trusted by the app.
 * Lab 1 hooks exactly this method with Frida:
 *
 *   Java.use("com.demo.wallet.Guard").isRooted.implementation = () => false
 *
 * Kept as a static method on a Kotlin `object` (@JvmStatic) so the Java-level
 * signature is `static boolean com.demo.wallet.Guard.isRooted()` and every caller
 * goes through it. Do not inline it, cache it, or fold it into RaspReport.
 *
 * The richer evidence (emulator, debugger, signature, hooks) lives in rasp/ and is
 * sent to the server as flags — the point of Lab 2 is that the server, not this
 * boolean, makes the decision.
 */
object Guard {

    private val SU_PATHS = listOf(
        "/system/bin/su",
        "/system/xbin/su",
        "/sbin/su",
        "/su/bin/su",
        "/system/sbin/su",
        "/vendor/bin/su",
        "/data/local/su",
        "/data/local/bin/su",
        "/data/local/xbin/su",
        "/system/app/Superuser.apk",
        "/system/app/SuperSU.apk",
        "/data/adb/magisk",
    )

    /**
     * True when an su binary or root manager is present. On the "Google APIs"
     * emulator images (userdebug) /system/xbin/su exists, so Lab 1's emulator is
     * "rooted"; "Google Play" images are user builds without su and pass.
     * (Build.TAGS is not used: emulator images vary between dev-keys and
     * test-keys, which would make the gate flaky across attendees' machines.)
     */
    @JvmStatic
    fun isRooted(): Boolean =
        isRootableBuild() ||
            SU_PATHS.any { path -> runCatching { File(path).exists() }.getOrDefault(false) }

    /**
     * userdebug/eng builds allow `adb root` (that's how frida-server runs as root on
     * the Lab 1 emulator), even when newer Google APIs images ship no su binary the
     * app can see. Google Play images and retail phones are "user" builds and pass.
     */
    private fun isRootableBuild(): Boolean =
        Build.TYPE == "userdebug" || Build.TYPE == "eng"
}
