# Google sign-in

Citizens sign in with the "Continue with Google" button. Creating the Google credential is free; no
billing account is needed.

## How it works

1. The page asks the API for a one-use challenge (`POST /api/v1/auth/google/challenge`, valid
   5 minutes) and hands it to Google's button as the `nonce`.
2. Google returns a signed ID token containing that nonce.
3. `POST /api/v1/auth/google` verifies the token's signature, audience, issuer, expiry and verified
   email with the `google-auth` library, then consumes the nonce. A replayed token or a token
   issued for a different challenge is rejected with 401.
4. A citizen account is created on first sign-in. Google can never sign in to an existing staff
   account (403); staff use their own credentials.

The Client ID is public. There is no client secret in this flow and none is used.

## Setup

1. Open https://console.cloud.google.com and create (or pick) a project, for example `nagarsaathi`.
   Google Cloud now requires 2-step verification on your Google account first.
2. **Google Auth Platform → Branding/Audience:** set an app name, choose **External**, and add the
   Gmail addresses that may sign in as **Test users**. While the app is in *Testing*, only those
   addresses can sign in.
3. **Clients → Create client:** type **Web application**. Leave "Use this client for an AI-powered
   agent" unchecked.
4. **Authorized JavaScript origins:** add `http://localhost:5173` and `http://127.0.0.1:5173`.
   When you deploy, add the deployed origin too (`https://your-app.example`, no trailing slash).
   Leave redirect URIs empty.
5. Copy the **Client ID** (`...apps.googleusercontent.com`) into `.env`:

   ```
   GOOGLE_CLIENT_ID=<your-id>.apps.googleusercontent.com
   ```

6. Restart the API. The button appears once `/api/v1/auth/options` reports the Client ID.

## Delete or rotate the client secret

Google shows a client secret once when a client is created. This app does not use it, so it is safe
to remove:

1. **Google Auth Platform → Clients →** open your client.
2. Under **Client secrets**, click **Add secret** to create a replacement if you ever need one, then
   **Disable** and **Delete** the old secret. Deleting a secret that nothing uses has no effect on
   sign-in.
3. If a secret was ever pasted into chat, a screenshot or a commit, treat it as exposed and do the
   steps above.

## Troubleshooting

- *"Google sign-in is not configured"*: `GOOGLE_CLIENT_ID` is empty in the API's environment.
- *"Error 400: origin_mismatch"*: the page's origin is not listed under Authorized JavaScript
  origins. Changes can take a few minutes to apply.
- *"access_denied" / app not verified*: the Gmail address is not in the Test users list.
- *"Google sign-in expired or was already used"*: the 5-minute challenge elapsed or was used; the
  page fetches a fresh one automatically, try the button again.
