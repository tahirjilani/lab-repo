package com.demo.wallet

import android.app.Application
import android.os.Bundle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.fragment.app.FragmentActivity
import com.demo.wallet.ui.WalletRoot
import com.demo.wallet.ui.WalletViewModel
import com.demo.wallet.ui.theme.DemoWalletTheme

class WalletApp : Application()

/** FragmentActivity (not plain ComponentActivity) because BiometricPrompt needs one. */
class MainActivity : FragmentActivity() {

    private val vm: WalletViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        setContent {
            DemoWalletTheme {
                WalletRoot(vm)
            }
        }
    }

    override fun onResume() {
        super.onResume()
        vm.checkDevice()
    }
}
