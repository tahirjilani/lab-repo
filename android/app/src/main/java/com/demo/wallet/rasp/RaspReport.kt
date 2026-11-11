package com.demo.wallet.rasp

/**
 * Evidence collected on the device. The client never decides on it — it is sent
 * with every request (header X-RASP) and in the transfer body, and the server's
 * risk engine decides allow / monitor / step-up / block.
 *
 * Pure Kotlin (no Android types) so it can be unit-tested on the JVM.
 */
data class RaspReport(
    /** Result of Guard.isRooted() — the value Lab 1's Frida hook flips to false. */
    val rooted: Boolean,
    val emulator: Boolean,
    val debugger: Boolean,
    /** True when the signing certificate matches the expected lab certificate. */
    val signatureValid: Boolean,
    /** Instrumentation seen: Frida agent/threads/port, Xposed classes. */
    val hooked: Boolean,
    /** Human-readable reasons, e.g. "su:/system/xbin/su", "maps:frida-agent". */
    val details: List<String> = emptyList(),
    val collectedAtMillis: Long = System.currentTimeMillis(),
) {
    val anyFlag: Boolean get() = rooted || emulator || debugger || !signatureValid || hooked

    /**
     * Compact header value, stable field order:
     *   v=1;root=0;emu=1;dbg=0;sig=1;hook=0;ts=1731350000000
     * sig=1 means the signature is VALID (unlike the others, where 1 is bad).
     */
    fun toHeader(): String = listOf(
        "v=1",
        "root=${rooted.bit()}",
        "emu=${emulator.bit()}",
        "dbg=${debugger.bit()}",
        "sig=${signatureValid.bit()}",
        "hook=${hooked.bit()}",
        "ts=$collectedAtMillis",
    ).joinToString(";")

    fun toJson(): String {
        val d = details.joinToString(",") { "\"" + it.jsonEscape() + "\"" }
        return "{\"rooted\":$rooted,\"emulator\":$emulator,\"debugger\":$debugger," +
            "\"signatureValid\":$signatureValid,\"hooked\":$hooked," +
            "\"details\":[$d],\"collectedAtMillis\":$collectedAtMillis}"
    }

    companion object {
        const val HEADER = "X-RASP"

        fun parseHeader(value: String): RaspReport? {
            val m = value.split(";").mapNotNull {
                val i = it.indexOf('='); if (i <= 0) null else it.substring(0, i) to it.substring(i + 1)
            }.toMap()
            if (m["v"] != "1") return null
            fun b(k: String) = m[k] == "1"
            return RaspReport(
                rooted = b("root"), emulator = b("emu"), debugger = b("dbg"),
                signatureValid = b("sig"), hooked = b("hook"),
                collectedAtMillis = m["ts"]?.toLongOrNull() ?: 0L,
            )
        }
    }
}

private fun Boolean.bit() = if (this) "1" else "0"

internal fun String.jsonEscape(): String = buildString {
    for (c in this@jsonEscape) when (c) {
        '"' -> append("\\\"")
        '\\' -> append("\\\\")
        '\n' -> append("\\n")
        '\r' -> append("\\r")
        '\t' -> append("\\t")
        else -> if (c < ' ') append(String.format("\\u%04x", c.code)) else append(c)
    }
}
