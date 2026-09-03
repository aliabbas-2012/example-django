# Postman collection

`example-django-auth-api.postman_collection.json` exercises the full auth + wallet
API against a plain host venv run -- no Docker `app` container needed.

## Run it

```bash
source .venv/bin/activate
python manage.py runserver
```

Import the collection into Postman, or run it headlessly with [newman](https://github.com/postmanlabs/newman):

```bash
npx newman run postman/example-django-auth-api.postman_collection.json
```

Folders run in order (top to bottom matters -- test scripts in earlier requests
populate the collection variables later ones depend on):

1. **Auth** -- register, login, `/me`, refresh (rotation), logout, then a refresh
   with the now-blacklisted token to prove logout actually revoked it.
2. **Wallets** -- list/retrieve, a second `create` that hits the unique
   constraint cleanly, a `PATCH` trying to smuggle a balance change (has no
   effect -- `balance` is read-only), and `credit`.
3. **401 vs 403 (two users)** -- registers a second user (Bob) and has him hit
   the first user's wallet: both come back `403`, not `404` or `401`, because
   `IsWalletOwner` (Q13) runs only after authentication already succeeded.
4. **Cleanup** -- deletes the wallet. Runs last on purpose, so folder 3 still
   has a real wallet to test against.

Verified end-to-end with `newman` against a live `runserver` on 2026-09-03:
17 requests, 20 assertions, 0 failures.
