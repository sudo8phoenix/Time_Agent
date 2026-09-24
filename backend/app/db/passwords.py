import base64, hashlib, hmac, os

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 240_000)
    return "pbkdf2_sha256$240000$%s$%s" % (base64.b64encode(salt).decode(), base64.b64encode(digest).decode())

def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt, expected = encoded.split("$")
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(rounds))
        return algorithm == "pbkdf2_sha256" and hmac.compare_digest(base64.b64encode(actual).decode(), expected)
    except (ValueError, TypeError):
        return False
