package com.demo.wallet.auth

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.Signature
import java.security.spec.ECGenParameterSpec

/**
 * A per-install EC key in Android Keystore that can only sign after a strong
 * biometric authentication, once per use.
 *
 * Step-up confirmation signs the server's challenge plus the transfer hash with it
 * (BiometricPrompt + CryptoObject), so "the user approved THIS transfer" is a
 * cryptographic statement, not a boolean the client sends. The public key is
 * registered with the server at sign-in.
 *
 * This replaces Android Protected Confirmation (limited device support, being
 * deprecated) — see step-1 summary row 21.
 */
object DeviceKey {
    private const val ALIAS = "demowallet-stepup"
    private const val ANDROID_KEYSTORE = "AndroidKeyStore"

    private fun keyStore(): KeyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }

    /** Creates the key if needed and returns the public key as base64 X.509 (SubjectPublicKeyInfo). */
    fun ensure(): String {
        val ks = keyStore()
        if (!ks.containsAlias(ALIAS)) {
            val spec = KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_SIGN)
                .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
                .setDigests(KeyProperties.DIGEST_SHA256)
                .setUserAuthenticationRequired(true)
                // 0 = every signature needs its own biometric authentication.
                .setUserAuthenticationParameters(0, KeyProperties.AUTH_BIOMETRIC_STRONG)
                .setInvalidatedByBiometricEnrollment(true)
                .build()
            KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, ANDROID_KEYSTORE).apply {
                initialize(spec)
                generateKeyPair()
            }
        }
        val cert = ks.getCertificate(ALIAS)
        return Base64.encodeToString(cert.publicKey.encoded, Base64.NO_WRAP)
    }

    /**
     * A Signature initialised with the private key, ready to wrap in a CryptoObject.
     * Throws KeyPermanentlyInvalidatedException if biometrics changed — then call
     * [reset], [ensure] again and re-register.
     */
    fun signatureForPrompt(): Signature {
        val key = keyStore().getKey(ALIAS, null) as PrivateKey
        return Signature.getInstance("SHA256withECDSA").apply { initSign(key) }
    }

    fun reset() {
        runCatching { keyStore().deleteEntry(ALIAS) }
    }

    /**
     * The exact bytes signed at step-up. server/verify.py must rebuild them:
     *   stepup|v1|<challengeId>|<challengeNonce>|<requestHash>
     */
    fun stepUpMessage(challengeId: String, challengeNonce: String, requestHash: String): ByteArray =
        "stepup|v1|$challengeId|$challengeNonce|$requestHash".toByteArray(Charsets.UTF_8)
}
