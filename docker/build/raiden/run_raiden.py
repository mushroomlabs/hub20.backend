import json
import os
import secrets
import subprocess
import sys
import tempfile

from eth_keyfile import create_keyfile_json
from eth_keys import keys


def main():
    pkey_bin = bytearray.fromhex(os.environ["RAIDEN_PRIVATE_KEY"][2:])
    password = secrets.token_hex()
    if not pkey_bin:
        sys.exit()

    private_key = keys.PrivateKey(pkey_bin)
    raiden_address = private_key.public_key.to_checksum_address()

    keyfile_json = create_keyfile_json(pkey_bin, password=password.encode())

    with tempfile.NamedTemporaryFile("w+") as key_file:
        json.dump(keyfile_json, key_file)
        key_file.flush()
        with tempfile.NamedTemporaryFile("w+") as password_file:
            password_file.write(password)
            password_file.flush()

            raiden_environment = os.environ.copy()
            raiden_environment.update(
                {
                    "RAIDEN_ADDRESS": raiden_address,
                    "RAIDEN_KEYSTORE_PATH": os.path.dirname(key_file.name),
                    "RAIDEN_KEYSTORE_FILE_PATH": key_file.name,
                    "RAIDEN_PASSWORD_FILE": password_file.name,
                    "RAIDEN_CHAIN_ID": os.getenv("RAIDEN_NETWORK_ID"),
                }
            )

            subprocess.call(["raiden"], env=raiden_environment)


if __name__ == "__main__":
    main()
