from datetime import datetime

import boto3
from fastapi import APIRouter, Depends, HTTPException, status
from firebase_admin import auth as firebase_auth

from app.core.config import settings
from app.core.security import create_access_token, get_current_user
from app.models.schemas import (
    AdminInviteRequest,
    AdminLoginRequest,
    AdminMetrics,
    AdminUser,
    DevLoginRequest,
    TokenPayload,
)
from app.services import database

router = APIRouter()


# ==========================================
# SECURITY DEPENDENCIES (RBAC)
# ==========================================


async def get_admin_reader(current_user: TokenPayload = Depends(get_current_user)) -> AdminUser:
    """Allows ALL admin roles (SUPER_ADMIN, ADMIN, ANALYST) to view dashboard data."""
    admin_record = database.get_admin_user(current_user.sub)
    if not admin_record or admin_record.role not in ["SUPER_ADMIN", "ADMIN", "ANALYST"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin/Analytics access required."
        )
    return admin_record


async def get_admin_writer(current_user: TokenPayload = Depends(get_current_user)) -> AdminUser:
    """Blocks ANALYSTS. Only allows SUPER_ADMIN and ADMIN to moderate or delete data."""
    admin_record = database.get_admin_user(current_user.sub)
    if not admin_record or admin_record.role not in ["SUPER_ADMIN", "ADMIN"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")
    return admin_record


async def get_super_admin(current_admin: AdminUser = Depends(get_admin_writer)) -> AdminUser:
    """Strictly locks route to SUPER_ADMIN only."""
    if current_admin.role != "SUPER_ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Super Admin privileges required."
        )
    return current_admin


@router.post("/dev-login", summary="Dev-only Admin login simulation")
async def admin_dev_login(payload: DevLoginRequest):
    if settings.is_production:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not available in production",
        )
    """
    Simulates frontend login for development. Validates email against 
    the admin database and issues a local JWT with admin role claims.
    """
    # Fetch the admin record by email from db
    admin_record = database.get_admin_by_email(payload.email)

    if not admin_record:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized as admin."
        )

    # Mint a local development JWT with the admin's UID and role
    token = create_access_token(
        subject=admin_record.user_id,
        extra_claims={"role": admin_record.role.value, "email": admin_record.email},
    )

    return {"access_token": token, "token_type": "bearer", "role": admin_record.role}


@router.post("/admin-login", summary="Production Admin Login")
async def admin_login(payload: AdminLoginRequest):
    """
    Verifies the Firebase ID token and checks DynamoDB for admin privileges.
    """
    try:
        # Verify the ID token
        decoded_token = firebase_auth.verify_id_token(payload.id_token)
        uid = decoded_token.get("uid")

        # Check if the UID is registered in the admin table
        admin_record = database.get_admin_user(uid)
        if not admin_record:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized as admin."
            )

        # Safely extract role string from Enum
        role_str = (
            admin_record.role.value if hasattr(admin_record.role, "value") else admin_record.role
        )

        # Mint backend JWT with admin claims
        token = create_access_token(subject=uid, extra_claims={"role": role_str})

        return {"access_token": token, "token_type": "bearer", "role": role_str}

    except HTTPException:
        # Pass 403 Forbidden and other explicit HTTP exceptions through
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Authentication failed: {str(e)}"
        ) from e


# ==========================================
# SUPER ADMIN ROUTES (TEAM MANAGEMENT)
# ==========================================
@router.get("/team", summary="List all admins and analysts")
async def list_team(super_admin: AdminUser = Depends(get_super_admin)):
    """Lists all team members with their email and role."""
    team = database.get_all_admins()

    database.log_admin_action(
        admin_id=super_admin.user_id,
        action="VIEW_TEAM_REGISTRY",
        entity_type="admin_users",
        entity_id="ALL",
    )

    return {"team": [{"user_id": m.user_id, "email": m.email, "role": m.role} for m in team]}


@router.post("/invite", summary="Create a new admin account")
async def invite_admin(
    payload: AdminInviteRequest, super_admin: AdminUser = Depends(get_super_admin)
):
    """Only a SUPER_ADMIN can invite new team members."""
    try:
        user_record = firebase_auth.create_user(email=payload.email)

        setup_link = firebase_auth.generate_password_reset_link(payload.email)

        new_admin = AdminUser(
            user_id=user_record.uid,
            email=payload.email,
            role=payload.role,
            created_at=datetime.now(),
        )
        database.create_admin_user(new_admin)

        database.log_admin_action(
            super_admin.user_id, "INVITE_ADMIN", "admin_users", user_record.uid
        )

        return {
            "success": True,
            "message": f"{payload.role} invited successfully.",
            "setup_link": setup_link,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/access/{admin_id}", summary="Revoke admin access")
async def revoke_admin(admin_id: str, super_admin: AdminUser = Depends(get_super_admin)):
    """Only a SUPER_ADMIN can remove team members."""
    if admin_id == super_admin.user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own Super Admin account.")

    database.delete_admin_user(admin_id)

    database.log_admin_action(super_admin.user_id, "REVOKE_ADMIN", "admin_users", admin_id)

    return {"success": True, "message": "Admin privileges revoked."}


# ==========================================
# ANALYST ROUTES (READ-ONLY DASHBOARD)
# ==========================================


@router.get("/metrics", response_model=AdminMetrics, summary="Get platform-wide metrics")
async def get_platform_metrics(reader: AdminUser = Depends(get_admin_reader)):
    """Fetches platform analytics (Total Users, DAU, Total Scans, Average Score)."""
    metrics = database.get_platform_aggregates()
    return AdminMetrics(
        totalUsers=metrics.get("total_users", 0),
        dailyActiveUsers=metrics.get("daily_active_users", 0),
        totalScans=metrics.get("total_scans", 0),
        averageScore=metrics.get("average_score", 0.0),
    )


@router.get("/users", summary="List all registered users")
async def list_all_users(reader: AdminUser = Depends(get_admin_reader)):
    """Returns a lightweight list of all users."""
    users = database.get_all_users()
    return {"users": [{"userId": u.user_id, "email": u.email, "totalScans": u.total_scans} for u in users]}


@router.get("/users/{user_id}", summary="Get specific user details")
async def get_user_details(user_id: str, reader: AdminUser = Depends(get_admin_reader)):
    """Fetches lifetime stats for a specific user."""
    user = database.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "userId": user.user_id,
        "totalScans": user.total_scans,
        "averageScore": user.average_score,
    }


@router.get("/images", summary="List images for moderation")
async def list_uploaded_images(reader: AdminUser = Depends(get_admin_reader)):
    """Returns a list of recent images and their metadata for dashboard review."""
    images = database.get_user_images()

    # Return image_id and the URL so the frontend can render
    return {
        "images": [
            {
                "imageId": img.get("image_id"),
                "userId": img.get("user_id"),
                "image_url": img.get("image_url"),
                "image_type": img.get("image_type"),
                "uploadedAt": img.get("timestamp"),
            }
            for img in images
        ]
    }


# ==========================================
# MODERATION ROUTES (WRITER ACCESS REQUIRED)
# ==========================================


@router.delete("/user/{user_id}", summary="Delete a user account")
async def delete_user(user_id: str, writer: AdminUser = Depends(get_admin_writer)):
    """Immediately delete a user account and its retained application data."""
    user_record = database.get_user(user_id)
    if not user_record:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        firebase_auth.delete_user(user_id)
        database.purge_user_data(user_id)
        database.log_admin_action(writer.user_id, "DELETE_USER", "users", user_id)

        return {"success": True, "message": f"User {user_id} deleted immediately"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/image/{image_id}", summary="Delete a specific image")
async def delete_image(image_id: str, writer: AdminUser = Depends(get_admin_writer)):
    """Removes a moderated image from AWS S3 and the database."""
    image_record = database.get_image_metadata(image_id)
    if not image_record:
        raise HTTPException(status_code=404, detail="Image not found")

    try:
        s3 = boto3.client("s3")
        image_path = image_record.get("image_url")
        object_key = image_path.split(".com/")[-1] if ".com/" in image_path else image_path

        s3.delete_object(Bucket=settings.S3_UPLOAD_BUCKET, Key=object_key)

        database.delete_image_record(image_id)
        database.log_admin_action(writer.user_id, "DELETE_IMAGE", "uploaded_images", image_id)

        return {"success": True, "message": "Image deleted successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete image: {str(e)}") from e
