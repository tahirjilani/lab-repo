package com.demo.wallet

import com.demo.wallet.rasp.RaspReport
import com.demo.wallet.transfer.Transfer

// Plain models shared by WalletApi and the backends. No Android types, so the
// mock backend and these models can be unit-tested on the JVM.

/**
 * Either a Play Integrity token or the reason there isn't one.
 * Both go to the server: a missing token is evidence too, never a silent pass.
 */
data class IntegrityResult(val token: String?, val error: String?) {
    companion object {
        fun ok(token: String) = IntegrityResult(token, null)
        fun failed(reason: String) = IntegrityResult(null, reason)
    }
}

enum class Decision(val wire: String) {
    ALLOW("allow"), MONITOR("monitor"), STEP_UP("step_up"), BLOCK("block");

    companion object {
        fun from(wire: String): Decision = entries.firstOrNull { it.wire == wire } ?: BLOCK
    }
}

data class Session(val token: String, val account: String, val displayName: String)
data class Challenge(val id: String, val nonce: String)

data class TransferOutcome(
    val decision: Decision,
    val transferId: String,
    val reason: String,
    val challenge: Challenge? = null,
    val balanceCents: Long? = null,
    /** Hash of the canonical transfer; the step-up signature covers it. Filled in by WalletApi. */
    val requestHash: String = "",
)

/** Everything the server gets for one transfer attempt. */
data class TransferRequest(
    val transfer: Transfer,
    val rasp: RaspReport,
    /** null when the Lab 2 feature flag is off: the field is omitted from the body. */
    val integrity: IntegrityResult?,
)
