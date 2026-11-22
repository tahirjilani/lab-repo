package com.demo.wallet.backend

import com.demo.wallet.AgentGrant
import com.demo.wallet.Challenge
import com.demo.wallet.Decision
import com.demo.wallet.Session
import com.demo.wallet.TransferOutcome
import com.demo.wallet.TransferRequest
import com.demo.wallet.WalletApi
import com.demo.wallet.rasp.RaspReport
import com.demo.wallet.transfer.Actor
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/** Talks to the lab verification server (server/, step 3). Blocking; call off the main thread. */
class HttpBackend(baseUrl: String) : Backend {
    private val base = baseUrl.trimEnd('/')

    override fun login(username: String, password: String, devicePublicKey: String, rasp: RaspReport): Session {
        val body = JSONObject()
            .put("username", username)
            .put("password", password)
            .put("devicePublicKey", devicePublicKey)
        val r = call("POST", "/api/login", null, Actor.USER, rasp, body)
        return Session(r.getString("sessionToken"), r.getString("account"), r.optString("displayName", username))
    }

    override fun balance(session: Session, rasp: RaspReport): Long =
        call("GET", "/api/balance", session, Actor.USER, rasp, null).getLong("balanceCents")

    override fun submitTransfer(session: Session, request: TransferRequest): TransferOutcome {
        val t = request.transfer
        val body = JSONObject()
            .put("transfer", JSONObject(t.toJson()))
            .put("clientRequestHash", t.requestHash())
            .put("rasp", JSONObject(request.rasp.toJson()))
        request.integrity?.let { i ->
            body.put("integrity", JSONObject()
                .put("token", i.token ?: JSONObject.NULL)
                .put("error", i.error ?: JSONObject.NULL))
        }
        val extra = request.agentToken?.let { mapOf(WalletApi.HEADER_AGENT_TOKEN to it) }.orEmpty()
        return outcome(call("POST", "/api/transfers", session, t.actor, request.rasp, body, extra))
    }

    override fun mintAgentToken(
        session: Session, agentId: String, payeeId: String, maxAmountCents: Long, ttlSeconds: Int,
        rasp: RaspReport,
    ): AgentGrant {
        val body = JSONObject()
            .put("agentId", agentId)
            .put("action", "transfer")
            .put("maxAmountCents", maxAmountCents)
            .put("payeeId", payeeId)
            .put("ttlSeconds", ttlSeconds)
            .put("currency", "EUR")
        // Always the user: the server refuses (403) a grant requested with X-Actor: assistant.
        val r = call("POST", "/api/agent-tokens", session, Actor.USER, rasp, body)
        return AgentGrant(
            token = r.getString("agentToken"),
            jti = r.optString("jti"),
            agentId = r.optString("agentId", agentId),
            action = r.optString("action", "transfer"),
            maxAmountCents = r.getLong("maxAmountCents"),
            payeeId = if (r.isNull("payeeId")) null else r.optString("payeeId"),
            issuedAtSeconds = r.optLong("issuedAt"),
            expiresAtSeconds = r.optLong("expiresAt"),
        )
    }

    override fun confirm(
        session: Session, transferId: String, challengeId: String, signatureB64: String,
        actor: Actor, rasp: RaspReport,
    ): TransferOutcome {
        val body = JSONObject().put("challengeId", challengeId).put("signature", signatureB64)
        return outcome(call("POST", "/api/transfers/$transferId/confirm", session, actor, rasp, body))
    }

    private fun outcome(r: JSONObject) = TransferOutcome(
        decision = Decision.from(r.getString("decision")),
        transferId = r.optString("transferId"),
        reason = r.optString("reason"),
        challenge = r.optJSONObject("challenge")?.let { Challenge(it.getString("id"), it.getString("nonce")) },
        balanceCents = if (r.has("balanceCents") && !r.isNull("balanceCents")) r.getLong("balanceCents") else null,
    )

    private fun call(
        method: String, path: String, session: Session?, actor: Actor, rasp: RaspReport, body: JSONObject?,
        extraHeaders: Map<String, String> = emptyMap(),
    ): JSONObject {
        val conn = (URL(base + path).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 5_000
            readTimeout = 15_000
            setRequestProperty("Accept", "application/json")
            setRequestProperty(RaspReport.HEADER, rasp.toHeader())
            setRequestProperty(WalletApi.HEADER_ACTOR, actor.wire)
            if (actor == Actor.ASSISTANT) setRequestProperty(WalletApi.HEADER_AGENT_ID, WalletApi.ASSISTANT_AGENT_ID)
            session?.let { setRequestProperty("Authorization", "Bearer ${it.token}") }
            extraHeaders.forEach { (k, v) -> setRequestProperty(k, v) }
            if (body != null) {
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
            }
        }
        try {
            body?.let { b -> conn.outputStream.use { it.write(b.toString().toByteArray(Charsets.UTF_8)) } }
            val status = conn.responseCode
            val stream = if (status in 200..299) conn.inputStream else conn.errorStream
            val text = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            if (status !in 200..299) {
                val msg = runCatching { JSONObject(text).optString("error", text) }.getOrDefault(text)
                throw BackendException("HTTP $status: ${msg.ifBlank { "no body" }}", status)
            }
            return if (text.isBlank()) JSONObject() else JSONObject(text)
        } catch (e: IOException) {
            throw BackendException("Can't reach $base (${e.javaClass.simpleName}). Is the lab server running?")
        } finally {
            conn.disconnect()
        }
    }
}
