plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

fun prop(name: String, default: String): String =
    (project.findProperty(name) as String?)?.trim()?.takeIf { it.isNotEmpty() } ?: default

android {
    namespace = "com.demo.wallet"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.demo.wallet"
        minSdk = 30
        targetSdk = 35
        versionCode = 1
        versionName = "1.0-lab"

        buildConfigField("boolean", "INTEGRITY_BINDING", prop("demowallet.integrityBinding", "false"))
        buildConfigField("long", "CLOUD_PROJECT_NUMBER", prop("demowallet.cloudProjectNumber", "0") + "L")
        buildConfigField("String", "API_BASE_URL", "\"" + prop("demowallet.apiBaseUrl", "mock") + "\"")
        buildConfigField("long", "AGENT_LIMIT_CENTS", prop("demowallet.agentLimitCents", "10000") + "L")
        // SHA-256 of the shared lab signing certificate (keystore/lab-debug.jks).
        buildConfigField(
            "String", "EXPECTED_SIGNER_SHA256",
            "\"20e107f47314fe9d753ea21ed6311560c1a408b5eb7cf3cd389acbd9330fd617\""
        )
    }

    signingConfigs {
        // One committed lab key so every attendee's wallet.apk has the same signature
        // and the RASP signature check is meaningful. Never do this for a real app.
        create("lab") {
            storeFile = rootProject.file("keystore/lab-debug.jks")
            storePassword = "android"
            keyAlias = "labdebug"
            keyPassword = "android"
        }
    }

    buildTypes {
        debug {
            signingConfig = signingConfigs.getByName("lab")
        }
        release {
            signingConfig = signingConfigs.getByName("lab")
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    // Produce wallet.apk (the name the deck uses).
    applicationVariants.all {
        outputs.all {
            (this as com.android.build.gradle.internal.api.BaseVariantOutputImpl).outputFileName =
                if (buildType.name == "debug") "wallet.apk" else "wallet-${buildType.name}.apk"
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.12.01")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-core")
    debugImplementation("androidx.compose.ui:ui-tooling")

    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.fragment:fragment-ktx:1.8.5")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")

    implementation("androidx.biometric:biometric:1.1.0")
    implementation("com.google.android.play:integrity:1.4.0")
    implementation("com.google.android.gms:play-services-tasks:18.2.0")

    testImplementation("junit:junit:4.13.2")
}
