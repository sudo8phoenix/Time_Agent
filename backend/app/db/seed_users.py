import argparse
from .passwords import hash_password
from .session import session_factory
from .models import User

def seed(username: str, password: str, role: str) -> bool:
    db = session_factory()
    try:
        existing = db.query(User).filter_by(username=username).one_or_none()
        if existing:
            if existing.role != role:
                existing.role = role
            db.commit()
            return False
        db.add(User(username=username, password_hash=hash_password(password), role=role))
        db.commit()
        return True
    finally: db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True); parser.add_argument("--password", required=True)
    parser.add_argument("--role", choices=("reviewer", "viewer"), default="viewer")
    args = parser.parse_args()
    print("created" if seed(args.username, args.password, args.role) else "existing; password unchanged")
