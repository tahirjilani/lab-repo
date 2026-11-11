package com.demo.wallet.assistant

/**
 * Stand-in for the LLM behind DemoWallet's assistant.
 *
 * The talk is about what happens AFTER a model decides to act, so the "model" here is
 * a deterministic parser: same input, same tool call, every time on stage. Swapping in
 * a real LLM changes nothing downstream — it would still have to produce the same
 * structured call (payee, amount) and go through WalletApi like everyone else.
 */
sealed interface AssistantIntent {
    data class SendMoney(val payeeName: String, val amountCents: Long) : AssistantIntent
    data object CheckBalance : AssistantIntent
    data class NeedsMoreInfo(val question: String) : AssistantIntent
    data object Unknown : AssistantIntent
}

object IntentParser {

    // €200 | 200€ | 200 € | 200 euros | 200 eur | EUR 200 | 12.50 | 12,50
    private const val AMOUNT =
        """(?:€\s*|eur\s+)?(\d{1,7}(?:[.,]\d{1,2})?)\s*(?:€|euros?|eur)?"""
    private const val NAME = """([a-zà-ÿ][a-zà-ÿ'\-]*)"""

    // "send|transfer|give|wire €200 to Ana"
    private val SEND_TO = Regex(
        """\b(?:send|transfer|give|wire|move)\s+$AMOUNT\s+to\s+$NAME""",
        RegexOption.IGNORE_CASE,
    )
    // "pay Ana €200" / "send Ana 200 euros"
    private val PAY_NAME_AMOUNT = Regex(
        """\b(?:pay|send|give)\s+$NAME\s+$AMOUNT""",
        RegexOption.IGNORE_CASE,
    )
    // "pay €200 to Ana"
    private val PAY_TO = Regex(
        """\bpay\s+$AMOUNT\s+to\s+$NAME""",
        RegexOption.IGNORE_CASE,
    )
    private val BALANCE = Regex("""\b(balance|how much (?:money )?(?:do )?i have)\b""", RegexOption.IGNORE_CASE)
    private val SEND_VERB = Regex("""\b(send|transfer|pay|give|wire)\b""", RegexOption.IGNORE_CASE)

    private val NOT_NAMES = setOf("me", "my", "the", "a", "an", "to", "money", "euros", "eur")

    fun parse(text: String): AssistantIntent {
        val t = text.trim()
        if (t.isEmpty()) return AssistantIntent.Unknown

        SEND_TO.find(t)?.let { m -> return send(m.groupValues[1], m.groupValues[2]) }
        PAY_TO.find(t)?.let { m -> return send(m.groupValues[1], m.groupValues[2]) }
        PAY_NAME_AMOUNT.find(t)?.let { m ->
            if (m.groupValues[1].lowercase() !in NOT_NAMES) return send(m.groupValues[2], m.groupValues[1])
        }

        if (BALANCE.containsMatchIn(t)) return AssistantIntent.CheckBalance
        if (SEND_VERB.containsMatchIn(t)) {
            return AssistantIntent.NeedsMoreInfo("Who should I send it to, and how much? For example: “Send €200 to Ana”.")
        }
        return AssistantIntent.Unknown
    }

    private fun send(amountText: String, name: String): AssistantIntent {
        val cents = parseCents(amountText)
            ?: return AssistantIntent.NeedsMoreInfo("I couldn't read the amount. Try “Send €200 to Ana”.")
        if (cents <= 0) return AssistantIntent.NeedsMoreInfo("The amount has to be more than €0.")
        val clean = name.trim().trimEnd('.', '!', '?', ',')
        return AssistantIntent.SendMoney(clean.replaceFirstChar { it.uppercase() }, cents)
    }

    /** "200" -> 20000, "12.5" -> 1250, "12,50" -> 1250. */
    fun parseCents(s: String): Long? {
        val norm = s.trim().replace(',', '.')
        val parts = norm.split('.')
        if (parts.size > 2) return null
        val whole = parts[0].toLongOrNull() ?: return null
        val frac = when {
            parts.size == 1 -> 0L
            parts[1].length == 1 -> parts[1].toLong() * 10
            parts[1].length == 2 -> parts[1].toLong()
            else -> return null
        }
        return whole * 100 + frac
    }
}
