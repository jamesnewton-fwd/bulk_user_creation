# bulk_user_creation

A small command-line tool to bulk create users on an online platform from a CSV file.

## Usage

```bash
python bulk_user_creation.py --csv sample_users.csv
```

The script uses `https://fwd.app` hardcoded as host (cannot be changed).

On startup, it prompts for `API Key` and `API Secret`, and sends a Basic Auth header.

## CSV format

Columns should be at minimum:

- `email`
- `username`
- `password`
- `networks`
- `roles`

`networks` and `roles` are optional, and each row may include `isSupport` and `enabled` as well.

Optional fields:

- `username` (defaults to `email` if omitted)
- `isSupport` (defaults to `false` if omitted)
- `enabled` (defaults to `true` if omitted)
- `networks` (comma-separated network IDs)
- `roles` (single role or comma-separated roles corresponding to each network)

If `roles` is omitted when `networks` is provided, `OPERATOR` is used for all networks.

Additional columns are included in the JSON payload if present, but `networks` and `roles` are used for separate role assignment calls.

## Example headers

```bash
--header "Authorization: Bearer <token>"
```

## Example CSV

```csv
email,username,password,isSupport,enabled
me@example.com,me@example.com,zF4H+K;5]qE~%9G=nbAk,false,true
```

