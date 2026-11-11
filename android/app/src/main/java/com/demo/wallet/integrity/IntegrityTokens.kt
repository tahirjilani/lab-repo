package com.demo.wallet.integrity

import android.content.Context
import android.util.Log
import com.demo.wallet.BuildConfig
import com.demo.wallet.IntegrityResult
import com.google.android.play.core.integrity.IntegrityManagerFactory
import com.google.android.play.core.integrity.StandardIntegrityManager
import com.google.android.play.core.integrity.StandardIntegrityManager.PrepareIntegrityTokenRequest
import com.google.android.play.core.integrity.StandardIntegrityManager.StandardIntegrityTokenProvider
import com.google.android.play.core.integrity.StandardIntegrityManager.StandardIntegrityTokenRequest
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlin.coroutines.resume

/**
 * Play Integrity *standard* requests (step-1 summary row 7–9):
 *  - prepareIntegrityToken() once (warm-up, can take seconds),
 *  - then request(requestHash) per transfer; the hash is bound into the verdict
 *    and comes back as requestDetails.requestHash after server-side decode.
 *
 * On a stock emulator image this will usually FAIL (no Play Store, or an
 * unrecognised sideloaded app). That is expected in the lab: the failure is sent
 * as integrity.error and the server steps up. See step-2 summary.
 */
class IntegrityTokens(context: Context) {
    private val appContext = context.applicationContext
    private val mutex = Mutex()
    private var provider: StandardIntegrityTokenProvider? = null

    val configured: Boolean get() = BuildConfig.CLOUD_PROJECT_NUMBER != 0L

    /** Call early (e.g. after sign-in) so the first transfer doesn't wait for warm-up. */
    suspend fun prepare(): String? = mutex.withLock {
        if (provider != null) return@withLock null
        if (!configured) return@withLock "NOT_CONFIGURED"
        try {
            val manager: StandardIntegrityManager = IntegrityManagerFactory.createStandard(appContext)
            val request = PrepareIntegrityTokenRequest.builder()
                .setCloudProjectNumber(BuildConfig.CLOUD_PROJECT_NUMBER)
                .build()
            suspendCancellableCoroutine<String?> { cont ->
                manager.prepareIntegrityToken(request)
                    .addOnSuccessListener { p -> provider = p; cont.resume(null) }
                    .addOnFailureListener { e -> cont.resume(describe("PREPARE", e)) }
            }
        } catch (e: Exception) {
            describe("PREPARE", e)
        }
    }

    suspend fun tokenFor(requestHash: String): IntegrityResult {
        prepare()?.let { return IntegrityResult.failed(it) }
        val p = provider ?: return IntegrityResult.failed("NO_PROVIDER")
        return try {
            val request = StandardIntegrityTokenRequest.builder()
                .setRequestHash(requestHash)
                .build()
            suspendCancellableCoroutine<IntegrityResult> { cont ->
                p.request(request)
                    .addOnSuccessListener { r -> cont.resume(IntegrityResult.ok(r.token())) }
                    .addOnFailureListener { e ->
                        // A provider can expire; drop it so the next call prepares again.
                        provider = null
                        cont.resume(IntegrityResult.failed(describe("REQUEST", e)))
                    }
            }
        } catch (e: Exception) {
            IntegrityResult.failed(describe("REQUEST", e))
        }
    }

    private fun describe(stage: String, e: Exception): String {
        Log.w("IntegrityTokens", "$stage failed", e)
        // e.g. "REQUEST:StandardIntegrityException:-2: Integrity API error (-2): Play Store not found."
        val msg = e.message?.take(160)?.replace('\n', ' ').orEmpty()
        return "$stage:${e.javaClass.simpleName}:$msg"
    }
}
