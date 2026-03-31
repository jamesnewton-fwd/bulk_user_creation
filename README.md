# bulk_user_creation

A small command-line tool to bulk create users on the Forward SaaS platform from a CSV file.

The script uses `https://fwd.app` hardcoded as host (cannot be changed).

On startup, it will prompt the user for an 'API Key' and 'API Secret', and sends a Basic Auth header. The API credentials given must have the required level of access to create new users in the networks specified.

## Usage

To run the script simply script you must specify the location of the .csv file where your user data is located. This is the only mandatory argument. 

```
bulk_user_creation.py --csv example.csv
```

## CSV format

Columns should be at minimum:

- `email`
- `networks` (Single network, or comma seperated list of networks)

Optional fields:

- `username` (defaults to `email` if omitted)
- `isSupport` (defaults to `false` if omitted)
- `enabled` (defaults to `true` if omitted)
- `roles` (single role or comma-separated roles corresponding to each network)

If `roles` is omitted when `networks` is provided, `OPERATOR` is used for all networks.

## Example CSV

```csv
email,username,password,isSupport,enabled
me@example.com,me@example.com,zF4H+K;5]qE~%9G=nbAk,false,true
```

