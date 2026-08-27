# iOS (Swift) — native login with AppAuth-iOS, ASWebAuthenticationSession, and PKCE

## What this is

Wiring authorization-code + PKCE login into a Swift iOS app using
[AppAuth-iOS](https://github.com/openid/AppAuth-iOS), the OpenID Foundation's RFC 8252 reference
client. AppAuth presents an `ASWebAuthenticationSession`, the user authenticates on Keycloak's own
page, and the callback returns to a custom URI scheme the app has registered.

Read `pattern-integration-decision.md` first — it settles where tokens live (Keychain), which grant
(auth code + PKCE), and why a mobile client is always `public`. This file does not repeat those
decisions; it implements them.

**Verified against:** AppAuth-iOS **3.0.0** (released 2026-08-24), Keycloak 26.x. Checked 2026-08-27.
API shapes taken from the 3.0.0 headers and the repo's own SwiftUI/SPM example.

---

## The rule that decides everything else: system browser, never a WebView

AppAuth refuses to run the flow in a `WKWebView`. Do not route around it.

| If you use | What happens |
|---|---|
| **`ASWebAuthenticationSession`** (what AppAuth does on iOS 15+) | Credentials are typed into a Safari-backed process your app cannot read. It shares Safari's cookie jar, so an existing Keycloak SSO session signs the user in without a prompt. iOS shows a one-time consent sheet naming the domain — that sheet is the security boundary working. |
| A `WKWebView` | Your app can read every keystroke and cookie, so **the user is handing you their password** — including the password of whatever IdP Keycloak brokers to. Isolated cookie jar, so **SSO breaks** and every app re-prompts. Google and other IdPs reject it by User-Agent, and App Review has rejected apps for it. |

AppAuth's README says `UIWebView` and `WKWebView` are explicitly not supported, citing RFC 8252
§8.12.

Two version-specific consequences of that design:

- **2.1.0 removed the Safari fallback.** If `ASWebAuthenticationSession` cannot start — Guided
  Access is the documented case — the flow now fails with an error instead of quietly opening an
  external browser. Handle the error; don't treat "no browser appeared" as a hang.
- `prefersEphemeralSession: true` gives you a private session with no shared cookies. That is a
  deliberate anti-SSO switch. Set it only when you *want* the user re-prompted every time.

---

## Step 1: The dependency

### Swift Package Manager (preferred)

In Xcode: **File → Add Package Dependencies →** `https://github.com/openid/AppAuth-iOS.git`, rule
**Up to Next Major** from `3.0.0`. Add the **`AppAuth`** product to your app target.

In a `Package.swift`:

```swift
dependencies: [
    .package(url: "https://github.com/openid/AppAuth-iOS.git", .upToNextMajor(from: "3.0.0"))
]
```

The README in the repo still shows `from: "1.3.0"`. That snippet is stale — do not copy it.

### CocoaPods

```ruby
pod 'AppAuth', '~> 3.0'
```

### Which major version you can use

| Version | Minimum iOS | Builds with | Pick it when |
|---|---|---|---|
| **3.0.0** | iOS 15 | Xcode 27 (SPM needs Swift 5.7 / Xcode 14+ to resolve) | Default for new work |
| 2.x | iOS 12 | Xcode 26 and earlier | You must still support iOS 12–14, or your CI is not on Xcode 27 |

3.0.0 is a breaking release cut specifically for Xcode 27. The break that will hit you:
`resumeExternalUserAgentFlowWithURL:error:` became a **required** member of
`OIDExternalUserAgentSession`, and Swift now spells it `resumeExternalUserAgentFlow(_:)`. Migrating
from 2.1.0, replace `try session.resumeExternalUserAgentFlow?(with: url)` with
`try session.resumeExternalUserAgentFlow(url)`. Objective-C callers are unaffected.

Two products exist: **`AppAuthCore`** is protocol-only with no UI, **`AppAuth`** adds the iOS/macOS
user agents. Link `AppAuth`; linking only `AppAuthCore` compiles and then fails at runtime with no
way to present the browser.

---

## Step 2: Choose the redirect URI

Use a custom scheme in reverse-domain form, distinct from any scheme the app already handles:

```
com.example.myapp.auth:/oauth2redirect
```

- Keep it **lowercase** and unique to auth. If your app already registers `com.example.myapp` for
  deep links, use `com.example.myapp.auth` — otherwise the callback is delivered to your deep-link
  router and AppAuth's session times out.
- `:/oauth2redirect` and `://oauth2redirect` are **different strings** to Keycloak. Pick one and use
  that exact spelling in both places in Step 3.

Universal Links (`https://app.example.com/oauth2redirect`) are stronger — a custom scheme can be
claimed by any other installed app — but need an `apple-app-site-association` file on the domain and
the `continue userActivity:` delegate path. Start with a custom scheme.

---

## Step 3: Register the redirect in BOTH places

**This is the most common failure in the whole integration, and each half fails differently.**

| Registered in | Missing from | Symptom |
|---|---|---|
| Keycloak client | `Info.plist` | The consent sheet appears, login completes, and then nothing comes back — the session times out or the user is left staring at Safari. AppAuth's own example asserts on a missing `CFBundleURLSchemes` at startup precisely because this is silent otherwise. |
| `Info.plist` | Keycloak client | **`Invalid parameter: redirect_uri`** on Keycloak's error page, before the login form renders. |

### 3a. The app side — `Info.plist`

Right-click `Info.plist` → **Open As → Source Code**:

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

`CFBundleURLSchemes` holds the **scheme only** — everything before the `:` — not the whole URI.
`CFBundleURLName` is any globally unique identifier; the bundle ID is the convention.

On iOS 15+ with the default user agent, the callback URL is actually delivered through
`ASWebAuthenticationSession`'s own completion handler, which matches on `callbackURLScheme` — so the
app-delegate hop in Step 4 is a fallback, not the primary path. Register the scheme anyway: it is
what AppAuth documents, it is required for the app-delegate resume path, for Universal Links, and
for any non-default external user agent, and Apple expects a scheme passed as `callbackURLScheme` to
be one the app can handle.

### 3b. The Keycloak side — the client's redirect URIs

Public client, standard flow on. Add the **full URI**, not the scheme:

```
com.example.myapp.auth:/oauth2redirect
```

See `client-registration-mcp.md` (Phase Two) or `client-registration.md` (self-managed). Two client
settings matter specifically for mobile:

| Setting (Admin console) | Value | Failure if wrong |
|---|---|---|
| **Client authentication** | Off (public) | A secret in an `.ipa` is a published secret — the binary can be unpacked. On a confidential client the token call fails `invalid_client`. |
| **Proof Key for Code Exchange Code Challenge Method** (Advanced tab) | `S256` | Blank means PKCE is *accepted* but not *required*, so an intercepted authorization code is still redeemable. Set it and Keycloak rejects any request from this client without a `code_challenge`. |

**Web origins are irrelevant here.** No browser JS makes the token call — `URLSession` inside the app
does. Don't set them, and don't chase CORS errors that cannot occur.

---

## Step 4: The auth flow

Keycloak's issuer is `https://<host>/realms/<realm>`. **Not `/auth/realms/`** — that prefix was
dropped in Keycloak 17 with the move to Quarkus. An old tutorial's URL 404s at discovery and
surfaces as "Error retrieving discovery document".

### Hold the session somewhere that outlives the call

```swift
import AppAuth
import UIKit

class AppDelegate: NSObject, UIApplicationDelegate {
    var currentAuthorizationFlow: OIDExternalUserAgentSession?

    func application(_ app: UIApplication,
                     open url: URL,
                     options: [UIApplication.OpenURLOptionsKey: Any] = [:]) -> Bool {
        if let flow = currentAuthorizationFlow {
            do {
                try flow.resumeExternalUserAgentFlow(url)   // AppAuth 3.x Swift spelling
                currentAuthorizationFlow = nil
                return true
            } catch {
                // A benign mismatch: the URL belongs to some other handler. Fall through.
                print("Authorization flow could not handle URL: \(error.localizedDescription)")
            }
        }
        return false
    }
}
```

In SwiftUI, attach it with `@UIApplicationDelegateAdaptor(AppDelegate.self)`. **The session must be
strongly retained.** If you drop the return value of `authState(byPresenting:)` into a local, ARC
releases it, the browser is dismissed, and login appears to do nothing.

### Discover, request, exchange

```swift
final class AuthManager: NSObject, ObservableObject {

    private let issuer = URL(string: "https://keycloak.example.com/realms/acme")!
    private let clientID = "acme-ios"
    private let redirectURI = URL(string: "com.example.myapp.auth:/oauth2redirect")!

    @Published private(set) var authState: OIDAuthState?
    weak var appDelegate: AppDelegate?

    var isAuthorized: Bool { authState?.isAuthorized ?? false }

    func login(presenting viewController: UIViewController) {
        OIDAuthorizationService.discoverConfiguration(forIssuer: issuer) { [weak self] config, error in
            guard let self, let config else {
                // Wrong issuer, no network, or an untrusted TLS cert.
                print("Discovery failed: \(error?.localizedDescription ?? "unknown")")
                return
            }

            // This initializer generates a secure `state` AND PKCE with S256 automatically.
            // Public client: use the overload with no clientSecret at all.
            let request = OIDAuthorizationRequest(
                configuration: config,
                clientId: self.clientID,
                scopes: [OIDScopeOpenID, OIDScopeProfile, OIDScopeEmail],
                redirectURL: self.redirectURI,
                responseType: OIDResponseTypeCode,
                additionalParameters: nil
            )

            // authState(byPresenting:) performs the code exchange for you.
            self.appDelegate?.currentAuthorizationFlow = OIDAuthState.authState(
                byPresenting: request,
                presenting: viewController
            ) { authState, error in
                guard let authState else {
                    print("Authorization error: \(error?.localizedDescription ?? "unknown")")
                    return
                }
                self.setAuthState(authState)
            }
        }
    }

    private func setAuthState(_ state: OIDAuthState?) {
        authState = state
        // Fires on every silent refresh — this is how the rotated refresh token gets persisted.
        authState?.stateChangeDelegate = self
        authState?.errorDelegate = self
        AuthStore.save(state)
    }
}

extension AuthManager: OIDAuthStateChangeDelegate, OIDAuthStateErrorDelegate {
    func didChange(_ state: OIDAuthState) { AuthStore.save(state) }
    func authState(_ state: OIDAuthState, didEncounterAuthorizationError error: Error) {
        print("Authorization error: \(error)")
    }
}
```

**PKCE is on and you did not switch it on.** The header for that initializer states it creates the
request "with opinionated defaults (a secure `state`, and PKCE with S256 as the
`code_challenge_method`)". Reaching for the designated initializer to pass your own
`codeVerifier: nil` disables it — against a client with the challenge method pinned to `S256`, every
request then fails.

### Calling your API

Never read `lastTokenResponse?.accessToken` for a request — it may be expired.

```swift
authState?.performAction { accessToken, idToken, error in
    guard error == nil, let accessToken else {
        // Refresh failed: the Keycloak SSO session ended or the refresh token was revoked.
        // Send the user back through login().
        return
    }
    var request = URLRequest(url: URL(string: "https://api.example.com/me")!)
    request.allHTTPHeaderFields = ["Authorization": "Bearer \(accessToken)"]
    // URLSession.shared.dataTask(with: request) { ... }
}
```

`performAction` is `performActionWithFreshTokens:` bridged; the trailing closure drops the label. It
refreshes when needed and mutates the `OIDAuthState` in place, which fires `didChange(_:)` — that
delegate is what saves the rotated refresh token. Without it, a refresh survives only in memory and
the next cold start signs the user out holding a token Keycloak already invalidated.

---

## Step 5: Secure token storage — Keychain, not `UserDefaults`

`OIDAuthState` conforms to `NSSecureCoding`, so it archives to `Data` in one call. That archive
contains the refresh token — a long-lived, replayable credential. Treat it as a password.

**AppAuth's own example app writes it to `UserDefaults`.** That is example brevity, not guidance:
`UserDefaults` is an unencrypted plist inside the app container, readable from a device backup or a
jailbroken filesystem, and it is included in iCloud/iTunes backups by default. Do not ship it.

```swift
import Security

enum AuthStore {
    private static let service = "com.example.myapp.auth"
    private static let account = "authState"

    static func save(_ state: OIDAuthState?) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]
        SecItemDelete(query as CFDictionary)

        guard let state,
              let data = try? NSKeyedArchiver.archivedData(withRootObject: state,
                                                           requiringSecureCoding: true)
        else { return }

        var add = query
        add[kSecValueData as String] = data
        // ThisDeviceOnly keeps it out of iCloud Keychain and device-to-device backups.
        // AfterFirstUnlock lets a background refresh work while the screen is locked.
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(add as CFDictionary, nil)
    }

    static func load() -> OIDAuthState? {
        var query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne

        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data
        else { return nil }

        return try? NSKeyedUnarchiver.unarchivedObject(ofClass: OIDAuthState.self, from: data)
    }
}
```

Two accessibility choices worth making deliberately:

| Constant | Effect |
|---|---|
| `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` | Readable after the first unlock since boot. Background refresh works. Never leaves this device. **The default choice.** |
| `kSecAttrAccessibleWhenUnlockedThisDeviceOnly` | Only while the device is unlocked. Stricter; breaks background refresh, so a `performAction` from a background task fails with `errSecInteractionNotAllowed`. |

Drop `ThisDeviceOnly` only if you genuinely want the session to follow the user to a restored device
via iCloud Keychain — and note that widens who can obtain it.

---

## Logout

Clearing the Keychain entry logs the user out of your app only. The Keycloak SSO session survives in
Safari's cookie jar, so the next login silently re-authenticates and looks broken. To end it, send an
RP-initiated logout:

```swift
let endSession = OIDEndSessionRequest(
    configuration: config,
    idTokenHint: idToken,                                                  // from lastTokenResponse
    postLogoutRedirectURL: URL(string: "com.example.myapp.auth:/logout")!,
    additionalParameters: nil
)
let agent = OIDExternalUserAgentIOS(presenting: viewController)!
appDelegate.currentAuthorizationFlow = OIDAuthorizationService.present(
    endSession, externalUserAgent: agent
) { response, error in
    AuthStore.save(nil)
}
```

**UNVERIFIED:** the Swift spelling `OIDAuthorizationService.present(_:externalUserAgent:callback:)`
is the name Swift's Objective-C importer derives from the verified selector
`presentEndSessionRequest:externalUserAgent:callback:` (the same derivation that turns
`presentAuthorizationRequest:presentingViewController:callback:` into
`present(_:presenting:callback:)`, which the repo's Swift example does use). AppAuth ships no Swift
end-session sample to confirm it against. If it does not compile, let Xcode complete the `present`
overload on `OIDAuthorizationService` — the Objective-C selector above is the ground truth.

**Keycloak validates the post-logout URI separately from the login one.** Since Keycloak 19 the
client has a **Valid post logout redirect URIs** field; if it is empty, the redirect after logout
fails with an invalid-redirect error even though login works. Either add
`com.example.myapp.auth:/logout` there, or set the field to `+`, which reuses the Valid Redirect
URIs list.

---

## Verify

Do all five. Steps 1–3 pass on a wrong configuration; only 4 and 5 catch the redirect mismatch.

1. **It builds and links.** `import AppAuth` resolving but `OIDExternalUserAgentIOS` not found means
   you linked `AppAuthCore` instead of `AppAuth`.
2. Confirm the scheme is live: with the app installed on a simulator,
   `xcrun simctl openurl booted "com.example.myapp.auth:/oauth2redirect?test=1"` must foreground your
   app. If nothing happens, Step 3a is wrong.
3. Tap login on a device or simulator. iOS must show the "…Wants to Use…to Sign In" consent sheet
   naming your Keycloak host, then a Safari-chrome browser. If it is your own view, something is
   using a `WKWebView`.
4. Read the `redirect_uri=` parameter out of that browser's URL and compare it character for
   character against the value on the Keycloak client. This is the check that catches `:/` vs `://`.
5. Complete login, then **kill the app from the app switcher and relaunch**. The user must still be
   signed in — that proves the Keychain write happened and the refresh token works.

Decode the access token and confirm `iss` matches your issuer exactly, and `azp` is `acme-ios`.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Invalid parameter: redirect_uri` on Keycloak's page, before the login form | the URI the app sent is not on the client | Compare the `redirect_uri` query parameter to the registered value; check `:/` vs `://`, case, trailing slash |
| Browser opens, login succeeds, app never comes back | scheme missing from `Info.plist`, or it doesn't match the URI Keycloak redirects to | Step 3a; the plist holds the scheme only, and it must be the scheme half of the registered URI |
| Nothing happens when you tap login | the returned `OIDExternalUserAgentSession` was not retained | Assign it to a property that outlives the call — `appDelegate.currentAuthorizationFlow` |
| `OIDErrorCodeUserCanceledAuthorizationFlow` | user dismissed the sheet | Normal cancellation — treat it as "not logged in", not an error |
| Flow fails immediately with no browser, on a managed device | Guided Access blocks `ASWebAuthenticationSession`, and 2.1.0 removed the Safari fallback | Surface the error to the user; there is no fallback to restore |
| `invalid_grant` at the token exchange | PKCE verifier mismatch, or the code was already redeemed | Use the convenience initializer; don't hand-build the request with a nil `codeVerifier`, and don't reuse a response |
| Token exchange fails `invalid_client` | the Keycloak client is confidential | Turn Client authentication off. Never fix this by shipping the secret. |
| "Error retrieving discovery document" | issuer URL wrong, or `/auth/` prefix left in from a pre-17 tutorial | `curl https://<host>/realms/<realm>/.well-known/openid-configuration` and use whatever URL returns JSON |
| Compile error on `resumeExternalUserAgentFlow` after upgrading to 3.x | the method became required and was renamed for Swift | Replace `try session.resumeExternalUserAgentFlow?(with: url)` with `try session.resumeExternalUserAgentFlow(url)` |
| Xcode can't resolve the SPM package | 3.0.0 needs Swift 5.7 / Xcode 14+ to resolve, Xcode 27 to build | Upgrade Xcode, or pin to 2.x if you must stay on Xcode 26 or support iOS 12–14 |
| Logged out after every cold start despite a successful login | state never persisted, or persisted before the exchange | Save from `didChange(_:)` and from the `authState(byPresenting:)` callback |
| Background API call fails `errSecInteractionNotAllowed` | Keychain item is `WhenUnlocked` and the device is locked | Use `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` |
| Logout redirect fails but login works | **Valid post logout redirect URIs** is empty on the client | Add the logout URI, or set the field to `+` |
| Second login shows the form again despite an active SSO session | `prefersEphemeralSession: true` — no shared cookie jar | Drop it unless you deliberately want a private session |
