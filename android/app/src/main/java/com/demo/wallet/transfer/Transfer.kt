package com.demo.wallet.transfer

import java.security.MessageDigest

/** Who initiated the action. The server treats these differently (agent identity layer). */
enum class Actor(val wire: String) { USER("user"), ASSISTANT("assistant") }

data class Payee(val id: String, val name: String, val iban: String)

/** The demo contact list. Server and mock backend use the same ids. */
object Payees {
    val all = listOf(
        Payee("ana", "Ana", "ES91 2100 0418 4502 0005 1332"),
        Payee("ben", "Ben", "DE89 3704 0044 0532 0130 00"),
        Payee("chloe", "Chloé", "FR14 2004 1010 0505 0001 3M02 606"),
    )

    fun byName(name: String): Payee? {
        val n = name.trim().lowercase().fold()
        return all.firstOrNull { it.name.lowercase().fold() == n || it.id == n }
    }

    private fun String.fold() = replace('é', 'e').replace('è', 'e')
}

/**
 * A transfer exactly as it will be executed. Its canonical form is what gets
 * hashed and bound to the Play Integrity token (Lab 2), and what the step-up
 * signature covers.
 */
data class Transfer(
    val account: String,
    val payeeId: String,
    val amountCents: Long,
    val currency: String = "EUR",
    /** Random per transfer; makes every hash unique even for identical transfers. */
    val nonce: String,
    val actor: Actor,
) {
    init {
        require(amountCents > 0) { "amount must be positive" }
        require(listOf(account, payeeId, currency, nonce).none { it.contains('|') }) { "'|' not allowed" }
    }

    /**
     * Canonical serialization, version 1. server/verify.py MUST build the same string:
     *
     *   v1|<account>|<payeeId>|<amountCents>|<currency>|<nonce>|<actor>
     *
     * e.g. v1|acc-001|ana|20000|EUR|3f9c...|assistant
     */
    fun canonical(): String =
        listOf("v1", account, payeeId, amountCents.toString(), currency, nonce, actor.wire).joinToString("|")

    /** Lowercase hex SHA-256 of canonical() (64 chars, under the 500-byte requestHash limit). */
    fun requestHash(): String = sha256Hex(canonical().toByteArray(Charsets.UTF_8))

    fun toJson(): String =
        "{\"account\":\"$account\",\"payeeId\":\"$payeeId\",\"amountCents\":$amountCents," +
            "\"currency\":\"$currency\",\"nonce\":\"$nonce\",\"actor\":\"${actor.wire}\"}"
}

fun sha256Hex(bytes: ByteArray): String =
    MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

fun formatEuros(cents: Long): String {
    val sign = if (cents < 0) "-" else ""
    val abs = kotlin.math.abs(cents)
    val whole = abs / 100
    val frac = abs % 100
    val grouped = whole.toString().reversed().chunked(3).joinToString(",").reversed()
    return "$sign€$grouped.${frac.toString().padStart(2, '0')}"
}
