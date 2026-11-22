# Lab 1 · Break it

Guide: [`docs/lab1.md`](../docs/lab1.md). Frida versions: [`requirements.txt`](requirements.txt).

**`bypass.js`** hooks `com.demo.wallet.Guard.isRooted()` to return `false`:

```bash
frida -U -f com.demo.wallet -l lab1/bypass.js
```

What it targets, from the app's side:

- `Guard.isRooted()` is a Kotlin `object` method marked `@JvmStatic`, so in Java terms it's `static boolean com.demo.wallet.Guard.isRooted()`. A ProGuard rule keeps the name.
- It's the only root gate: it decides the "This device appears to be rooted" screen at start, is checked again before every transfer, and also feeds the `root` RASP flag. Hooking it hides root everywhere in the app.
- It does **not** hide the hook itself: the RASP `hook` flag (Frida's port, thread names, `/proc/self/maps`) is a separate check, and the server sees it.
- It doesn't tap anything. When the assistant asks for permission, you still tap **Allow** yourself.

Use it only against DemoWallet on your own emulator.
