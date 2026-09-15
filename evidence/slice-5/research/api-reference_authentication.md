> ## Documentation Index
> Fetch the complete documentation index at: https://docs.novig.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Authentication

> OAuth 2.0 authentication for the NBX API

The NBX API uses **OAuth 2.0 Client Credentials** with JSON Web Tokens (JWT).

<Note>
  Access tokens expire **30 minutes** after issuance. Request a new token when your current one expires.
</Note>

## 1. Obtain Credentials

Request your client ID and secret from Novig.

## 2. Request an Access Token

Send a POST request to the OAuth endpoint:

```bash theme={null}
curl --request POST \
  --url https://api.novig.com/nbx/v1/auth/emm-token \
  --header "Content-Type: application/json" \
  --data '{
    "grant_type": "client_credentials",
    "client_id": "YOUR_CLIENT_ID",
    "client_secret": "YOUR_CLIENT_SECRET"
  }'
```

## 3. Use the Token

Include the token in your requests by setting the HTTP header:

```bash theme={null}
Authorization: Bearer YOUR_ACCESS_TOKEN
```

<Note>
  For integration in the **QA environment**, use a different endpoint:

  | Setting      | QA Value                  |
  | ------------ | ------------------------- |
  | API Base URL | `https://api-qa.novig.us` |
</Note>

<Note>
  Both environments are hosted in **AWS `us-east-1`**. Novig does not offer AWS PrivateLink at this time.
</Note>
