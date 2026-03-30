#!/usr/bin/env python3
"""Bulk user creation tool for CSV-driven API user provisioning."""

import argparse
import base64
import csv
import datetime
import getpass
import http.client
import json
import os
import secrets
import string
import sys
import time
from typing import Dict, Iterable, List, Optional, Tuple

BOOLEAN_TRUE = {"true", "yes", "1", "on"}
BOOLEAN_FALSE = {"false", "no", "0", "off"}


def parse_headers(header_list: Iterable[str]) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    for header in header_list:
        if ":" not in header:
            raise ValueError(f"Invalid header format: '{header}'. Use 'Name: Value'.")
        name, value = header.split(":", 1)
        headers[name.strip()] = value.strip()
    return headers


def write_debug_log(log_file: Optional[str], messages: List[str]) -> None:
    if not log_file:
        return
    with open(log_file, "a", encoding="utf-8") as fp:
        fp.write("\n".join(messages))
        fp.write("\n\n")


def parse_network_roles(networks_raw: Optional[str], roles_raw: Optional[str]) -> List[Tuple[str, str]]:
    if not networks_raw:
        return []

    networks = [n.strip() for n in str(networks_raw).split(",") if n.strip()]
    if not networks:
        return []

    if roles_raw is None or str(roles_raw).strip() == "":
        roles = ["OPERATOR"] * len(networks)
    else:
        roles = [r.strip().upper() for r in str(roles_raw).split(",") if r.strip()]
        if len(roles) == 1:
            roles *= len(networks)

    if len(roles) != len(networks):
        raise ValueError(
            f"Network count ({len(networks)}) does not match role count ({len(roles)})."
        )

    allowed = {"ADMIN", "OPERATOR", "READ_ONLY"}
    pairs: List[Tuple[str, str]] = []
    for net, role in zip(networks, roles):
        if role not in allowed:
            raise ValueError(f"Role '{role}' is invalid; expected ADMIN, OPERATOR, or READ_ONLY.")
        pairs.append((net, role))

    return pairs


def normalize_value(value: str):
    if value is None:
        return None
    text = value.strip()
    if text == "":
        return None
    lower = text.lower()
    if lower in BOOLEAN_TRUE:
        return True
    if lower in BOOLEAN_FALSE:
        return False
    return text


def generate_password(length: int = 20) -> str:
    # Strong password but avoid quotes and commas to prevent CSV quoting issues.
    excluded = '",'
    characters = ''.join(c for c in (string.ascii_letters + string.digits + string.punctuation) if c not in excluded)
    return "".join(secrets.choice(characters) for _ in range(length))


def load_users(csv_path: str) -> Tuple[List[Dict[str, object]], List[Dict[str, str]], List[str]]:
    with open(csv_path, newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames is None:
            raise ValueError(f"CSV file '{csv_path}' has no header row.")

        fieldnames = list(reader.fieldnames)
        has_password_column = any(fn.lower() == "password" for fn in fieldnames)

        users: List[Dict[str, object]] = []
        rows: List[Dict[str, str]] = []
        for row_number, row in enumerate(reader, start=2):
            rows.append(row)
            payload = {}
            for key, raw_value in row.items():
                if key is None:
                    continue
                if key.lower() in {"networks", "roles"}:
                    continue

                normalized_key = key
                if key.lower() == "email":
                    normalized_key = "email"
                elif key.lower() == "username":
                    normalized_key = "username"
                elif key.lower() == "password":
                    normalized_key = "password"
                elif key.lower() == "issupport":
                    normalized_key = "isSupport"
                elif key.lower() == "enabled":
                    normalized_key = "enabled"

                normalized_value = normalize_value(raw_value)
                if normalized_value is None:
                    continue
                payload[normalized_key] = normalized_value

            if "email" not in payload:
                raise ValueError(f"CSV row {row_number} must include at least 'email'.")

            if "username" not in payload:
                payload["username"] = payload["email"]
            if "isSupport" not in payload:
                payload["isSupport"] = False
            if "enabled" not in payload:
                payload["enabled"] = True

            networks_value = row.get("networks") or row.get("Networks")
            roles_value = row.get("roles") or row.get("Roles")
            network_roles = parse_network_roles(networks_value, roles_value)

            users.append({
                "payload": payload,
                "network_roles": network_roles,
            })

        if not has_password_column:
            fieldnames.append("password")

        return users, rows, fieldnames


def build_connection(scheme: str, host: str, timeout: Optional[float]) -> http.client.HTTPConnection:
    if scheme == "https":
        return http.client.HTTPSConnection(host, timeout=timeout)
    return http.client.HTTPConnection(host, timeout=timeout)


def send_user_request(
    conn: http.client.HTTPConnection,
    api_path: str,
    headers: Dict[str, str],
    payload: Dict[str, object],
    log_file: Optional[str] = None,
) -> Tuple[int, str]:
    body = json.dumps(payload)
    write_debug_log(log_file, [
        f"[REQUEST] POST {api_path}",
        f"Headers: {json.dumps(headers)}",
        f"Body: {body}",
    ])
    conn.request("POST", api_path, body, headers)
    response = conn.getresponse()
    response_body = response.read().decode("utf-8")
    write_debug_log(log_file, [
        f"[RESPONSE] {response.status} {response.reason}",
        f"Body: {response_body}",
    ])
    return response.status, response_body


def send_role_assignment(
    conn: http.client.HTTPConnection,
    template: str,
    user_id: str,
    network_id: str,
    role: str,
    headers: Dict[str, str],
    log_file: Optional[str] = None,
) -> Tuple[int, str]:
    path = template.format(user_id=user_id, network_id=network_id, role=role)
    write_debug_log(log_file, [
        f"[REQUEST] POST {path}",
        f"Headers: {json.dumps(headers)}",
        "Body: ",
    ])
    conn.request("POST", path, "", headers)
    response = conn.getresponse()
    response_body = response.read().decode("utf-8")
    write_debug_log(log_file, [
        f"[RESPONSE] {response.status} {response.reason}",
        f"Body: {response_body}",
    ])
    return response.status, response_body


def run_cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bulk create users from a CSV file via an HTTP API."
    )
    parser.add_argument(
        "--csv",
        dest="csv_path",
        required=True,
        help="Path to the CSV file containing user rows.",
    )
    parser.add_argument(
        "--api-path",
        default="/api/users",
        help="Request path for user creation (default: /api/users).",
    )
    parser.add_argument(
        "--api-key",
        help="API key for basic auth. If omitted, prompts at runtime.",
    )
    parser.add_argument(
        "--api-secret",
        help="API secret for basic auth. If omitted, prompts at runtime.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Log full API requests and responses to a file.",
    )
    parser.add_argument(
        "--log-file",
        default="logs/api_calls.log",
        help="Path to write verbose API debug logs (default: logs/api_calls.log).",
    )
    parser.add_argument(
        "--header",
        action="append",
        default=[],
        help="Additional HTTP header to send, in the form 'Name: Value'. Can be repeated.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Seconds to wait between requests (default: 0).",
    )
    parser.add_argument(
        "--role-path",
        default="/api/users/{user_id}/roles/network/{network_id}?role={role}",
        help="Template for network role assignment path."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print payloads without sending requests.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Connection timeout in seconds (default: 30).",
    )

    args = parser.parse_args(argv)

    api_key = args.api_key or input("API Key: ")
    api_secret = args.api_secret or getpass.getpass("API Secret: ")
    basic_token = (f"{api_key}:{api_secret}").encode("utf-8")
    auth_value = "Basic " + base64.b64encode(basic_token).decode("ascii")

    log_file = args.log_file if args.verbose else None
    if args.verbose:
        log_dir = os.path.dirname(log_file) or "."
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        with open(log_file, "w", encoding="utf-8") as fp:
            fp.write(f"API debug log started at {datetime.datetime.utcnow().isoformat()}Z\n\n")

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": auth_value,
    }

    try:
        headers.update(parse_headers(args.header))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    try:
        users, rows, fieldnames = load_users(args.csv_path)
    except Exception as exc:
        print(f"Failed to load users from CSV: {exc}", file=sys.stderr)
        return 1

    missing_password_indices = [
        idx for idx, user_entry in enumerate(users)
        if "password" not in user_entry["payload"]
    ]
    if missing_password_indices:
        confirm = input(
            f"{len(missing_password_indices)} user(s) have blank passwords. "
            "Generate 20-char random passwords and write back to CSV? [y/N]: "
        ).strip().lower()
        if confirm == "y":
            password_column = next(
                (fn for fn in fieldnames if fn.lower() == "password"), "password"
            )
            for idx in missing_password_indices:
                generated = generate_password(20)
                users[idx]["payload"]["password"] = generated

                # update original row representation for CSV writeback
                rows[idx][password_column] = generated

            with open(args.csv_path, "w", newline="", encoding="utf-8") as csv_file:
                writer = csv.DictWriter(
                    csv_file,
                    fieldnames=fieldnames,
                    quoting=csv.QUOTE_MINIMAL,
                )
                writer.writeheader()
                writer.writerows(rows)

            print(f"Generated passwords for {len(missing_password_indices)} user(s) and updated CSV.")

    if args.dry_run:
        print(f"Dry run enabled: {len(users)} user(s) loaded from {args.csv_path}")
        for index, user_entry in enumerate(users, start=1):
            print(f"--- user #{index} ---")
            print(json.dumps(user_entry["payload"], indent=2))
        return 0

    fixed_host = "fwd.app"
    fixed_scheme = "https"
    print(f"Sending {len(users)} user creation requests to {fixed_scheme}://{fixed_host}{args.api_path}")
    if args.verbose:
        print(f"Verbose API logging enabled; writing to {log_file}")
    for index, user_entry in enumerate(users, start=1):
        payload = user_entry["payload"]
        network_roles = user_entry.get("network_roles", [])

        print(f"[{index}/{len(users)}] Creating user {payload.get('email')}")
        user_id = None
        try:
            conn = build_connection(fixed_scheme, fixed_host, args.timeout)
            status, body = send_user_request(conn, args.api_path, headers, payload, log_file)
            conn.close()
            print(f"  -> HTTP {status}")
            if body:
                print(f"  -> {body}")
            if status < 200 or status >= 300:
                print(f"  ! Request failed for {payload.get('email')}", file=sys.stderr)
            else:
                try:
                    parsed = json.loads(body)
                    user_id = (
                        parsed.get("id")
                        or parsed.get("user_id")
                        or (parsed.get("data") or {}).get("id")
                    )
                except Exception:
                    user_id = None
                    print("  ! Could not parse user ID from response for role assignments", file=sys.stderr)

        except Exception as exc:
            print(f"  ! Error creating {payload.get('email')}: {exc}", file=sys.stderr)

        if user_id and network_roles:
            print(f"  -> Assigning {len(network_roles)} network role(s) for user_id={user_id}")
            for network_id, role in network_roles:
                print(f"    - Network {network_id} -> role {role}")
                try:
                    conn = build_connection(fixed_scheme, fixed_host, args.timeout)
                    rstatus, rbody = send_role_assignment(
                        conn,
                        args.role_path,
                        str(user_id),
                        network_id,
                        role,
                        headers,
                        log_file,
                    )
                    conn.close()
                    print(f"      -> HTTP {rstatus}")
                    if rbody:
                        print(f"      -> {rbody}")
                    if rstatus < 200 or rstatus >= 300:
                        print(
                            f"      ! Role assignment failed for user {user_id} network {network_id} role {role}",
                            file=sys.stderr,
                        )
                except Exception as exc:
                    print(
                        f"      ! Error assigning role {role} for network {network_id} to user {user_id}: {exc}",
                        file=sys.stderr,
                    )

        if args.delay > 0 and index < len(users):
            time.sleep(args.delay)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
