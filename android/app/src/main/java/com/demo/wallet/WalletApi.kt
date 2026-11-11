package com.demo.wallet

import android.content.Context
import com.demo.wallet.backend.Backend
import com.demo.wallet.backend.HttpBackend
import com.demo.wallet.backend.MockBackend
import com.demo.wallet.integrity.IntegrityTokens
import com.demo.wallet.rasp.Rasp
import com.demo.wallet.rasp.RaspReport
import com.demo.wallet.transfer.Actor
import com.demo.wallet.transfer.Transfer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.security.SecureRandom

/**
 * The one door to the backend. Every request carries the RASP flags (header X-RASP)
 * and the actor (header X-Actor); transfers also carry the full report in the body.
 *
 * ── Lab 2 ────────────────────────────────────────────────────────────────────
 * With BuildConfig.INTEGRITY_BINDING on (gradle property demowallet.integrityBinding,
 * false on lab1-start, true on lab2-start), each transfer is hashed
 * (Transfer.requestHash()) and a Play Integrity standard token is requested FOR THAT
 * HASH. The server decodes the token, recomputes the hash from the body and checks
 * they match, so a token can't be lifted onto a different transfer. If no token can
 * be obtained, the error is sent instead and the server steps up — it never blocks
 * on a missing verdict alone.
 * ─────────────────────────────────────────────────────────────────────────────
 */
class WalletApi(context: Context) {
    private val appContext = context.applicationContext
    private val integrity = IntegrityTokens(appContext)
    private val random = SecureRandom()

    val backend: Backend =
        if (BuildConfig.API_BASE_URL == "mock") MockBackend() else HttpBackend(BuildConfig.API_BASE_URL)

    val integrityBindingEnabled: Boolean get() = BuildConfig.INTEGRITY_BINDING

    var session: Session? = null
        private set

    fun rasp(): RaspReport = Rasp.collect(appContext)

    suspend fun signIn(username: String, password: String, devicePublicKey: String): Session =
        withContext(Dispatchers.IO) {
            backend.login(username, password, devicePublicKey, rasp()).also { s ->
                session = s
                if (integrityBindingEnabled) integrity.prepare() // warm-up; result is reported per transfer
            }
        }

    suspend fun balanceCents(): Long = withContext(Dispatchers.IO) {
        backend.balance(requireSession(), rasp())
    }

    suspend fun sendTransfer(payeeId: String, amountCents: Long, actor: Actor): TransferOutcome =
        withContext(Dispatchers.IO) {
            val s = requireSession()
            val transfer = Transfer(
                account = s.account,
                payeeId = payeeId,
                amountCents = amountCents,
                nonce = newNonce(),
                actor = actor,
            )

            // ── Lab 2: bind a Play Integrity token to this exact transfer ──
            val integrityResult: IntegrityResult? =
                if (integrityBindingEnabled) integrity.tokenFor(transfer.requestHash()) else null

            backend.submitTransfer(s, TransferRequest(transfer, rasp(), integrityResult))
                .copy(requestHash = transfer.requestHash())
        }

    suspend fun confirmStepUp(transferId: String, challengeId: String, signatureB64: String, actor: Actor): TransferOutcome =
        withContext(Dispatchers.IO) {
            backend.confirm(requireSession(), transferId, challengeId, signatureB64, actor, rasp())
        }

    fun signOut() {
        session = null
    }

    private fun requireSession() = session ?: error("Not signed in")

    private fun newNonce(): String {
        val b = ByteArray(16).also(random::nextBytes)
        return b.joinToString("") { "%02x".format(it) }
    }

    companion object {
        const val HEADER_ACTOR = "X-Actor"
        const val HEADER_AGENT_ID = "X-Agent-Id"
        /** Identity the in-app assistant presents. A real deployment would sign this. */
        const val ASSISTANT_AGENT_ID = "demowallet-assistant/1.0"
    }
}
