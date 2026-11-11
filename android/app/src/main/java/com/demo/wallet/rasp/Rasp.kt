package com.demo.wallet.rasp

import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Debug
import com.demo.wallet.BuildConfig
import com.demo.wallet.Guard
import java.io.File
import java.security.MessageDigest

/**
 * Runtime application self-protection checks.
 *
 * Every check is cheap and local, and every one can be bypassed by someone who
 * controls the device — that is the talk's point. They are collected as evidence
 * and shipped to the server; none of them blocks on its own except the
 * deliberately naive Guard.isRooted() gate in the UI.
 */
object Rasp {

    fun collect(context: Context): RaspReport {
        val details = mutableListOf<String>()

        // 1. Root — reuse the exact method Lab 1 hooks, so a hooked device reports
        //    root=0 here too. The hook still shows up under "hooked" below.
        val rooted = Guard.isRooted()
        if (rooted) details += "root:su-present"

        val emulator = EmulatorCheck.run(details)
        val debugger = DebuggerCheck.run(details)
        val signatureValid = SignatureCheck.run(context, details)
        val hooked = HookCheck.run(details)

        return RaspReport(rooted, emulator, debugger, signatureValid, hooked, details.toList())
    }
}

internal object EmulatorCheck {
    fun run(details: MutableList<String>): Boolean {
        val hits = buildList {
            val fp = Build.FINGERPRINT.orEmpty()
            if (fp.startsWith("generic") || fp.contains("emulator") || fp.contains("sdk_gphone")) add("fingerprint")
            val hw = Build.HARDWARE.orEmpty()
            if (hw.contains("goldfish") || hw.contains("ranchu")) add("hardware:$hw")
            val product = Build.PRODUCT.orEmpty()
            if (product.contains("sdk") || product.contains("emulator") || product.contains("simulator")) add("product:$product")
            if (Build.MODEL.orEmpty().contains("Android SDK built for")) add("model")
            if (File("/dev/qemu_pipe").exists() || File("/dev/goldfish_pipe").exists()) add("qemu-pipe")
        }
        hits.forEach { details += "emu:$it" }
        return hits.isNotEmpty()
    }
}

internal object DebuggerCheck {
    fun run(details: MutableList<String>): Boolean {
        var hit = false
        if (Debug.isDebuggerConnected() || Debug.waitingForDebugger()) {
            details += "dbg:jdwp"; hit = true
        }
        // A native tracer (gdb, strace, some injectors) shows up as TracerPid.
        val tracer = runCatching {
            File("/proc/self/status").readLines()
                .firstOrNull { it.startsWith("TracerPid:") }
                ?.substringAfter(':')?.trim()?.toIntOrNull() ?: 0
        }.getOrDefault(0)
        if (tracer != 0) {
            details += "dbg:tracer=$tracer"; hit = true
        }
        // Informational only: lab builds are debuggable by design, so not a flag.
        if (BuildConfig.DEBUG) details += "info:debuggable-build"
        return hit
    }
}

internal object SignatureCheck {
    fun run(context: Context, details: MutableList<String>): Boolean = runCatching {
        val info = context.packageManager.getPackageInfo(
            context.packageName, PackageManager.GET_SIGNING_CERTIFICATES
        )
        val signing = info.signingInfo ?: return@runCatching false.also { details += "sig:none" }
        val certs = if (signing.hasMultipleSigners()) signing.apkContentsSigners else signing.signingCertificateHistory
        val digests = certs.map { sha256Hex(it.toByteArray()) }
        val ok = digests.any { it.equals(BuildConfig.EXPECTED_SIGNER_SHA256, ignoreCase = true) }
        if (!ok) details += "sig:mismatch:${digests.firstOrNull()?.take(16)}"
        ok
    }.getOrElse { details += "sig:error:${it.javaClass.simpleName}"; false }

    private fun sha256Hex(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
}

internal object HookCheck {
    private val MAP_MARKERS = listOf("frida", "gum-js", "gadget", "linjector", "xposed", "lsposed", "substrate")
    private val THREAD_MARKERS = listOf("gum-js-loop", "gmain", "gdbus", "pool-frida", "frida")
    private const val FRIDA_PORT_HEX = ":69A2" // 27042, frida-server's default port

    fun run(details: MutableList<String>): Boolean {
        var hit = false

        // Frida injects frida-agent-*.so (often as a memfd) into the process.
        runCatching {
            File("/proc/self/maps").useLines { lines ->
                lines.map { it.lowercase() }
                    .mapNotNull { line -> MAP_MARKERS.firstOrNull { line.contains(it) } }
                    .distinct()
                    .forEach { details += "hook:maps:$it"; hit = true }
            }
        }

        // Frida's JS runtime runs on named threads inside the target process.
        runCatching {
            File("/proc/self/task").listFiles()?.forEach { task ->
                val name = runCatching { File(task, "comm").readText().trim() }.getOrDefault("")
                THREAD_MARKERS.firstOrNull { name.contains(it) }?.let {
                    details += "hook:thread:$name"; hit = true
                }
            }
        }

        // frida-server listening on its default port. Often unreadable for apps
        // on Android 10+ (SELinux) — then it simply contributes nothing.
        runCatching {
            listOf("/proc/net/tcp", "/proc/net/tcp6").forEach { path ->
                File(path).useLines { lines ->
                    if (lines.drop(1).any { l ->
                            val cols = l.trim().split(Regex("\\s+"))
                            cols.size > 3 && cols[1].uppercase().endsWith(FRIDA_PORT_HEX) && cols[3] == "0A"
                        }) {
                        details += "hook:port:27042"; hit = true
                    }
                }
            }
        }

        // Xposed / LSPosed framework classes on the classpath.
        listOf("de.robv.android.xposed.XposedBridge", "de.robv.android.xposed.XC_MethodHook").forEach { cls ->
            if (runCatching { Class.forName(cls) }.isSuccess) {
                details += "hook:class:$cls"; hit = true
            }
        }

        return hit
    }
}
