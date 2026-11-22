package com.demo.wallet

import com.demo.wallet.assistant.AssistantIntent
import com.demo.wallet.assistant.IntentParser
import com.demo.wallet.backend.BackendException
import com.demo.wallet.backend.MockBackend
import com.demo.wallet.rasp.RaspReport
import com.demo.wallet.transfer.Actor
import com.demo.wallet.transfer.Transfer
import com.demo.wallet.transfer.formatEuros
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.security.KeyPairGenerator
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import java.util.Base64

class LogicTest {

    private fun send(text: String) = IntentParser.parse(text) as AssistantIntent.SendMoney

    @Test fun parsesTheDeckExample() {
        assertEquals(AssistantIntent.SendMoney("Ana", 20_000), IntentParser.parse("Send €200 to Ana"))
    }

    @Test fun parsesVariants() {
        assertEquals(20_000L, send("send 200 euros to ana").amountCents)
        assertEquals(1_250L, send("Transfer €12.50 to Ben").amountCents)
        assertEquals(1_250L, send("transfer 12,5€ to Ben").amountCents)
        assertEquals("Ana", send("Pay Ana €20").payeeName)
        assertEquals(2_000L, send("pay €20 to Ana please").amountCents)
        assertEquals("Chloé", send("send 5 eur to chloé").payeeName)
    }

    @Test fun asksWhenIncomplete() {
        assertTrue(IntentParser.parse("send money") is AssistantIntent.NeedsMoreInfo)
        assertEquals(AssistantIntent.CheckBalance, IntentParser.parse("What's my balance?"))
        assertEquals(AssistantIntent.Unknown, IntentParser.parse("hello"))
    }

    @Test fun canonicalFormIsStable() {
        val t = Transfer("acc-001", "ana", 20_000, "EUR", "00ff", Actor.ASSISTANT)
        assertEquals("v1|acc-001|ana|20000|EUR|00ff|assistant", t.canonical())
        // python3 -c "import hashlib;print(hashlib.sha256(b'v1|acc-001|ana|20000|EUR|00ff|assistant').hexdigest())"
        assertEquals("e71ee40ea59a74ba0232bcfbe5fa606d85704fb673068c4cfbc81e32a8b71ca8", t.requestHash())
    }

    @Test fun raspHeaderRoundTrips() {
        val r = RaspReport(rooted = false, emulator = true, debugger = false, signatureValid = true, hooked = true,
            collectedAtMillis = 42)
        assertEquals("v=1;root=0;emu=1;dbg=0;sig=1;hook=1;ts=42", r.toHeader())
        assertEquals(r.copy(details = emptyList()), RaspReport.parseHeader(r.toHeader()))
    }

    @Test fun formatsEuros() {
        assertEquals("€2,450.00", formatEuros(245_000))
        assertEquals("€0.05", formatEuros(5))
    }

    @Test fun mockStepUpVerifiesSignature() {
        val kp = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()
        val backend = MockBackend()
        val clean = RaspReport(false, false, false, true, false)
        val s = backend.login("t", "p", Base64.getEncoder().encodeToString(kp.public.encoded), clean)

        val t = Transfer(s.account, "ana", 20_000, nonce = "abc", actor = Actor.ASSISTANT)
        val o = backend.submitTransfer(s, TransferRequest(t, clean, null))
        assertEquals(Decision.STEP_UP, o.decision)
        val ch = o.challenge!!

        val msg = "stepup|v1|${ch.id}|${ch.nonce}|${t.requestHash()}".toByteArray()
        val sig = Signature.getInstance("SHA256withECDSA").run { initSign(kp.private); update(msg); sign() }
        val done = backend.confirm(s, o.transferId, ch.id, Base64.getEncoder().encodeToString(sig), Actor.ASSISTANT, clean)
        assertEquals(Decision.ALLOW, done.decision)
        assertEquals(225_000L, done.balanceCents)
    }

    // ── Agent tokens: MockBackend mirrors server/agent_tokens.py ──

    private val clean = RaspReport(false, false, false, true, false)

    private fun assistantTransfer(s: Session, cents: Long, payee: String = "ana", nonce: String = "n-$cents-$payee") =
        Transfer(s.account, payee, cents, nonce = nonce, actor = Actor.ASSISTANT)

    @Test fun assistantWithoutGrantStepsUp() {
        val b = MockBackend()
        val s = b.login("t", "p", "", clean)
        val o = b.submitTransfer(s, TransferRequest(assistantTransfer(s, 2_000), clean, null))
        assertEquals(Decision.STEP_UP, o.decision)
        assertTrue(o.reason, o.reason.contains("no delegation"))
    }

    @Test fun assistantWithinGrantGoesThroughOnce() {
        val b = MockBackend()
        val s = b.login("t", "p", "", clean)
        val g = b.mintAgentToken(s, WalletApi.ASSISTANT_AGENT_ID, "ana", 2_000, 300, clean)
        assertEquals(2_000L, g.maxAmountCents)
        val ok = b.submitTransfer(s, TransferRequest(assistantTransfer(s, 2_000), clean, null, g.token))
        assertEquals(Decision.ALLOW, ok.decision)
        assertEquals(243_000L, ok.balanceCents)
        // Single use: the same token can't move money twice.
        val again = b.submitTransfer(s, TransferRequest(assistantTransfer(s, 2_000, nonce = "n2"), clean, null, g.token))
        assertEquals(Decision.STEP_UP, again.decision)
        assertTrue(again.reason, again.reason.contains("already used"))
    }

    @Test fun grantIsCappedAtTheAgentLimitAndScoped() {
        val b = MockBackend(agentLimitCents = 10_000)
        val s = b.login("t", "p", "", clean)
        val tooBig = runCatching { b.mintAgentToken(s, WalletApi.ASSISTANT_AGENT_ID, "ana", 20_000, 300, clean) }
        assertTrue(tooBig.exceptionOrNull() is BackendException)

        // "Send €200 to Ana": the user can delegate at most €100, so the transfer steps up.
        val g = b.mintAgentToken(s, WalletApi.ASSISTANT_AGENT_ID, "ana", 10_000, 300, clean)
        val over = b.submitTransfer(s, TransferRequest(assistantTransfer(s, 20_000), clean, null, g.token))
        assertEquals(Decision.STEP_UP, over.decision)
        assertTrue(over.reason, over.reason.contains("exceeds the delegated €100.00"))

        val g2 = b.mintAgentToken(s, WalletApi.ASSISTANT_AGENT_ID, "ana", 2_000, 300, clean)
        val otherPayee = b.submitTransfer(s, TransferRequest(assistantTransfer(s, 2_000, payee = "ben"), clean, null, g2.token))
        assertEquals(Decision.STEP_UP, otherPayee.decision)
    }

    @Test fun expiredAndUnknownAgentTokens() {
        var now = 1_000L
        val b = MockBackend(nowSeconds = { now })
        val s = b.login("t", "p", "", clean)
        val g = b.mintAgentToken(s, WalletApi.ASSISTANT_AGENT_ID, "ana", 2_000, 60, clean)
        now += 60
        val expired = b.submitTransfer(s, TransferRequest(assistantTransfer(s, 2_000), clean, null, g.token))
        assertEquals(Decision.STEP_UP, expired.decision)
        val forged = b.submitTransfer(s, TransferRequest(assistantTransfer(s, 2_000, nonce = "f"), clean, null, "dwat1.x.y"))
        assertEquals(Decision.BLOCK, forged.decision)
    }

    @Test fun missingIntegrityTokenStepsUpNotBlocks() {
        val backend = MockBackend()
        val clean = RaspReport(false, false, false, true, false)
        val s = backend.login("t", "p", "", clean)
        val t = Transfer(s.account, "ben", 500, nonce = "n1", actor = Actor.USER)
        val o = backend.submitTransfer(s, TransferRequest(t, clean, IntegrityResult.failed("NOT_CONFIGURED")))
        assertEquals(Decision.STEP_UP, o.decision)
    }
}
