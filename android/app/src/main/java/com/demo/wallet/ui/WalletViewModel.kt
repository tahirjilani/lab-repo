package com.demo.wallet.ui

import android.app.Application
import android.util.Base64
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.demo.wallet.AgentGrant
import com.demo.wallet.Decision
import com.demo.wallet.Guard
import com.demo.wallet.TransferOutcome
import com.demo.wallet.WalletApi
import com.demo.wallet.assistant.AssistantIntent
import com.demo.wallet.assistant.IntentParser
import com.demo.wallet.auth.DeviceKey
import com.demo.wallet.rasp.RaspReport
import com.demo.wallet.transfer.Actor
import com.demo.wallet.transfer.Payee
import com.demo.wallet.transfer.Payees
import com.demo.wallet.transfer.formatEuros
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.security.Signature
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

enum class Speaker { USER, ASSISTANT, TOOL, GRANT }
data class ChatMessage(val from: Speaker, val text: String)

/** A transfer the server wants the user to confirm. Everything shown on the step-up screen. */
data class PendingStepUp(
    val transferId: String,
    val challengeId: String,
    val challengeNonce: String,
    val requestHash: String,
    val payee: Payee,
    val amountCents: Long,
    val actor: Actor,
    val reason: String,
) {
    /** The action as a sentence, e.g. "Send €200.00 to Ana". */
    val actionLabel: String get() = "Send ${formatEuros(amountCents)} to ${payee.name}"
}

/**
 * The assistant wants to act: what the user is asked to delegate before it does.
 * [scopeCents] is what the token will cover: the requested amount, capped at the agent limit.
 */
data class GrantRequest(val payee: Payee, val amountCents: Long, val scopeCents: Long, val limitCents: Long) {
    val exceedsLimit: Boolean get() = amountCents > scopeCents
}

sealed interface Screen {
    data object RootBlocked : Screen
    data object SignIn : Screen
    data object Home : Screen
    data class Confirm(val pending: PendingStepUp) : Screen
}

data class UiState(
    val screen: Screen = Screen.SignIn,
    val busy: Boolean = false,
    val error: String? = null,
    val displayName: String = "",
    val balanceCents: Long? = null,
    val rasp: RaspReport? = null,
    val deviceKeyProblem: String? = null,
    val messages: List<ChatMessage> = listOf(
        ChatMessage(Speaker.ASSISTANT, "Hi! I can send money for you. Try “Send €200 to Ana”.")
    ),
    val integrityBinding: Boolean = false,
    val backendLabel: String = "",
    /** Non-null while the consent card is showing. */
    val pendingGrant: GrantRequest? = null,
)

class WalletViewModel(app: Application) : AndroidViewModel(app) {

    private val api = WalletApi(app)
    private val _state = MutableStateFlow(
        UiState(
            integrityBinding = api.integrityBindingEnabled,
            backendLabel = com.demo.wallet.BuildConfig.API_BASE_URL,
        )
    )
    val state: StateFlow<UiState> = _state.asStateFlow()

    init {
        checkDevice()
    }

    /** The local gate Lab 1 bypasses: one call to Guard.isRooted(). */
    fun checkDevice() {
        viewModelScope.launch {
            val (rooted, report) = withContext(Dispatchers.IO) { Guard.isRooted() to api.rasp() }
            _state.update {
                it.copy(
                    rasp = report,
                    screen = when {
                        rooted -> Screen.RootBlocked
                        it.screen == Screen.RootBlocked -> Screen.SignIn
                        else -> it.screen
                    },
                )
            }
        }
    }

    fun signIn(username: String, password: String) {
        if (_state.value.busy) return
        _state.update { it.copy(busy = true, error = null) }
        viewModelScope.launch {
            try {
                val (publicKey, keyProblem) = withContext(Dispatchers.IO) {
                    try {
                        DeviceKey.ensure() to null
                    } catch (e: Exception) {
                        "" to "Couldn't create the confirmation key (${e.javaClass.simpleName}). " +
                            "Set a screen lock and enroll a fingerprint in the emulator's Settings, then sign in again."
                    }
                }
                val session = api.signIn(username, password, publicKey)
                val balance = api.balanceCents()
                _state.update {
                    it.copy(
                        busy = false, screen = Screen.Home, displayName = session.displayName,
                        balanceCents = balance, deviceKeyProblem = keyProblem, rasp = api.rasp(),
                    )
                }
            } catch (e: Exception) {
                _state.update { it.copy(busy = false, error = e.message ?: e.javaClass.simpleName) }
            }
        }
    }

    fun signOut() {
        api.signOut()
        _state.update { UiState(integrityBinding = it.integrityBinding, backendLabel = it.backendLabel, rasp = it.rasp) }
        checkDevice()
    }

    fun clearError() = _state.update { it.copy(error = null) }

    // ── Assistant ──────────────────────────────────────────────────────────────

    fun ask(text: String) {
        val trimmed = text.trim()
        if (trimmed.isEmpty() || _state.value.busy || _state.value.pendingGrant != null) return
        say(Speaker.USER, trimmed)
        when (val intent = IntentParser.parse(trimmed)) {
            is AssistantIntent.SendMoney -> {
                val payee = Payees.byName(intent.payeeName)
                if (payee == null) {
                    val known = Payees.all.joinToString(", ") { it.name }
                    say(Speaker.ASSISTANT, "I don't have ${intent.payeeName} in your contacts. I can send to $known.")
                } else {
                    requestGrant(payee, intent.amountCents)
                }
            }
            AssistantIntent.CheckBalance -> refreshBalance(announce = true)
            is AssistantIntent.NeedsMoreInfo -> say(Speaker.ASSISTANT, intent.question)
            AssistantIntent.Unknown -> say(Speaker.ASSISTANT, "I can send money or check your balance. Try “Send €200 to Ana”.")
        }
    }

    // ── Agent identity: the user delegates before the assistant acts ──────────────

    private fun requestGrant(payee: Payee, amountCents: Long) {
        val limit = api.agentLimitCents
        val scope = minOf(amountCents, limit)
        say(Speaker.TOOL, "request_delegation(agent=\"${WalletApi.ASSISTANT_AGENT_ID}\", action=\"transfer\", " +
            "payee=\"${payee.id}\", maxAmountCents=$scope)")
        say(Speaker.ASSISTANT, "I need your permission to send ${formatEuros(amountCents)} to ${payee.name}.")
        _state.update { it.copy(pendingGrant = GrantRequest(payee, amountCents, scope, limit)) }
    }

    /** User tapped Allow: mint the scoped token (X-Actor: user), show it, then let the assistant act with it. */
    fun approveGrant() {
        val req = _state.value.pendingGrant ?: return
        if (_state.value.busy) return
        _state.update { it.copy(pendingGrant = null, busy = true) }
        viewModelScope.launch {
            val grant = try {
                api.grantAssistant(req.payee.id, req.scopeCents)
            } catch (e: Exception) {
                _state.update { it.copy(busy = false) }
                say(Speaker.ASSISTANT, "I couldn't get a delegation: ${e.message ?: e.javaClass.simpleName}. Nothing was sent.")
                return@launch
            }
            _state.update { it.copy(busy = false) }
            say(Speaker.GRANT, describe(grant, req.payee))
            say(Speaker.TOOL, "transfer(payee=\"${req.payee.id}\", amountCents=${req.amountCents}, actor=\"assistant\") " +
                "X-Agent-Token: ${grant.token.take(14)}…")
            send(req.payee, req.amountCents, Actor.ASSISTANT, grant.token)
        }
    }

    fun denyGrant() {
        if (_state.value.pendingGrant == null) return
        _state.update { it.copy(pendingGrant = null) }
        say(Speaker.ASSISTANT, "OK. Without your permission I won't send anything.")
    }

    private fun describe(g: AgentGrant, payee: Payee): String {
        val expires = TIME.format(Instant.ofEpochSecond(g.expiresAtSeconds).atZone(ZoneId.systemDefault()))
        val to = if (g.payeeId == null) "anyone" else payee.name
        return "You granted ${g.agentId}: ${g.action} up to ${formatEuros(g.maxAmountCents)} to $to · single use · " +
            "expires $expires · jti ${g.jti}"
    }

    /** Manual transfer from the Send dialog: same API, actor = user. */
    fun sendManual(payee: Payee, amountCents: Long) {
        say(Speaker.USER, "(manual) Send ${formatEuros(amountCents)} to ${payee.name}")
        send(payee, amountCents, Actor.USER)
    }

    private fun send(payee: Payee, amountCents: Long, actor: Actor, agentToken: String? = null) {
        // Local root gate, re-checked before every transfer. Lab 1's hook makes this false.
        if (Guard.isRooted()) {
            say(Speaker.ASSISTANT, "I can't send money from a rooted device.")
            _state.update { it.copy(screen = Screen.RootBlocked) }
            return
        }
        _state.update { it.copy(busy = true) }
        viewModelScope.launch {
            try {
                val outcome = api.sendTransfer(payee.id, amountCents, actor, agentToken)
                handleOutcome(outcome, payee, amountCents, actor)
            } catch (e: Exception) {
                say(Speaker.ASSISTANT, "That didn't go through: ${e.message ?: e.javaClass.simpleName}")
            } finally {
                _state.update { it.copy(busy = false, rasp = api.rasp()) }
            }
        }
    }

    private fun handleOutcome(o: TransferOutcome, payee: Payee, amountCents: Long, actor: Actor) {
        when (o.decision) {
            Decision.ALLOW, Decision.MONITOR -> {
                say(Speaker.ASSISTANT, "Done. ${o.reason}")
                o.balanceCents?.let { b -> _state.update { it.copy(balanceCents = b) } }
            }
            Decision.STEP_UP -> {
                val ch = o.challenge
                if (ch == null) {
                    say(Speaker.ASSISTANT, "The server asked for confirmation but sent no challenge. Nothing was sent.")
                    return
                }
                say(Speaker.ASSISTANT, "I need you to confirm this one: ${o.reason}")
                val pending = PendingStepUp(
                    transferId = o.transferId, challengeId = ch.id, challengeNonce = ch.nonce,
                    requestHash = o.requestHash, payee = payee, amountCents = amountCents,
                    actor = actor, reason = o.reason,
                )
                _state.update { it.copy(screen = Screen.Confirm(pending)) }
            }
            Decision.BLOCK -> say(Speaker.ASSISTANT, "Blocked by the bank: ${o.reason}")
        }
    }

    // ── Step-up ────────────────────────────────────────────────────────────────

    /** Bytes the biometric-unlocked key must sign for this pending transfer. */
    fun stepUpMessage(p: PendingStepUp): ByteArray =
        DeviceKey.stepUpMessage(p.challengeId, p.challengeNonce, p.requestHash)

    /** Called with the Signature that BiometricPrompt unlocked. */
    fun completeStepUp(p: PendingStepUp, unlocked: Signature) {
        _state.update { it.copy(busy = true) }
        viewModelScope.launch {
            try {
                val sig = withContext(Dispatchers.Default) {
                    unlocked.update(stepUpMessage(p))
                    Base64.encodeToString(unlocked.sign(), Base64.NO_WRAP)
                }
                val outcome = api.confirmStepUp(p.transferId, p.challengeId, sig, p.actor)
                _state.update { it.copy(screen = Screen.Home) }
                when (outcome.decision) {
                    Decision.ALLOW, Decision.MONITOR -> {
                        say(Speaker.ASSISTANT, outcome.reason)
                        outcome.balanceCents?.let { b -> _state.update { it.copy(balanceCents = b) } }
                    }
                    Decision.STEP_UP -> say(Speaker.ASSISTANT, "Still needs confirmation: ${outcome.reason}")
                    Decision.BLOCK -> say(Speaker.ASSISTANT, "Blocked by the bank: ${outcome.reason}")
                }
            } catch (e: Exception) {
                _state.update { it.copy(screen = Screen.Home) }
                say(Speaker.ASSISTANT, "Confirmation failed: ${e.message ?: e.javaClass.simpleName}. Nothing was sent.")
            } finally {
                _state.update { it.copy(busy = false) }
            }
        }
    }

    fun cancelStepUp(reason: String = "Cancelled. Nothing was sent.") {
        _state.update { it.copy(screen = Screen.Home) }
        say(Speaker.ASSISTANT, reason)
    }

    fun refreshBalance(announce: Boolean = false) {
        viewModelScope.launch {
            try {
                val b = api.balanceCents()
                _state.update { it.copy(balanceCents = b, rasp = api.rasp()) }
                if (announce) say(Speaker.ASSISTANT, "Your balance is ${formatEuros(b)}.")
            } catch (e: Exception) {
                if (announce) say(Speaker.ASSISTANT, "I couldn't get your balance: ${e.message}")
            }
        }
    }

    private fun say(from: Speaker, text: String) =
        _state.update { it.copy(messages = it.messages + ChatMessage(from, text)) }

    private companion object {
        val TIME: DateTimeFormatter = DateTimeFormatter.ofPattern("HH:mm:ss")
    }
}
