package com.demo.wallet.backend

import com.demo.wallet.AgentGrant
import com.demo.wallet.Session
import com.demo.wallet.TransferOutcome
import com.demo.wallet.TransferRequest
import com.demo.wallet.rasp.RaspReport
import com.demo.wallet.transfer.Actor

/**
 * Wire contract shared with server/ (step 3). All bodies are JSON, all requests
 * except login carry `Authorization: Bearer <sessionToken>`, and ALL requests carry
 * `X-RASP: v=1;root=..;emu=..;dbg=..;sig=..;hook=..;ts=..` and `X-Actor: user|assistant`
 * (plus `X-Agent-Id` when the actor is the assistant).
 *
 * POST /api/login            {username, password, devicePublicKey}
 *                            -> {sessionToken, account, displayName}
 * GET  /api/balance          -> {account, balanceCents, currency}
 * POST /api/transfers        {transfer:{account,payeeId,amountCents,currency,nonce,actor},
 *                             clientRequestHash, rasp:{...}, integrity?:{token,error}}
 *                            -> {decision, transferId, reason, challenge?:{id,nonce}, balanceCents?}
 * POST /api/transfers/{id}/confirm {challengeId, signature}
 *                            -> {decision, transferId, reason, balanceCents?}
 * POST /api/agent-tokens     {agentId, action, maxAmountCents, payeeId?, ttlSeconds?, currency?}
 *                            (X-Actor: user only — an agent can't delegate to itself)
 *                            -> {agentToken, jti, agentId, action, maxAmountCents, payeeId,
 *                                issuedAt, expiresAt}
 * Assistant transfers carry the granted token as `X-Agent-Token`. Without one, the
 * server steps up every assistant transfer ("no delegation").
 *
 * decision ∈ allow | monitor | step_up | block.
 * `integrity` is absent when the Lab 2 flag is off. clientRequestHash is for logs
 * only: the server recomputes the hash from `transfer` (canonical v1 form).
 * Step-up signature: base64 DER ECDSA-P256-SHA256 over
 *   stepup|v1|<challengeId>|<challengeNonce>|<requestHash>
 * with the devicePublicKey (base64 X.509 SubjectPublicKeyInfo) sent at login.
 */
interface Backend {
    fun login(username: String, password: String, devicePublicKey: String, rasp: RaspReport): Session
    fun balance(session: Session, rasp: RaspReport): Long
    fun submitTransfer(session: Session, request: TransferRequest): TransferOutcome

    /** The user grants [agentId] one transfer to [payeeId] of at most [maxAmountCents]. Always sent as X-Actor: user. */
    fun mintAgentToken(
        session: Session,
        agentId: String,
        payeeId: String,
        maxAmountCents: Long,
        ttlSeconds: Int,
        rasp: RaspReport,
    ): AgentGrant

    fun confirm(
        session: Session,
        transferId: String,
        challengeId: String,
        signatureB64: String,
        actor: Actor,
        rasp: RaspReport,
    ): TransferOutcome
}

class BackendException(message: String, val status: Int = 0) : Exception(message)
