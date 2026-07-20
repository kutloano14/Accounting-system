from app.database import SessionLocal
from app import models
from app.main import get_password_hash

db = SessionLocal()

users = [
    {
        "email": "tobanep@gmail.com",
        "full_name": "Tobane",
        "password": "Password123",
    },
    {
        "email": "theto@gmail.com",
        "full_name": "Theto",
        "password": "Password123",
    },
]

for u in users:
    existing = db.query(models.User).filter(models.User.email == u["email"]).first()

    if not existing:
        user = models.User(
            email=u["email"],
            full_name=u["full_name"],
            password_hash=get_password_hash(u["password"]),
            is_active=True,
        )
        db.add(user)

db.commit()
db.close()

print("Users created successfully.")