# seed_admin.py
from datetime import datetime

from app.models.schemas import AdminRole, AdminUser
from app.services import database


def seed_super_admin():
    # Use the Enum here for strict typing
    admin = AdminUser(
        user_id="testsuperadmin",
        email="admin@facebyyou.dev",
        role=AdminRole.SUPER_ADMIN,
        created_at=datetime.now(),
    )

    try:
        database.create_admin_user(admin)
        print(f"Successfully seeded {admin.role.value}: {admin.email}")
    except Exception as e:
        print(f"Error seeding admin: {e}")


if __name__ == "__main__":
    seed_super_admin()
