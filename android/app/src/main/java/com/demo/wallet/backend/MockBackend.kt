package com.demo.wallet.backend

import com.demo.wallet.AgentGrant
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
 * In-process stand-in for server/ so the app runs without the lab server
 * (gradle property demowallet.apiBaseUrl=mock; the branches default to the server).
 *
 * The rules below are a placeholder risk engine — simple, readable, and NOT the
 * lab's real logic. They exist so every screen can be reached without Python:
 *   - unknown payee / amount above balance          -> block
 *   - assistant with a token this mock never issued -> block    (server: forged token)
 *   - Lab 2 on and no integrity token               -> step_up  (missing verdict: step up, never block)
 *   - hook / bad signature / debugger               -> step_up
 *   - assistant without a granted token             -> step_up  (server: no_delegation)
 *   - assistant token expired / used / out of scope -> step_up  (scope = payee + amount ≤ grant)
 *   - user above the user limit                     -> step_up
 *   - root or emulator only                         -> monitor
 *   - otherwise                                     -> allow
 * Agent tokens follow the server's rules (user-only, capped at [agentLimitCents], single use,
 * short-lived) but are opaque ids, not HMAC-signed. Integrity tokens are NOT decoded here
 * (that needs Google's API on a server); a present token is accepted as-is.
 */
class MockBackend(
    startingBalanceCents: Long = 245_000,
    /** Deck slide 18's agent limit; WalletApi passes BuildConfig.AGENT_LIMIT_CENTS. */
    private val agentLimitCents: Long = DEFAULT_AGENT_LIMIT_CENTS,
    private val nowSeconds: () -> Long = { System.currentTimeMillis() / 1000 },
) : Backend {

    private data class Pending(val transfer: Transfer, val challenge: Challenge)

    private val lock = Any()
    private var balance = startingBalanceCents
    private var devicePublicKey: PublicKey? = null
    private val pending = mutableMapOf<String, Pending>()
    private val grants = mutableMapOf<String, AgentGrant>()
    private val usedGrants = mutableSetOf<String>()
    private val random = SecureRandom()

    override fun login(username: String, password: String, devicePublicKey: String, rasp: RaspReport): Session {
        if (username.isBlank() || password.isBlank()) throw BackendException("Enter any username and password.", 400)
        this.devicePublicKey = runCatching { parseKey(devicePublicKey) }.getOrNull()
        return Session(token = UUID.randomUUID().toString(), account = "acc-001", displayName = username.trim())
    }

    override fun balance(session: Session, rasp: RaspReport): Long = synchronized(lock) { balance }

    override fun mintAgentToken(
        session: Session, agentId: String, payeeId: String, maxAmountCents: Long, ttlSeconds: Int,
        rasp: RaspReport,
    ): AgentGrant = synchronized(lock) {
        if (maxAmountCents !in 1..agentLimitCents) {
            throw BackendException("maxAmountCents must be between 1 and the agent limit ($agentLimitCents)", 400)
        }
        if (ttlSeconds !in 1..MAX_TTL_SECONDS) {
            throw BackendException("ttlSeconds must be between 1 and $MAX_TTL_SECONDS", 400)
        }
        val now = nowSeconds()
        val jti = hex(8)
        val grant = AgentGrant(
            token = "mock-agent.$jti", jti = jti, agentId = agentId, action = "transfer",
            maxAmountCents = maxAmountCents, payeeId = payeeId,
            issuedAtSeconds = now, expiresAtSeconds = now + ttlSeconds,
        )
        grants[grant.token] = grant
        grant
    }

    override fun submitTransfer(session: Session, request: TransferRequest): TransferOutcome = synchronized(lock) {
        val t = request.transfer
        val id = "tx-" + UUID.randomUUID().toString().take(8)
        val payee = Payees.all.firstOrNull { it.id == t.payeeId }
            ?: return TransferOutcome(Decision.BLOCK, id, "Unknown payee ${t.payeeId}.")
        if (t.amountCents > balance) {
            return TransferOutcome(Decision.BLOCK, id, "Insufficient funds for ${formatEuros(t.amountCents)}.")
        }

        // Agent layer: does a grant the user made cover this assistant transfer?
        var inScope: AgentGrant? = null
        var agentReason: String? = null
        if (t.actor == Actor.ASSISTANT) {
            val token = request.agentToken
            val g = token?.let { grants[it] }
            when {
                token == null -> agentReason = "The assistant has no delegation token for this."
                g == null -> return TransferOutcome(Decision.BLOCK, id, "Agent token is not valid.")
                nowSeconds() >= g.expiresAtSeconds -> agentReason = "Agent token has expired."
                g.jti in usedGrants -> agentReason = "Agent token was already used."
                g.payeeId != null && g.payeeId != t.payeeId ->
                    agentReason = "Outside the assistant's delegation: token is limited to payee ${g.payeeId}."
                t.amountCents > g.maxAmountCents ->
                    agentReason = "Outside the assistant's delegation: ${formatEuros(t.amountCents)} " +
                        "exceeds the delegated ${formatEuros(g.maxAmountCents)}."
                else -> inScope = g
            }
        }

        val r = request.rasp
        val i = request.integrity
        val stepUpReason = when {
            i != null && i.token == null -> "No integrity verdict (${i.error?.substringBefore(':') ?: "unknown"})."
            r.hooked -> "Instrumentation detected on the device."
            !r.signatureValid -> "App signature doesn't match."
            r.debugger -> "Debugger attached."
            agentReason != null -> agentReason
            t.actor == Actor.USER && t.amountCents > USER_LIMIT_CENTS ->
                "Transfers above ${formatEuros(USER_LIMIT_CENTS)} need confirmation."
            else -> null
        }
        // Like the server: an in-scope token is spent once the transfer isn't blocked.
        inScope?.let { usedGrants += it.jti }

        if (stepUpReason != null) {
            val challenge = Challenge(id = "ch-" + UUID.randomUUID().toString().take(8), nonce = hex(16))
            pending[id] = Pending(t, challenge)
            return TransferOutcome(Decision.STEP_UP, id, stepUpReason, challenge)
        }

        balance -= t.amountCents
        val decision = if (r.rooted || r.emulator) Decision.MONITOR else Decision.ALLOW
        val notes = listOfNotNull(
            inScope?.let { "assistant within its delegation of ${formatEuros(it.maxAmountCents)}" },
            if (decision == Decision.MONITOR) "logged for review: ${monitorWhy(r)}" else null,
        )
        val note = if (notes.isEmpty()) "" else " (${notes.joinToString("; ")})"
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
        /** Default for the deck's "agent limit" (slide 18): €100. Same as the server's DW_AGENT_LIMIT_CENTS. */
        const val DEFAULT_AGENT_LIMIT_CENTS = 10_000L
        const val USER_LIMIT_CENTS = 100_000L   // €1,000
        const val MAX_TTL_SECONDS = 600
    }
}
