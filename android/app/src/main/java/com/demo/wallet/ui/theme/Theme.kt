package com.demo.wallet.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val Teal = Color(0xFF0E3B43)
private val TealLight = Color(0xFF1F6F78)
private val Gold = Color(0xFFF4C95D)

private val Light = lightColorScheme(
    primary = TealLight,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFD3ECEE),
    onPrimaryContainer = Teal,
    secondary = Color(0xFF8A6A12),
    secondaryContainer = Color(0xFFFFEFC2),
    onSecondaryContainer = Color(0xFF3A2C00),
    background = Color(0xFFF7F8F7),
    surface = Color.White,
    surfaceVariant = Color(0xFFECEFEE),
    error = Color(0xFFB3261E),
    errorContainer = Color(0xFFFFDAD6),
)

private val Dark = darkColorScheme(
    primary = Color(0xFF8FD3DA),
    onPrimary = Teal,
    primaryContainer = TealLight,
    onPrimaryContainer = Color(0xFFD3ECEE),
    secondary = Gold,
    secondaryContainer = Color(0xFF5A4500),
    onSecondaryContainer = Color(0xFFFFEFC2),
    background = Color(0xFF0B1416),
    surface = Color(0xFF111C1F),
    surfaceVariant = Color(0xFF1C292C),
)

@Composable
fun DemoWalletTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = if (isSystemInDarkTheme()) Dark else Light, content = content)
}
