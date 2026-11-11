package com.demo.wallet.backend

import com.demo.wallet.Challenge
import com.demo.wallet.Decision
import com.demo.wallet.Session
import com.demo.wallet.TransferOutcome
import com.demo.wallet.TransferRequest
import com.demo.wallet.rasp.RaspReport
import com.demo.wallet.transfer.Actor
import com.demo.wallet.transfer.Payees
import com.demo.wallet.transfer.Transfer
import com.demo.wallet.transfer.formatEuros
import java.security.KeyFactory
import java.security.PublicKey
import java.security.SecureRandom
import java.security.Signature
import java.security.spec.X509EncodedKeySpec
import java.util.Base64
import java.util.UUID

/**
 * In-process stand-in for server/ so the app runs on an emulator with no backend
 * (gradle property demowallet.apiBaseUrl=mock, the default until step 3 lands).
 *
 * The rules below are a placeholder risk engine — simple, readable, and NOT the
 * lab's real logic. They exist so every screen can be reached on stage:
 *   - amount above balance               -> block
 *   - Lab 2 on and no integrity token     -> step_up  (missing verdict: step up, never block)
 *   - hook / bad signature / debugger     -> step_up
 *   - assistant above the agent limit     -> step_up  (deck slide 18, limit still TBD)
 *   - user above the user limit           -> step_up
 *   - root or emulator only               -> monitor
 *   - otherwise                           -> allow
 * Integrity tokens are NOT decoded here (that needs Google's API on a server); a
 * present token is accepted as-is, which is exactly why this is only a mock.
 */
class MockBackend(startingBalanceCents: Long = 245_000) : Backend {

    private data class Pending(val transfer: Transfer, val challenge: Challenge)

    private val lock = Any()
    private var balance = startingBalanceCents
    private var devicePublicKey: PublicKey? = null
    private val pending = mutableMapOf<String, Pending>()
    private val random = SecureRandom()

    override fun login(username: String, password: String, devicePublicKey: String, rasp: RaspReport): Session {
        if (username.isBlank() || password.isBlank()) throw BackendException("Enter any username and password.", 400)
        this.devicePublicKey = runCatching { parseKey(devicePublicKey) }.getOrNull()
        return Session(token = UUID.randomUUID().toString(), account = "acc-001", displayName = username.trim())
    }

    override fun balance(session: Session, rasp: RaspReport): Long = synchronized(lock) { balance }

    override fun submitTransfer(session: Session, request: TransferRequest): TransferOutcome = synchronized(lock) {
        val t = request.transfer
        val id = "tx-" + UUID.randomUUID().toString().take(8)
        val payee = Payees.all.firstOrNull { it.id == t.payeeId }
            ?: return TransferOutcome(Decision.BLOCK, id, "Unknown payee ${t.payeeId}.")
        if (t.amountCents > balance) {
            return TransferOutcome(Decision.BLOCK, id, "Insufficient funds for ${formatEuros(t.amountCents)}.")
        }

        val r = request.rasp
        val i = request.integrity
        val stepUpReason = when {
            i != null && i.token == null -> "No integrity verdict (${i.error?.substringBefore(':') ?: "unknown"})."
            r.hooked -> "Instrumentation detected on the device."
            !r.signatureValid -> "App signature doesn't match."
            r.debugger -> "Debugger attached."
            t.actor == Actor.ASSISTANT && t.amountCents > AGENT_LIMIT_CENTS ->
                "Assistant transfers above ${formatEuros(AGENT_LIMIT_CENTS)} need your confirmation."
            t.actor == Actor.USER && t.amountCents > USER_LIMIT_CENTS ->
                "Transfers above ${formatEuros(USER_LIMIT_CENTS)} need confirmation."
            else -> null
        }
        if (stepUpReason != null) {
            val challenge = Challenge(id = "ch-" + UUID.randomUUID().toString().take(8), nonce = hex(16))
            pending[id] = Pending(t, challenge)
            return TransferOutcome(Decision.STEP_UP, id, stepUpReason, challenge)
        }

        balance -= t.amountCents
        val decision = if (r.rooted || r.emulator) Decision.MONITOR else Decision.ALLOW
        val note = if (decision == Decision.MONITOR) " (logged for review: ${monitorWhy(r)})" else ""
        TransferOutcome(decision, id, "Sent ${formatEuros(t.amountCents)} to ${payee.name}$note.", balanceCents = balance)
    }

    override fun confirm(
        session: Session, transferId: String, challengeId: String, signatureB64: String,
        actor: Actor, rasp: RaspReport,
    ): TransferOutcome = synchronized(lock) {
        val p = pending.remove(transferId)
            ?: return TransferOutcome(Decision.BLOCK, transferId, "No pending confirmation for this transfer.")
        if (p.challenge.id != challengeId) return TransferOutcome(Decision.BLOCK, transferId, "Challenge mismatch.")

        val key = devicePublicKey ?: return TransferOutcome(Decision.BLOCK, transferId, "No device key registered.")
        val message = "stepup|v1|${p.challenge.id}|${p.challenge.nonce}|${p.transfer.requestHash()}"
        val valid = runCatching {
            Signature.getInstance("SHA256withECDSA").run {
                initVerify(key)
                update(message.toByteArray(Charsets.UTF_8))
                verify(Base64.getDecoder().decode(signatureB64))
            }
        }.getOrDefault(false)
        if (!valid) return TransferOutcome(Decision.BLOCK, transferId, "Confirmation signature invalid.")

        if (p.transfer.amountCents > balance) return TransferOutcome(Decision.BLOCK, transferId, "Insufficient funds.")
        balance -= p.transfer.amountCents
        val payee = Payees.all.first { it.id == p.transfer.payeeId }
        TransferOutcome(
            Decision.ALLOW, transferId,
            "Confirmed. Sent ${formatEuros(p.transfer.amountCents)} to ${payee.name}.",
            balanceCents = balance,
        )
    }

    private fun monitorWhy(r: RaspReport) = listOfNotNull(
        "rooted".takeIf { r.rooted }, "emulator".takeIf { r.emulator },
    ).joinToString(", ")

    private fun parseKey(b64: String): PublicKey =
        KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(Base64.getDecoder().decode(b64)))

    private fun hex(n: Int) = ByteArray(n).also(random::nextBytes).joinToString("") { "%02x".format(it) }

    companion object {
        /** Placeholder for the deck's "agent limit [€__]" (slide 18). */
        const val AGENT_LIMIT_CENTS = 10_000L   // €100
        const val USER_LIMIT_CENTS = 100_000L   // €1,000
    }
}
