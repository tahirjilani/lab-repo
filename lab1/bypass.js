// lab1/bypass.js · DSC Europe Lab 1 · DemoWallet only
//
// The app asks itself "am I rooted?" (com.demo.wallet.Guard.isRooted) and trusts the answer.
// This script answers for it. Nothing else is touched: the RASP hook detector still sees Frida,
// and the server still sees that.
//
//   frida -U -f com.demo.wallet -l lab1/bypass.js
//
// Java.perform waits until the app's class loader is ready, so spawning with -f is fine.
Java.perform(() => {
  const Guard = Java.use("com.demo.wallet.Guard");   // Kotlin object, @JvmStatic isRooted()

  Guard.isRooted.implementation = () => {
    console.log("[bypass] Guard.isRooted() → false");
    return false;
  };

  console.log("[bypass] hooked com.demo.wallet.Guard.isRooted: the app now thinks it isn't rooted");
});
