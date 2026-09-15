---
updatedAt: 2026-09-10T16:43:24.000Z
---

Fetch the complete documentation index at: https://docs.prophetx.co/llms.txt. Use this file to discover all available pages before exploring further. Append .md to any documentation page URL to get its markdown version.

# Production Transition / Going Live

Move your Trading API integration from sandbox to production by creating production credentials and updating your base URL.

Move your Trading API integration from sandbox to production by creating production credentials and updating your base URL.

## Prepare your production account

1. Create your production ProphetX account.
2. Generate production access and secret keys. Do not reuse sandbox credentials in production.
3. Review the [Trading API reference](/reference/post_auth-login) before you deploy.

## Update your production configuration

Set your production `BASE_URL` to:

```text
https://cash.api.prophetx.co/partner
```

Update your deployment configuration, secrets store, and any environment variables that contain sandbox credentials or the sandbox base URL.

## Generate API tokens

After your account is approved for API access:

1. Sign in to [ProphetX](https://www.prophetx.co/?currency=cash).
2. Open the menu and select **API integration**.
3. Select **Create a new token**.

You can create multiple tokens for separate integration processes and revoke an individual token without interrupting the others.