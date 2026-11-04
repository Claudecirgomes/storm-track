import argparse
import getpass

from backend.app.accounts.service import provision_account
from backend.app.core.config import get_settings
from backend.app.core.db import connect, initialize_database


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision a local StormTrack account (no public signup).")
    parser.add_argument("--username", required=True)
    parser.add_argument("--role", choices=("ADMIN", "USER"), required=True)
    args = parser.parse_args()
    password = getpass.getpass("Password (minimum 12 characters): ")
    confirmation = getpass.getpass("Repeat password: ")
    if password != confirmation:
        parser.error("Passwords do not match")
    settings = get_settings()
    initialize_database(settings.database_target)
    connection = connect(settings.database_target)
    try:
        account = provision_account(connection, args.username, password, args.role)
    finally:
        connection.close()
    print(f"Provisioned {account['role']} account: {account['username']}")


if __name__ == "__main__":
    main()
