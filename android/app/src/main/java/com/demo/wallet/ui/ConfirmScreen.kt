package com.demo.wallet.ui

import android.content.Context
import android.content.ContextWrapper
import android.os.Build
import android.security.keystore.KeyPermanentlyInvalidatedException
import android.view.View
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricManager.Authenticators.BIOMETRIC_STRONG
import androidx.biometric.BiometricPrompt
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import com.demo.wallet.WalletApi
import com.demo.wallet.auth.DeviceKey
import com.demo.wallet.transfer.Actor
import com.demo.wallet.transfer.formatEuros

/**
 * Step-up confirmation. Names the action, the amount and the payee in the app AND in
 * the system biometric sheet, and only a biometric-unlocked Keystore key can produce
 * the signature the server accepts — so an agent can't "click confirm" for the user.
 */
@Composable
fun ConfirmScreen(p: PendingStepUp, busy: Boolean, vm: WalletViewModel) {
    val context = LocalContext.current
    val view = LocalView.current
    var problem by remember(p.transferId) { mutableStateOf<String?>(null) }

    // Android 14+: hide this screen's contents from accessibility services that are
    // not declared accessibility tools (screen readers keep access). Step-1 row 15.
    DisposableEffect(view) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            view.setAccessibilityDataSensitive(View.ACCESSIBILITY_DATA_SENSITIVE_YES)
        }
        onDispose {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                view.setAccessibilityDataSensitive(View.ACCESSIBILITY_DATA_SENSITIVE_AUTO)
            }
        }
    }

    val requester = if (p.actor == Actor.ASSISTANT) "DemoWallet assistant (${WalletApi.ASSISTANT_AGENT_ID})" else "You"

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Spacer(Modifier.height(8.dp))
        Icon(Icons.Filled.Lock, null, Modifier.size(40.dp), tint = MaterialTheme.colorScheme.primary)
        Text("Confirm this transfer", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.SemiBold)
        Text(p.reason, color = MaterialTheme.colorScheme.onSurfaceVariant)

        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Field("Action", "Send money")
                HorizontalDivider()
                Field("Amount", formatEuros(p.amountCents), big = true)
                HorizontalDivider()
                Field("Payee", p.payee.name)
                Text(p.payee.iban, fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                HorizontalDivider()
                Field("Requested by", requester)
            }
        }

        problem?.let { Text(it, color = MaterialTheme.colorScheme.error) }

        Button(
            onClick = {
                problem = null
                startBiometric(context, p, vm) { problem = it }
            },
            enabled = !busy,
            modifier = Modifier.fillMaxWidth().height(56.dp),
        ) {
            if (busy) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
            else Text("Confirm ${formatEuros(p.amountCents)} to ${p.payee.name}")
        }
        OutlinedButton(onClick = { vm.cancelStepUp() }, enabled = !busy, modifier = Modifier.fillMaxWidth()) {
            Text("Cancel")
        }
        Text(
            "transfer ${p.transferId} · hash ${p.requestHash.take(12)}…",
            fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun Field(label: String, value: String, big: Boolean = false) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(label, Modifier.weight(1f), color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(
            value,
            style = if (big) MaterialTheme.typography.headlineSmall else MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
        )
    }
}

private fun startBiometric(context: Context, p: PendingStepUp, vm: WalletViewModel, onProblem: (String) -> Unit) {
    val activity = context.findFragmentActivity()
        ?: return onProblem("Biometric prompt needs a FragmentActivity.")

    when (BiometricManager.from(activity).canAuthenticate(BIOMETRIC_STRONG)) {
        BiometricManager.BIOMETRIC_SUCCESS -> Unit
        BiometricManager.BIOMETRIC_ERROR_NONE_ENROLLED -> return onProblem(
            "No fingerprint enrolled. On the emulator: Settings → Security → add a screen lock and a fingerprint " +
                "(touch the sensor from Extended controls → Fingerprint), then sign in again."
        )
        else -> return onProblem("Strong biometrics aren't available on this device.")
    }

    val signature = try {
        DeviceKey.signatureForPrompt()
    } catch (e: KeyPermanentlyInvalidatedException) {
        DeviceKey.reset()
        return onProblem("Your fingerprints changed, so the confirmation key was reset. Sign out and sign in again.")
    } catch (e: Exception) {
        return onProblem("No confirmation key on this device (${e.javaClass.simpleName}). Sign out and sign in again.")
    }

    val prompt = BiometricPrompt(
        activity,
        ContextCompat.getMainExecutor(activity),
        object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                val unlocked = result.cryptoObject?.signature
                if (unlocked == null) onProblem("Biometric succeeded but no key was unlocked.")
                else vm.completeStepUp(p, unlocked)
            }

            override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                if (errorCode != BiometricPrompt.ERROR_NEGATIVE_BUTTON && errorCode != BiometricPrompt.ERROR_USER_CANCELED) {
                    onProblem(errString.toString())
                } else {
                    onProblem("Not confirmed.")
                }
            }
        },
    )

    val info = BiometricPrompt.PromptInfo.Builder()
        .setTitle("Send ${formatEuros(p.amountCents)} to ${p.payee.name}?")
        .setSubtitle(p.payee.iban)
        .setDescription(
            if (p.actor == Actor.ASSISTANT) "Requested by the DemoWallet assistant" else "Requested by you"
        )
        .setNegativeButtonText("Cancel")
        .setAllowedAuthenticators(BIOMETRIC_STRONG)
        .setConfirmationRequired(true)
        .build()

    prompt.authenticate(info, BiometricPrompt.CryptoObject(signature))
}

private fun Context.findFragmentActivity(): FragmentActivity? {
    var c: Context? = this
    while (c is ContextWrapper) {
        if (c is FragmentActivity) return c
        c = c.baseContext
    }
    return null
}
