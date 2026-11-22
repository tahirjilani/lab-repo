package com.demo.wallet.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ExitToApp
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.demo.wallet.WalletApi
import com.demo.wallet.assistant.IntentParser
import com.demo.wallet.rasp.RaspReport
import com.demo.wallet.transfer.Payee
import com.demo.wallet.transfer.Payees
import com.demo.wallet.transfer.formatEuros

@Composable
fun WalletRoot(vm: WalletViewModel) {
    val state by vm.state.collectAsState()
    Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
        Box(Modifier.safeDrawingPadding()) {
            when (val s = state.screen) {
                Screen.RootBlocked -> RootBlockedScreen(onRetry = vm::checkDevice)
                Screen.SignIn -> SignInScreen(state, vm::signIn, vm::clearError)
                Screen.Home -> HomeScreen(state, vm)
                is Screen.Confirm -> ConfirmScreen(s.pending, state.busy, vm)
            }
        }
    }
}

// ── Rooted gate ───────────────────────────────────────────────────────────────

@Composable
private fun RootBlockedScreen(onRetry: () -> Unit) {
    Column(
        Modifier.fillMaxSize().padding(32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Icon(Icons.Filled.Warning, null, Modifier.size(56.dp), tint = MaterialTheme.colorScheme.error)
        Spacer(Modifier.height(16.dp))
        Text("This device appears to be rooted", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.height(8.dp))
        Text(
            "For your security, DemoWallet doesn't run on rooted devices.",
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(24.dp))
        OutlinedButton(onClick = onRetry) { Text("Check again") }
        Spacer(Modifier.height(24.dp))
        Text(
            "Decided by Guard.isRooted() on the device.",
            style = MaterialTheme.typography.labelSmall,
            fontFamily = FontFamily.Monospace,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

// ── Sign-in ───────────────────────────────────────────────────────────────────

@Composable
private fun SignInScreen(state: UiState, onSignIn: (String, String) -> Unit, onClearError: () -> Unit) {
    var user by rememberSaveable { mutableStateOf("tahir") }
    var pass by rememberSaveable { mutableStateOf("demo") }
    Column(
        Modifier.fillMaxSize().padding(28.dp).imePadding(),
        verticalArrangement = Arrangement.Center,
    ) {
        Text("DemoWallet", style = MaterialTheme.typography.displaySmall, fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.primary)
        Text("Demo sign-in · any username and password", color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.height(28.dp))
        OutlinedTextField(
            value = user, onValueChange = { user = it; onClearError() },
            label = { Text("Username") }, singleLine = true, modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(12.dp))
        OutlinedTextField(
            value = pass, onValueChange = { pass = it; onClearError() },
            label = { Text("Password") }, singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
            keyboardActions = KeyboardActions(onDone = { onSignIn(user, pass) }),
            modifier = Modifier.fillMaxWidth(),
        )
        state.error?.let {
            Spacer(Modifier.height(12.dp))
            Text(it, color = MaterialTheme.colorScheme.error)
        }
        Spacer(Modifier.height(20.dp))
        Button(onClick = { onSignIn(user, pass) }, enabled = !state.busy, modifier = Modifier.fillMaxWidth().height(52.dp)) {
            if (state.busy) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
            else Text("Sign in")
        }
        Spacer(Modifier.height(24.dp))
        LabFooter(state)
    }
}

// ── Home: balance, device signals, assistant ────────────────────────────────────

@Composable
private fun HomeScreen(state: UiState, vm: WalletViewModel) {
    var input by rememberSaveable { mutableStateOf("") }
    var showSend by remember { mutableStateOf(false) }
    val listState = rememberLazyListState()
    LaunchedEffect(state.messages.size) {
        if (state.messages.isNotEmpty()) listState.animateScrollToItem(state.messages.lastIndex)
    }

    Column(Modifier.fillMaxSize().imePadding().padding(horizontal = 16.dp)) {
        Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("Hi, ${state.displayName}", style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
            IconButton(onClick = vm::signOut) { Icon(Icons.AutoMirrored.Filled.ExitToApp, "Sign out") }
        }

        Card(
            Modifier.fillMaxWidth().padding(top = 4.dp),
            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer),
        ) {
            Row(Modifier.padding(20.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Balance", style = MaterialTheme.typography.labelLarge)
                    Text(
                        state.balanceCents?.let(::formatEuros) ?: "—",
                        style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold,
                    )
                }
                Button(onClick = { showSend = true }, enabled = !state.busy) { Text("Send") }
            }
        }

        state.rasp?.let { SignalsRow(it, state.integrityBinding) }
        state.deviceKeyProblem?.let {
            Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.padding(top = 6.dp))
        }

        Text("Assistant", style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(top = 14.dp, bottom = 6.dp))
        LazyColumn(
            state = listState,
            modifier = Modifier.weight(1f).fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            items(state.messages) { ChatBubble(it) }
        }

        state.pendingGrant?.let { GrantCard(it, state.busy, onAllow = vm::approveGrant, onDeny = vm::denyGrant) }
        val canAsk = !state.busy && state.pendingGrant == null
        SuggestionRow(enabled = canAsk) { vm.ask(it) }
        Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = input, onValueChange = { input = it },
                placeholder = { Text("Ask the assistant…") }, singleLine = true,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                keyboardActions = KeyboardActions(onSend = { vm.ask(input); input = "" }),
                modifier = Modifier.weight(1f),
            )
            Spacer(Modifier.size(8.dp))
            FilledIconButton(onClick = { vm.ask(input); input = "" }, enabled = canAsk && input.isNotBlank()) {
                if (state.busy) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                else Icon(Icons.AutoMirrored.Filled.Send, "Send to assistant")
            }
        }
    }

    if (showSend) {
        SendDialog(
            onDismiss = { showSend = false },
            onSend = { payee, cents -> showSend = false; vm.sendManual(payee, cents) },
        )
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun SignalsRow(r: RaspReport, integrityBinding: Boolean) {
    FlowRow(
        Modifier.fillMaxWidth().padding(top = 10.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Signal("root", r.rooted)
        Signal("emulator", r.emulator)
        Signal("debugger", r.debugger)
        Signal("signature", !r.signatureValid, okLabel = "signature ok", badLabel = "signature bad")
        Signal("hook", r.hooked)
        Tag(if (integrityBinding) "integrity: on" else "integrity: off", MaterialTheme.colorScheme.secondaryContainer)
    }
}

@Composable
private fun Signal(name: String, bad: Boolean, okLabel: String = "$name ✓", badLabel: String = "$name!") {
    Tag(
        if (bad) badLabel else okLabel,
        if (bad) MaterialTheme.colorScheme.errorContainer else MaterialTheme.colorScheme.surfaceVariant,
    )
}

@Composable
private fun Tag(text: String, color: Color) {
    Text(
        text,
        fontFamily = FontFamily.Monospace,
        fontSize = 12.sp,
        modifier = Modifier
            .background(color, RoundedCornerShape(50))
            .padding(horizontal = 10.dp, vertical = 4.dp),
    )
}

@Composable
private fun ChatBubble(m: ChatMessage) {
    val mine = m.from == Speaker.USER
    Row(Modifier.fillMaxWidth(), horizontalArrangement = if (mine) Arrangement.End else Arrangement.Start) {
        when (m.from) {
            Speaker.TOOL -> Text(
                "→ ${m.text}",
                fontFamily = FontFamily.Monospace, fontSize = 12.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 4.dp),
            )
            // The delegation the user just made, so the audience sees it before the transfer goes out.
            Speaker.GRANT -> Row(
                Modifier
                    .fillMaxWidth()
                    .background(MaterialTheme.colorScheme.tertiaryContainer, RoundedCornerShape(12.dp))
                    .padding(horizontal = 12.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(Icons.Filled.Lock, null, Modifier.size(16.dp), tint = MaterialTheme.colorScheme.onTertiaryContainer)
                Spacer(Modifier.size(8.dp))
                Text(
                    m.text,
                    fontFamily = FontFamily.Monospace, fontSize = 12.sp,
                    color = MaterialTheme.colorScheme.onTertiaryContainer,
                )
            }
            else -> Text(
                m.text,
                modifier = Modifier
                    .widthIn(max = 300.dp)
                    .background(
                        if (mine) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surfaceVariant,
                        RoundedCornerShape(16.dp),
                    )
                    .padding(horizontal = 14.dp, vertical = 10.dp),
                color = if (mine) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurface,
            )
        }
    }
}

/** Consent card: the user delegates one scoped, single-use transfer to the assistant. */
@Composable
private fun GrantCard(req: GrantRequest, busy: Boolean, onAllow: () -> Unit, onDeny: () -> Unit) {
    Card(
        Modifier.fillMaxWidth().padding(vertical = 6.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.tertiaryContainer),
    ) {
        Column(Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Filled.Person, null, Modifier.size(18.dp), tint = MaterialTheme.colorScheme.onTertiaryContainer)
                Spacer(Modifier.size(8.dp))
                Text("Let the assistant do this?", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
            }
            Spacer(Modifier.height(6.dp))
            Text(
                "agent   ${WalletApi.ASSISTANT_AGENT_ID}\n" +
                    "action  transfer to ${req.payee.name} (${req.payee.iban})\n" +
                    "up to   ${formatEuros(req.scopeCents)} · single use · 5 min",
                fontFamily = FontFamily.Monospace, fontSize = 12.sp,
            )
            if (req.exceedsLimit) {
                Spacer(Modifier.height(6.dp))
                Text(
                    "You asked for ${formatEuros(req.amountCents)}, but the most you can delegate is " +
                        "${formatEuros(req.limitCents)} (agent limit). The bank will ask you to confirm this one.",
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            Row(Modifier.fillMaxWidth().padding(top = 8.dp), horizontalArrangement = Arrangement.End) {
                TextButton(onClick = onDeny, enabled = !busy) { Text("Deny") }
                Spacer(Modifier.size(8.dp))
                Button(onClick = onAllow, enabled = !busy) { Text("Allow") }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun SuggestionRow(enabled: Boolean, onPick: (String) -> Unit) {
    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        listOf("Send €200 to Ana", "Send €20 to Ben", "What's my balance?").forEach { s ->
            AssistChip(onClick = { onPick(s) }, label = { Text(s) }, enabled = enabled)
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun SendDialog(onDismiss: () -> Unit, onSend: (Payee, Long) -> Unit) {
    var payee by remember { mutableStateOf(Payees.all.first()) }
    var amount by remember { mutableStateOf("") }
    val cents = IntentParser.parseCents(amount)
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Send money") },
        text = {
            Column {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Payees.all.forEach { p ->
                        FilterChip(selected = p == payee, onClick = { payee = p }, label = { Text(p.name) })
                    }
                }
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = amount, onValueChange = { amount = it },
                    label = { Text("Amount (€)") }, singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                )
            }
        },
        confirmButton = {
            TextButton(onClick = { cents?.let { onSend(payee, it) } }, enabled = cents != null && cents > 0) { Text("Send") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
internal fun LabFooter(state: UiState) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Icon(Icons.Filled.Lock, null, Modifier.size(14.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.size(6.dp))
        Text(
            "backend: ${state.backendLabel} · integrity binding: ${if (state.integrityBinding) "on" else "off"}",
            style = MaterialTheme.typography.labelSmall, fontFamily = FontFamily.Monospace,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
