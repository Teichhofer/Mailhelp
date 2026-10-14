from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from mailhelp.webpush import b64


def sub():
    key = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return {"endpoint": "https://fcm.googleapis.com/fcm/send/synthetic", "keys": {"p256dh": b64(key), "auth": b64(b"x" * 16)}}

