#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path

import requests
from databricks.sdk import WorkspaceClient


DEFAULT_HOST = "https://dbc-de54b796-a6c4.cloud.databricks.com"
DEFAULT_PARENT_PATH = "/Workspace/Users/amit@mindint.org"
DEFAULT_SPACE_ID = "01f14d5383a21f0e8626a80d72315de3"
DEFAULT_TITLE = "BERTopic Narrative Agent"
DEFAULT_DESCRIPTION = (
    "Curated Genie Space for BERTopic narrative analysis over topic metadata, "
    "message-level incitement views, and SQL vector_search examples."
)
DEFAULT_WAREHOUSE_ID = "593af0ca865fa166"


def normalize_host(host: str) -> str:
    host = host.strip().rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = f"https://{host}"
    return host


def get_workspace_client(args: argparse.Namespace) -> WorkspaceClient:
    if args.profile:
        return WorkspaceClient(profile=args.profile)
    return WorkspaceClient(host=normalize_host(args.host or os.getenv("DATABRICKS_HOST", DEFAULT_HOST)))


def build_headers(workspace: WorkspaceClient) -> dict:
    headers = workspace.config.authenticate()
    if not headers.get("Authorization"):
        raise RuntimeError("Databricks SDK did not return an Authorization header.")
    return {**headers, "Content-Type": "application/json"}


def read_payload(path: Path) -> str:
    payload = json.loads(path.read_text())
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True)


def find_existing_space(
    host: str,
    headers: dict,
    title: str,
) -> dict | None:
    response = requests.get(
        f"{host}/api/2.0/genie/spaces",
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()
    spaces = response.json().get("spaces", [])
    for space in spaces:
        if space.get("title") == title:
            return space
    return None


def create_space(
    host: str,
    headers: dict,
    *,
    title: str,
    description: str,
    parent_path: str,
    warehouse_id: str,
    serialized_space: str,
) -> dict:
    response = requests.post(
        f"{host}/api/2.0/genie/spaces",
        headers=headers,
        json={
            "title": title,
            "description": description,
            "parent_path": parent_path,
            "warehouse_id": warehouse_id,
            "serialized_space": serialized_space,
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def update_space(
    host: str,
    headers: dict,
    *,
    space_id: str,
    title: str,
    description: str,
    warehouse_id: str,
    serialized_space: str,
) -> dict:
    response = requests.patch(
        f"{host}/api/2.0/genie/spaces/{space_id}",
        headers=headers,
        json={
            "title": title,
            "description": description,
            "warehouse_id": warehouse_id,
            "serialized_space": serialized_space,
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create the curated BERTopic Narrative Genie Space."
    )
    parser.add_argument(
        "--payload",
        default="genie_space/bertopic_narrative_space.json",
        help="Path to the unescaped serialized_space JSON payload.",
    )
    parser.add_argument("--profile", default=os.getenv("DATABRICKS_CONFIG_PROFILE"))
    parser.add_argument("--host", default=os.getenv("DATABRICKS_HOST", DEFAULT_HOST))
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--description", default=DEFAULT_DESCRIPTION)
    parser.add_argument("--parent-path", default=DEFAULT_PARENT_PATH)
    parser.add_argument("--space-id", default=os.getenv("GENIE_SPACE_ID", DEFAULT_SPACE_ID))
    parser.add_argument("--warehouse-id", default=DEFAULT_WAREHOUSE_ID)
    parser.add_argument(
        "--force-create",
        action="store_true",
        help="Create a new space even if a space with the same title already exists.",
    )
    args = parser.parse_args()

    workspace = get_workspace_client(args)
    host = normalize_host(workspace.config.host or args.host)
    headers = build_headers(workspace)
    serialized_space = read_payload(Path(args.payload))

    if not args.force_create:
        existing_space = None
        if args.space_id:
            existing_space = {"space_id": args.space_id, "title": args.title}
        else:
            existing_space = find_existing_space(host, headers, args.title)
        if existing_space:
            try:
                space = update_space(
                    host,
                    headers,
                    space_id=existing_space["space_id"],
                    title=args.title,
                    description=args.description,
                    warehouse_id=args.warehouse_id,
                    serialized_space=serialized_space,
                )
            except requests.HTTPError as e:
                print(e.response.text, file=sys.stderr)
                raise

            print(json.dumps(space, indent=2, sort_keys=True))
            return 0

    try:
        space = create_space(
            host,
            headers,
            title=args.title,
            description=args.description,
            parent_path=args.parent_path,
            warehouse_id=args.warehouse_id,
            serialized_space=serialized_space,
        )
    except requests.HTTPError as e:
        print(e.response.text, file=sys.stderr)
        raise

    print(json.dumps(space, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
