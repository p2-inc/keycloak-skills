<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# React Native / Expo — native login with react-native-app-auth, the system browser, and PKCE

## What this is

Wiring authorization-code + PKCE login into a React Native app using
[`react-native-app-auth`](https://github.com/FormidableLabs/react-native-app-auth), a JS bridge over
the OpenID Foundation's own AppAuth-Android and AppAuth-iOS. You get the same RFC 8252 guarantees as
a native app — Chrome Custom Tabs on Android, `ASWebAuthenticationSession` on iOS — from one JS API.

Read `pattern-integration-decision.md` first — it settles where tokens live (OS keystore), which
grant (auth code + PKCE), and why a mobile client is always `public`. This file does not repeat
those decisions; it implements them.

**Verified against:** `react-native-app-auth@8.4.1` (published 2026-07-06, peer
`react-native >= 0.63.0`), `expo-secure-store@57.0.2`, `react-native-keychain@10.0.0`, Keycloak 26.x.
Checked 2026-08-27. API shapes taken from the package's shipped `index.d.ts` and its own docs.

---

## Step 0: Expo or bare React Native — and what actually differs

Detect from the project root:

| Signal | Project type |
|---|---|
| `app.json` with an `expo` key, or `app.config.js` / `app.config.ts` | **Expo** (CNG) |
| No `app.json`/`app.config.*`, but `ios/` and `android/` directories are committed | **Bare React Native** |
| Both — `app.json` *and* committed `ios/`/`android/` | Expo that has already run `prebuild`. Treat as Expo, but note the plugin only regenerates on `prebuild`; hand-edits to `ios/`/`android/` will be overwritten. |

**Expo does not need a different library.** `react-native-app-auth` ships an **official Expo config
plugin** — `app.plugin.js` is in the package's published `files` list and re-exports `plugin/build`,
supporting Expo SDK 53+ with Continuous Native Generation. Same library, same JS API, both project
types. Do not swap to another library on the basis of "it's an Expo project".

**The real constraint is Expo Go, and it is absolute.** Expo's own authentication guide states that
Expo Go cannot be used for local development and testing of OAuth or OpenID Connect apps, because of
"the inability to customize your app scheme". No OAuth library fixes that — Expo says it about
`expo-auth-session`, their own library. Without a custom scheme there is nowhere for Keycloak to
redirect back to. The fix is a **Development Build**, not a different package:

```bash
npx expo install expo-dev-client
npx expo prebuild --clean
npx expo run:ios        # or: npx expo run:android, or an EAS build
```

`expo-auth-session` (currently 57.0.10) is Expo's own pure-JS OIDC client and is a legitimate
alternative — fewer native moving parts in a managed project, at the cost of doing the flow in JS
rather than in AppAuth. It is an **alternative, not a requirement**, and it is under exactly the same
Expo Go restriction. Pick `react-native-app-auth` when you want the audited native AppAuth
implementation; pick `expo-auth-session` when you want to stay closest to the Expo toolchain.

---

## The rule that decides everything else: system browser, never a WebView

`react-native-app-auth` will not run the flow in a `react-native-webview`, because AppAuth will not.
Do not hand-roll it in one.

| If you use | What happens |
|---|---|
| **Custom Tabs / `ASWebAuthenticationSession`** (what this library does) | Credentials are typed into the browser's process, not your JS bundle. The system cookie jar is shared, so an existing Keycloak SSO session signs the user in without a prompt. |
| A `WebView` | Your JS can read every keystroke and cookie in it, so **the user is handing you their password** — including their Google/Okta password if Keycloak brokers to one. Isolated cookie jar, so **SSO breaks** and every app re-prompts. IdPs block it by User-Agent, and both app stores have rejected apps for it. |

---

## Step 1: The dependency

```bash
npm install react-native-app-auth        # 8.4.1
```

Then, by project type:

| Project | Next step |
|---|---|
| Expo | Add the config plugin (Step 3a), then `npx expo prebuild --clean` |
| Bare RN | `cd ios && pod install` — this is what pulls in AppAuth-iOS. Android needs no pod-equivalent; Gradle resolves `net.openid:appauth` transitively. |

---

## Step 2: Choose the redirect URI

Use a custom scheme in reverse-domain form, distinct from any scheme the app already handles:

```
com.example.myapp.auth://oauth2redirect
```

- **Keep it lowercase.** Android lowercases scheme matching in intent filters; Keycloak compares the
  string exactly. A capital letter makes the two disagree.
- **Do not reuse your deep-link scheme.** If React Navigation's linking config already claims
  `com.example.myapp`, use `com.example.myapp.auth` for OAuth. Sharing one scheme means the auth
  callback is delivered to your navigation router and the AppAuth session never resolves — a
  documented failure in this library's issue tracker, and one that only reproduces once deep linking
  is wired up.
- `://oauth2redirect` and `:/oauth2redirect` are **different strings** to Keycloak. Pick one and use
  that exact spelling everywhere.

---

## Step 3: Register the redirect in BOTH places

**This is the most common failure in the whole integration, and each half fails differently.**

| Registered in | Missing from | Symptom |
|---|---|---|
| Keycloak client | the app (plugin config / native files) | **Android:** the Gradle manifest merger fails on `${appAuthRedirectScheme}`, or — if the scheme is merely wrong — login completes and the redirect dead-ends on `ERR_UNKNOWN_URL_SCHEME`. **iOS:** the browser opens, login succeeds, and nothing ever comes back. |
| the app | Keycloak client | **`Invalid parameter: redirect_uri`** on Keycloak's error page, before the login form renders. The user never gets to type a password. |

### 3a. The app side — Expo

`app.json` (or the equivalent in `app.config.js`):

```json
{
  "expo": {
    "scheme": "com.example.myapp",
    "plugins": [
      [
        "react-native-app-auth",
        { "redirectUrls": ["com.example.myapp.auth://oauth2redirect"] }
      ]
    ]
  }
}
```

`redirectUrls` takes **full URLs**, not schemes — the plugin splits the first entry on `:` and
derives the scheme itself. Then:

```bash
npx expo prebuild --clean
```

That writes `CFBundleURLTypes` into `ios/<App>/Info.plist`, wires the AppDelegate and bridging
header, and adds `manifestPlaceholders` to `android/app/build.gradle`. **Config changes take effect
only at `prebuild`.** Editing `app.json` and rebuilding without re-running `prebuild` leaves the old
scheme in the native projects, and the symptom is a redirect that stops working for no visible
reason.

Note the `expo.scheme` above is deliberately *different* from the auth scheme — see Step 2.

### 3b. The app side — bare React Native

**Android** — `android/app/build.gradle`:

```groovy
android {
  defaultConfig {
    manifestPlaceholders = [
      appAuthRedirectScheme: 'com.example.myapp.auth'
    ]
  }
}
```

The placeholder is the **scheme only** — no `://`, no path. AppAuth's own manifest supplies the
`RedirectUriReceiverActivity` and its intent filter; you add no activity.

**iOS** — `ios/<App>/Info.plist`:

```xml
<key>CFBundleURLTypes</key>
<array>
  <dict>
    <key>CFBundleURLName</key>
    <string>com.example.myapp</string>
    <key>CFBundleURLSchemes</key>
    <array>
      <string>com.example.myapp.auth</string>
    </array>
  </dict>
</array>
```

**iOS AppDelegate** — the native side has to hand the callback URL back to the library. Which edit
you make depends on your React Native version, because 0.77 switched the AppDelegate template to
Swift:

*React Native ≥ 0.77 (Swift AppDelegate)* — create a bridging header, e.g.
`ios/AppDelegate+RNAppAuth.h`, containing `#import "RNAppAuthAuthorizationFlowManager.h"`, point
Build Settings → **Objective-C Bridging Header** at it, then:

```swift
@main
class AppDelegate: UIResponder, UIApplicationDelegate, RNAppAuthAuthorizationFlowManager {
  // Required by the RNAppAuthAuthorizationFlowManager protocol.
  public weak var authorizationFlowManagerDelegate: RNAppAuthAuthorizationFlowManagerDelegate?

  func application(_ app: UIApplication,
                   open url: URL,
                   options: [UIApplication.OpenURLOptionsKey: Any] = [:]) -> Bool {
    if let delegate = authorizationFlowManagerDelegate,
       delegate.resumeExternalUserAgentFlow(with: url) {
      return true
    }
    return false
  }
}
```

*React Native ≥ 0.68 (Objective-C `AppDelegate.mm`)* — declare conformance to
`RNAppAuthAuthorizationFlowManager` and the `authorizationFlowManagerDelegate` property in
`AppDelegate.h`, then in `AppDelegate.mm`:

```objc
- (BOOL)application:(UIApplication *)application
            openURL:(NSURL *)url
            options:(NSDictionary<UIApplicationOpenURLOptionsKey, id> *)options
{
  if ([self.authorizationFlowManagerDelegate resumeExternalUserAgentFlowWithURL:url]) {
    return YES;
  }
  return [RCTLinkingManager application:application openURL:url options:options];
}
```

Skipping this edit is the classic bare-RN iOS failure: login completes in the browser, and the
promise from `authorize()` never settles.

### 3c. The Keycloak side — the client's redirect URIs

Public client, standard flow on. Add the **full URI**, not the scheme:

```
com.example.myapp.auth://oauth2redirect
```

See `client-registration-mcp.md` (Phase Two) or `client-registration.md` (self-managed). Two client
settings matter specifically for mobile:

| Setting (Admin console) | Value | Failure if wrong |
|---|---|---|
| **Client authentication** | Off (public) | A secret in a JS bundle or an APK/IPA is a published secret. The library's own docs carry a warning page about client secrets for exactly this reason: `clientSecret` exists in the config type for non-compliant providers, and it is not for you. On a confidential client the token call fails `invalid_client`. |
| **Proof Key for Code Exchange Code Challenge Method** (Advanced tab) | `S256` | Blank means PKCE is *accepted* but not *required*, so an intercepted authorization code is still redeemable. Set it and Keycloak rejects any request from this client without a `code_challenge`. |

**Web origins are irrelevant here.** No browser JS makes the token call — the native layer does.
Don't set them, and don't chase CORS errors that cannot occur.

---

## Step 4: The auth flow

Keycloak's issuer is `https://<host>/realms/<realm>`. **Not `/auth/realms/`** — that prefix was
dropped in Keycloak 17 with the move to Quarkus. This library's own Keycloak provider page still
shows the old `/auth/realms/` form; it is stale. An old URL 404s at discovery and surfaces as
`service_configuration_fetch_error`.

```js
import { authorize, refresh, logout } from 'react-native-app-auth';

const config = {
  issuer: 'https://keycloak.example.com/realms/acme',
  clientId: 'acme-mobile',
  redirectUrl: 'com.example.myapp.auth://oauth2redirect',   // must match Step 3 exactly
  scopes: ['openid', 'profile', 'email'],
  // usePKCE defaults to true. Leave it. Setting it false disables the code_challenge,
  // and a client with the challenge method pinned to S256 then rejects every request.
};

export async function login() {
  const result = await authorize(config);
  await saveTokens(result);
  return result;
}
```

`authorize()` resolves with:

| Field | Notes |
|---|---|
| `accessToken` | Bearer token for your API |
| `accessTokenExpirationDate` | ISO 8601 **string**, not a number. Compare with `new Date(...)`. |
| `idToken` | Needed for logout — keep it |
| `refreshToken` | Long-lived, replayable. Keychain/Keystore only. |
| `tokenType`, `scopes` | `'Bearer'`, and the granted scopes |
| `authorizationCode`, `codeVerifier` | Only populated when `skipCodeExchange: true` |

### Refresh

```js
export async function refreshTokens(refreshToken) {
  const result = await refresh(config, { refreshToken });
  // Keycloak rotates refresh tokens: `result.refreshToken` may be a NEW value, or null when
  // the server did not issue one. Persist the new value if present, keep the old one if null.
  await saveTokens({
    ...result,
    refreshToken: result.refreshToken ?? refreshToken,
  });
  return result;
}
```

Dropping a rotated refresh token is a slow-burn bug: everything works until the first refresh, then
the next one fails `invalid_grant` and the user is logged out for no apparent reason.

There is no `performActionWithFreshTokens` equivalent here — the JS API gives you the raw tokens.
Check `accessTokenExpirationDate` before each API call and refresh when it is past, with a margin
(30–60s) for clock skew.

---

## Step 5: Secure token storage

**Never `AsyncStorage`.** It is an unencrypted key-value store — the library's own docs say so
outright. On Android it is a plain file in the app container; on iOS it is in the backup.

| Project | Use |
|---|---|
| Expo | `expo-secure-store` — iOS Keychain, Android `SharedPreferences` encrypted with the Android Keystore |
| Bare RN | `react-native-keychain` — iOS Keychain, Android Keystore-backed |

### Expo

```js
import * as SecureStore from 'expo-secure-store';

const KEY = 'kc.refreshToken';

export async function saveTokens({ refreshToken }) {
  await SecureStore.setItemAsync(KEY, refreshToken, {
    keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
  });
}

export const loadRefreshToken = () => SecureStore.getItemAsync(KEY);
export const clearTokens = () => SecureStore.deleteItemAsync(KEY);
```

**Store the refresh token, keep the access token in memory.** Expo's SecureStore docs warn that
large payloads can be rejected by the platform and that some iOS releases refused values above
roughly 2048 bytes. A Keycloak access token is a JWT carrying realm and client roles and routinely
exceeds that — writing the whole `authorize()` result as one JSON blob is how this breaks, on iOS
only, once a user accumulates enough roles. The access token is short-lived anyway; re-derive it
from the refresh token on cold start.

`AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY` keeps the item out of iCloud Keychain and off restored
devices, while still allowing a background refresh while the screen is locked.

### Bare React Native

```js
import * as Keychain from 'react-native-keychain';

const SERVICE = 'com.example.myapp.auth';

export async function saveTokens({ refreshToken }) {
  await Keychain.setGenericPassword('kc', refreshToken, {
    service: SERVICE,
    accessible: Keychain.ACCESSIBLE.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
  });
}

export async function loadRefreshToken() {
  const creds = await Keychain.getGenericPassword({ service: SERVICE });
  return creds ? creds.password : null;   // getGenericPassword resolves to `false` when empty
}

export const clearTokens = () => Keychain.resetGenericPassword({ service: SERVICE });
```

`getGenericPassword` resolves to `false` — not `null`, not a throw — when nothing is stored. Code
that destructures the result directly crashes on first launch.

Also set `android:allowBackup="false"` (or a `dataExtractionRules` exclusion) so the token does not
ride out in a cloud backup.

---

## Logout

Clearing local storage logs the user out of your app only. The Keycloak SSO session survives in the
system browser, so the next login silently re-authenticates and looks broken. To end it:

```js
await logout(
  { issuer: config.issuer, clientId: config.clientId },
  {
    idToken: storedIdToken,
    postLogoutRedirectUrl: 'com.example.myapp.auth://logout',
  }
);
await clearTokens();
```

`logout()` needs the **`idToken`** — it becomes the `id_token_hint` Keycloak uses to identify the
session and the client. Without it Keycloak cannot resolve which client is logging out and the
redirect is rejected.

**Keycloak validates the post-logout URI separately from the login one.** Since Keycloak 19 the
client has a **Valid post logout redirect URIs** field; if it is empty, the redirect after logout
fails with an invalid-redirect error even though login works. Either add
`com.example.myapp.auth://logout` there, or set the field to `+`, which reuses the Valid Redirect
URIs list.

---

## Verify

Do all six. Steps 1–4 pass on a wrong configuration; only 5 and 6 catch the redirect mismatch.

1. **It builds.** Expo: `npx expo prebuild --clean` completes. Android: no manifest-merger complaint
   about `${appAuthRedirectScheme}`.
2. **Expo only — confirm the plugin actually ran.** Grep the generated projects:
   `grep -r appAuthRedirectScheme android/app/build.gradle` and
   `grep -A3 CFBundleURLSchemes ios/*/Info.plist`. If either is missing, the plugin is not in
   `app.json` or `prebuild` was not re-run. "Package does not contain a valid config plugin" means
   the install is stale — `npx expo install --fix`, then `prebuild --clean`.
3. **You are not in Expo Go.** If the app is running under Expo Go, stop — OAuth cannot work there.
   Build a Development Build.
4. Confirm the scheme is live. iOS simulator:
   `xcrun simctl openurl booted "com.example.myapp.auth://oauth2redirect?test=1"` must foreground the
   app. Android: `adb shell am start -a android.intent.action.VIEW -d "com.example.myapp.auth://oauth2redirect?test=1"`.
5. Call `authorize()` on a real device or emulator with a browser installed. A Custom Tab (Android)
   or the iOS consent sheet plus Safari chrome must appear, showing
   `https://keycloak.example.com/realms/acme/protocol/openid-connect/auth?...`. If it is a view
   inside your app, something is using a WebView.
6. Read the `redirect_uri=` parameter out of that URL bar and compare it character for character
   against the value on the Keycloak client. Then complete login, kill the app, relaunch, and confirm
   `refresh()` restores the session — that proves secure storage worked.

Decode the access token and confirm `iss` matches your issuer exactly, and `azp` is `acme-mobile`.

---

## Troubleshooting

Error codes below are the `code` field on the rejected `Error`.

| Symptom | Cause | Fix |
|---|---|---|
| `Invalid parameter: redirect_uri` on Keycloak's page, before the login form | the URI the app sent is not on the client | Compare the `redirect_uri` query parameter to the registered value; check `://` vs `:/`, case, trailing slash |
| `service_configuration_fetch_error` | issuer URL wrong, or `/auth/` prefix left in from a pre-17 tutorial or this library's stale Keycloak page | `curl https://<host>/realms/<realm>/.well-known/openid-configuration` and use whatever URL returns JSON |
| `authorize()` never settles on iOS (bare RN) | the AppDelegate `openURL` edit is missing | Step 3b — and use the variant matching your React Native version; 0.77+ needs the Swift form plus a bridging header |
| `authorize()` never settles, and deep links work | your OAuth scheme collides with React Navigation's linking scheme | Give auth its own scheme (`com.example.myapp.auth`) in both the app config and Keycloak |
| Android build fails: `Attribute data@scheme ... requires a placeholder substitution` | `appAuthRedirectScheme` not set | Step 3b (bare) or run `prebuild` (Expo) |
| Login completes, `ERR_UNKNOWN_URL_SCHEME`, app never returns | the scheme Keycloak redirects to is not the one the app claimed | Make the placeholder / plugin scheme and the Keycloak URI's scheme identical |
| Redirect stopped working after an `app.json` edit | `prebuild` was not re-run, so the native projects still hold the old scheme | `npx expo prebuild --clean` |
| Anything OAuth fails in Expo Go | Expo Go cannot customize the app scheme — no library works around this | Build a Development Build (`expo-dev-client` + `prebuild` + `run:ios`/`run:android` or EAS) |
| `browser_not_found` (Android) | no browser on the device — common on bare emulator images | Use an emulator image with Google APIs, or install Chrome |
| `token_refresh_failed` / `invalid_grant` after the first successful refresh | a rotated refresh token was not persisted | Persist `result.refreshToken` when it is non-null; keep the previous value when it is null |
| `invalid_client` at the token exchange | the Keycloak client is confidential | Turn Client authentication off. Never fix this by putting `clientSecret` in the config. |
| Works on Android, fails on iOS only, for some users | a value over ~2048 bytes written to SecureStore | Store only the refresh token; keep the access token in memory |
| Crash on first launch reading stored credentials | `getGenericPassword` resolves to `false`, not `null` | Guard the result before destructuring |
| `authentication_failed` right after the consent sheet | user cancelled | Normal cancellation — treat it as "not logged in", not an error |
| Logout redirect fails but login works | **Valid post logout redirect URIs** is empty on the client | Add the logout URI, or set the field to `+` |
| Second login shows the form again despite an active SSO session | `iosPrefersEphemeralSession` / `androidPrefersEphemeralSession` is true — no shared cookie jar | Drop them unless you deliberately want a private session |
