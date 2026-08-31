<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Android — native login with AppAuth-Android, the system browser, and PKCE

## What this is

Wiring authorization-code + PKCE login into an Android app using
[AppAuth-Android](https://github.com/openid/AppAuth-Android), the OpenID Foundation's RFC 8252
reference client. The app opens **Chrome Custom Tabs**, the user authenticates on Keycloak's own
page, and Keycloak redirects back to a custom URI scheme the app has registered.

Read `pattern-integration-decision.md` first — it settles where tokens live (OS keystore), which
grant (auth code + PKCE), and why a mobile client is always `public`. This file does not repeat
those decisions; it implements them.

**Verified against:** `net.openid:appauth:0.11.1`, `androidx.security:security-crypto:1.1.0`,
Keycloak 26.x. Checked 2026-08-27.

---

## The rule that decides everything else: system browser, never a WebView

AppAuth will not let you use a `WebView`, and that is deliberate. Do not work around it by
hand-rolling the flow in one.

| If you use | What happens |
|---|---|
| **Chrome Custom Tabs** (what AppAuth does) | The password is typed into the browser's process, not yours. Cookies are the system browser's, so an existing Keycloak SSO session logs the user straight in. |
| An embedded `WebView` | Your app can read every keystroke and cookie in it, so **the user is handing you their password** — including their Google/Okta password if Keycloak brokers to one. It has its own cookie jar, so **SSO breaks**: every app re-prompts. Many IdPs block it by User-Agent, and both app stores have rejected apps for it. |

AppAuth's README states it plainly: `WebView` is explicitly not supported. RFC 8252 §8.12 is the
normative version.

---

## Step 1: The dependency

```groovy
// app/build.gradle
dependencies {
    implementation 'net.openid:appauth:0.11.1'
    implementation 'androidx.security:security-crypto:1.1.0'   // token storage, see Step 5
}
```

Three facts about that version, so you don't go looking for a newer one:

- **0.11.1 (2021-12-22) is the newest release on Maven Central.** There is no 0.12.x. `master` sits
  a handful of commits ahead with no release cut. A build file pinning `net.openid:appauth:0.12.0`
  or similar fails to resolve — the version does not exist.
- It is stale but not abandoned in the way that matters: it is still the RFC 8252 reference
  implementation, still ships the `<queries>` element Android 11+ package visibility needs to find
  a browser, and still generates PKCE by default.
- It pulls in `androidx.annotation:1.2.0`, `androidx.appcompat:1.3.0`, `androidx.browser:1.3.0`
  transitively. If your app pins newer AndroidX versions, Gradle resolves upward — that is fine and
  expected.

---

## Step 2: Choose the redirect URI

Use a **custom scheme in reverse-domain form**, distinct from any scheme your app already handles
for deep links:

```
com.example.myapp.auth:/oauth2redirect
```

Rules that produce real failures when broken:

- The scheme must be **lowercase**. Android lowercases scheme matching in intent filters; Keycloak
  compares the `redirect_uri` string exactly. A capital letter makes the two disagree.
- It must not collide with your app's deep-link scheme. If React Navigation or an App Link already
  claims `com.example.myapp`, use `com.example.myapp.auth` for OAuth — otherwise the auth redirect
  gets routed to your deep-link handler and AppAuth never sees it.
- `:/oauth2redirect` (one slash) and `://oauth2redirect` (two) are **different URIs** to Keycloak.
  Pick one and use that exact string in both places in Step 3.

App Links (`https://app.example.com/oauth2redirect`) are more secure — a custom scheme can be
claimed by any other installed app — but need a verified `assetlinks.json` on the domain. Start with
a custom scheme; move to App Links when you have the domain to host it.

---

## Step 3: Register the redirect in BOTH places

**This is the most common failure in the whole integration, and each half fails differently.**
Registering one without the other produces two entirely different symptoms:

| Registered in | Missing from | Symptom |
|---|---|---|
| Keycloak client | the app (Gradle/manifest) | **The build fails.** AppAuth's manifest declares `<data android:scheme="${appAuthRedirectScheme}"/>`; with no placeholder the merger aborts with `Attribute data@scheme ... requires a placeholder substitution`. If you instead registered a *different* scheme, login completes in the browser and the redirect dead-ends on `ERR_UNKNOWN_URL_SCHEME` — the app never comes back. |
| the app | Keycloak client | **`Invalid parameter: redirect_uri`** on Keycloak's error page, before the login form renders. The user never gets to type a password. |

### 3a. The app side — Gradle manifest placeholder

```groovy
// app/build.gradle
android {
    defaultConfig {
        manifestPlaceholders = [
            'appAuthRedirectScheme': 'com.example.myapp.auth'
        ]
    }
}
```

The placeholder is the **scheme only** — no `:/`, no path. AppAuth's library manifest already
declares `RedirectUriReceiverActivity` with a `VIEW` / `DEFAULT` / `BROWSABLE` intent-filter and
substitutes this value into it. You do not add an activity yourself.

If you need an App Link or more control, override the activity instead (needs
`xmlns:tools` on `<manifest>`):

```xml
<activity
    android:name="net.openid.appauth.RedirectUriReceiverActivity"
    android:exported="true"
    tools:node="replace">
    <intent-filter android:autoVerify="true">
        <action android:name="android.intent.action.VIEW"/>
        <category android:name="android.intent.category.DEFAULT"/>
        <category android:name="android.intent.category.BROWSABLE"/>
        <data android:scheme="https" android:host="app.example.com" android:path="/oauth2redirect"/>
    </intent-filter>
</activity>
```

### 3b. The Keycloak side — the client's redirect URIs

Public client, standard flow on. Add the **full URI**, not the scheme:

```
com.example.myapp.auth:/oauth2redirect
```

See `client-registration-mcp.md` (Phase Two) or `client-registration.md` (self-managed) for the
call. Two client settings matter specifically for mobile:

| Setting (Admin console) | Value | Failure if wrong |
|---|---|---|
| **Client authentication** | Off (public) | A secret in an APK is a published secret — anyone can `apktool` it out. AppAuth on a public client sends no secret; if the client is confidential, the token call fails `invalid_client`. |
| **Proof Key for Code Exchange Code Challenge Method** (Advanced tab) | `S256` | Leaving it blank lets PKCE be *accepted* but not *required*, so a stolen authorization code is still redeemable by an attacker who intercepted the redirect. Set it and Keycloak rejects any request from this client without a `code_challenge`. |

**Web origins are irrelevant here.** There is no browser JS making a cross-origin token call — the
app's own HTTP stack does it. Don't set them and don't chase CORS errors that cannot occur.

---

## Step 4: The auth flow

Keycloak's issuer is `https://<host>/realms/<realm>`. **Not `/auth/realms/`** — that prefix was
dropped in Keycloak 17 when the server moved to Quarkus. An old tutorial's URL 404s at discovery and
surfaces as a vague "failed to fetch configuration".

```kotlin
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import net.openid.appauth.*

class LoginActivity : AppCompatActivity() {

    private val issuer = Uri.parse("https://keycloak.example.com/realms/acme")
    private val clientId = "acme-android"
    private val redirectUri = Uri.parse("com.example.myapp.auth:/oauth2redirect")

    private lateinit var authService: AuthorizationService
    private lateinit var authState: AuthState

    // Must be registered before the activity is STARTED — a field initializer or onCreate.
    // Registering it inside a click handler throws IllegalStateException.
    private val authLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        val data: Intent = result.data ?: return@registerForActivityResult
        val response = AuthorizationResponse.fromIntent(data)
        val error = AuthorizationException.fromIntent(data)
        authState.update(response, error)

        if (response == null) {
            // User cancelled, or Keycloak returned an error. error.errorDescription has the detail.
            AuthStore.save(this, authState)
            return@registerForActivityResult
        }

        // Exchange the code for tokens. AppAuth attaches the PKCE code_verifier automatically.
        authService.performTokenRequest(response.createTokenExchangeRequest()) { tokenResponse, ex ->
            authState.update(tokenResponse, ex)
            AuthStore.save(this, authState)     // persist AFTER the exchange, not before
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        authService = AuthorizationService(this)
        authState = AuthStore.load(this)
    }

    fun startLogin() {
        AuthorizationServiceConfiguration.fetchFromIssuer(issuer) { config, ex ->
            if (config == null) {
                // Discovery failed: wrong issuer, no network, or an untrusted TLS cert.
                return@fetchFromIssuer
            }
            val request = AuthorizationRequest.Builder(
                config,
                clientId,
                ResponseTypeValues.CODE,
                redirectUri
            )
                .setScope("openid profile email")
                .build()

            authLauncher.launch(authService.getAuthorizationRequestIntent(request))
        }
    }

    override fun onDestroy() {
        authService.dispose()   // releases the Custom Tabs service binding; leaks if you skip it
        super.onDestroy()
    }
}
```

**PKCE is on and you did not switch it on.** `AuthorizationRequest.Builder`'s constructor calls
`setCodeVerifier(CodeVerifierUtil.generateRandomCodeVerifier())`, which derives an S256 challenge.
Do not call `setCodeVerifier(null)` — that disables PKCE, and against a client with the challenge
method pinned to `S256` every authorization request then fails.

### Calling your API

Never read `authState.accessToken` directly for a request — it may be expired.

```kotlin
authState.performActionWithFreshTokens(authService) { accessToken, _, ex ->
    if (ex != null) {
        // Refresh failed: the Keycloak SSO session ended or the refresh token was revoked.
        // Send the user back through startLogin().
        return@performActionWithFreshTokens
    }
    val request = Request.Builder()
        .url("https://api.example.com/me")
        .header("Authorization", "Bearer $accessToken")
        .build()
    // ...
}
```

`performActionWithFreshTokens` refreshes when needed and mutates `authState` in place. **Save the
state inside the callback** — otherwise the rotated refresh token exists only in memory, and after
the process dies the user is logged out with a token that Keycloak has already invalidated.

---

## Step 5: Secure token storage

`AuthState` serializes to a JSON string. It contains the refresh token, which is a long-lived,
replayable credential — treat it as a password.

```kotlin
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

object AuthStore {
    private const val FILE = "auth"
    private const val KEY = "authState"

    private fun prefs(context: Context) = EncryptedSharedPreferences.create(
        context,
        FILE,
        MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
    )

    fun save(context: Context, state: AuthState) =
        prefs(context).edit().putString(KEY, state.jsonSerializeString()).apply()

    fun load(context: Context): AuthState =
        prefs(context).getString(KEY, null)?.let { AuthState.jsonDeserialize(it) } ?: AuthState()
}
```

### Read this before you copy that block

**`EncryptedSharedPreferences` is deprecated.** `androidx.security:security-crypto:1.1.0`
(2025-07-30) is the current stable release, and every API in it carries `@Deprecated` — the class
Javadoc says to use `android.content.SharedPreferences` instead. Google's reasoning is that
app-private files are already covered by Android's file-based encryption, and the Tink keyset the
wrapper maintained caused real key-loss bugs. It still compiles, still works, and still helps
against an attacker with filesystem access on a rooted or backed-up device.

Your options, in the order most apps should consider them:

| Option | When |
|---|---|
| Keep `EncryptedSharedPreferences` (deprecated but functional) | Existing code, or a threat model that includes rooted devices. Expect deprecation warnings; suppress them deliberately, not silently. |
| Encrypt the `AuthState` JSON yourself with an AES key held in the **Android Keystore** | New code that needs hardware-backed keys or `setUserAuthenticationRequired`. |
| Plain app-private `SharedPreferences` (`MODE_PRIVATE`) | Only if you accept Google's current position that platform encryption suffices. |

What is **not** an option, under any of the three: `MODE_WORLD_READABLE`, external storage, logging
the token, or leaving `android:allowBackup="true"` so the refresh token rides out in a cloud backup.
Set `android:allowBackup="false"` or exclude the auth file with `dataExtractionRules`.

---

## Logout

Clearing local state logs the user out of your app only. The Keycloak SSO session survives in the
browser, so the next login silently re-authenticates. To end it, send an RP-initiated logout:

```kotlin
val endSessionRequest = EndSessionRequest.Builder(config)
    .setIdTokenHint(authState.idToken)
    .setPostLogoutRedirectUri(Uri.parse("com.example.myapp.auth:/logout"))
    .build()

endSessionLauncher.launch(authService.getEndSessionRequestIntent(endSessionRequest))
// then, in the result callback:
authState = AuthState()
AuthStore.save(this, authState)
```

**Keycloak validates the post-logout URI separately from the login one.** Since Keycloak 19 the
client has a **Valid post logout redirect URIs** field; if it is empty, the redirect after logout
fails with an invalid-redirect error even though login works. Either add
`com.example.myapp.auth:/logout` there, or set the field to `+`, which reuses the Valid Redirect
URIs list.

---

## Verify

Do all five. Steps 1–3 pass on a wrong configuration; only 4 and 5 catch the redirect mismatch.

1. **Build succeeds.** If the merger complains about `${appAuthRedirectScheme}`, Step 3a is missing.
2. `adb shell dumpsys package com.example.myapp | grep -A3 "Scheme"` — confirm the scheme is
   registered as an intent filter.
3. Tap login on a **real device or emulator with Chrome installed**. A Custom Tab must open with
   `https://keycloak.example.com/realms/acme/protocol/openid-connect/auth?...` in the URL bar. If it
   is your app's own view, something is using a WebView.
4. Read the `redirect_uri=` parameter out of that URL bar and compare it character for character
   against the value on the Keycloak client. This is the check that catches `:/` vs `://`.
5. Complete login. The app must come back to the foreground on its own. Then kill the process
   (`adb shell am force-stop com.example.myapp`), relaunch, and confirm the user is still signed in
   — that proves the `AuthState` persisted and the refresh token works.

Decode the access token and confirm `iss` matches your issuer exactly, and `azp` is `acme-android`.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Build fails: `Attribute data@scheme ... requires a placeholder substitution` | `appAuthRedirectScheme` not set in `defaultConfig` | Step 3a. The placeholder is the scheme alone, no `:/`. |
| `Invalid parameter: redirect_uri` on Keycloak's page, before the login form | the URI the app sent is not on the client | Compare the `redirect_uri` query parameter to the registered value; check `:/` vs `://`, case, and trailing slash |
| Login completes in the browser, `ERR_UNKNOWN_URL_SCHEME`, app never returns | Keycloak's registered URI uses a scheme the app didn't claim | Make the Gradle placeholder and the Keycloak URI's scheme identical |
| App returns but `result.data` is `null` | user dismissed the Custom Tab | Normal cancellation — treat it as "not logged in", not an error |
| `AuthorizationException` `TokenRequestErrors.INVALID_GRANT` (code 2002) at the token exchange | PKCE verifier mismatch, or the code was already redeemed | Don't reuse an `AuthorizationResponse`; don't call `setCodeVerifier(null)` |
| Token exchange fails `invalid_client` | the Keycloak client is confidential | Turn Client authentication off. Never fix this by shipping the secret. |
| Discovery fails, "failed to fetch configuration" | issuer URL wrong, or `/auth/` prefix left in from a pre-17 tutorial | `curl https://<host>/realms/<realm>/.well-known/openid-configuration` and use whatever URL returns JSON |
| `ActivityNotFoundException` / no browser opens | device has no browser (bare emulator image) | Use an emulator image *with* Google APIs, or install Chrome |
| Crashes on Android 12+: `Targeting S+ requires FLAG_IMMUTABLE or FLAG_MUTABLE` | your own `PendingIntent` built with flags `0` — AppAuth's README predates API 31 | Add `PendingIntent.FLAG_IMMUTABLE`, or use the `getAuthorizationRequestIntent` + `ActivityResultLauncher` form above, which needs no `PendingIntent` |
| User logged out after force-stop despite a fresh login | state saved before the token exchange, or not saved from the `performActionWithFreshTokens` callback | Save inside both callbacks |
| Logout redirect fails but login works | **Valid post logout redirect URIs** is empty on the client | Add the logout URI, or set the field to `+` |
| Second login shows the login form again despite an active SSO session | a WebView or an ephemeral browser session — no shared cookie jar | Use the default Custom Tabs agent; don't set an ephemeral session unless you mean it |
