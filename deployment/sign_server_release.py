"""Sign or verify a server installer manifest with Ed25519."""

from __future__ import annotations

import argparse
import base64
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate")
    generate.add_argument("--private-key", required=True)
    generate.add_argument("--public-key", required=True)
    sign = sub.add_parser("sign")
    sign.add_argument("--private-key", required=True)
    sign.add_argument("--manifest", required=True)
    sign.add_argument("--output", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--public-key", required=True)
    verify.add_argument("--manifest", required=True)
    verify.add_argument("--signature", required=True)
    args = parser.parse_args(argv)

    if args.command == "generate":
        private = Ed25519PrivateKey.generate()
        private_path = Path(args.private_key)
        private_path.parent.mkdir(parents=True, exist_ok=True)
        private_path.write_bytes(
            private.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        Path(args.public_key).write_text(
            base64.b64encode(
                private.public_key().public_bytes(
                    serialization.Encoding.Raw,
                    serialization.PublicFormat.Raw,
                )
            ).decode("ascii"),
            encoding="ascii",
        )
        return 0

    manifest = Path(args.manifest).read_bytes()
    if args.command == "sign":
        private = serialization.load_pem_private_key(
            Path(args.private_key).read_bytes(),
            password=None,
        )
        if not isinstance(private, Ed25519PrivateKey):
            raise TypeError("The release key is not an Ed25519 private key.")
        Path(args.output).write_text(
            base64.b64encode(private.sign(manifest)).decode("ascii") + "\n",
            encoding="ascii",
        )
        return 0

    public = Ed25519PublicKey.from_public_bytes(
        base64.b64decode(Path(args.public_key).read_text(encoding="ascii").strip())
    )
    public.verify(
        base64.b64decode(Path(args.signature).read_text(encoding="ascii").strip()),
        manifest,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
