import streamlit as st
from sqlalchemy import text
from database import get_engine, get_next_user_id

def register_user(user_name, password, mail_id, phone_number):
    try:
        user_id = get_next_user_id()
        engine = get_engine()
        with engine.begin() as conn:
            conn.execute(
                text("""
                INSERT INTO customer_details (user_id, user_name, password, mail_id, phone_number, is_active, role)
                VALUES (:user_id, :user_name, :password, :mail_id, :phone_number, :is_active, :role)
                """),
                {
                    "user_id": user_id,
                    "user_name": user_name,
                    "password": password,
                    "mail_id": mail_id,
                    "phone_number": phone_number,
                    "is_active": False,
                    "role": "Standard User"
                },
            )
        return True, user_id
    except Exception as e:
        return False, str(e)

def authenticate_user(user_name, password):
    # Check for Admin hardcoded credentials first
    admin_user = st.secrets["admin"]["username"]
    admin_pass = st.secrets["admin"]["password"]
    
    if user_name == admin_user and password == admin_pass:
        return {
            "user_id": 0,
            "user_name": "Admin",
            "mail_id": "admin@example.com",
            "phone_number": "0000000000",
            "is_admin": True
        }

    engine = get_engine()
    with engine.begin() as conn:
        row = conn.execute(
            text("""
            SELECT user_id, user_name, mail_id, phone_number, password, is_active, role, assigned_stock_type, require_password_change, price_adjustment_percent
            FROM customer_details
            WHERE user_name = :user_name
            """),
            {"user_name": user_name},
        ).fetchone()

    if row and password == row.password:
        if not row.is_active:
             return {"error": "Account pending approval"}
             
        return {
            "user_id": row.user_id,
            "user_name": row.user_name,
            "mail_id": row.mail_id,
            "phone_number": row.phone_number,
            "is_admin": row.role == "Admin", # Or check specific role string
            "role": row.role,
            "assigned_stock_type": row.assigned_stock_type or "parts_stock", # Default to parts_stock
            "require_password_change": row.require_password_change,
            "price_adjustment_percent": float(row.price_adjustment_percent or 0)
        }
    return None

def update_profile(user_id, mail_id, phone_number):
    try:
        engine = get_engine()
        with engine.begin() as conn:
            conn.execute(
                text("""
                UPDATE customer_details
                SET mail_id = :mail_id,
                    phone_number = :phone_number
                WHERE user_id = :user_id
                """),
                {"mail_id": mail_id, "phone_number": phone_number, "user_id": user_id},
            )
        return True, "Profile updated"
    except Exception as e:
        return False, str(e)

def change_password(user_id, current_password, new_password):
    try:
        engine = get_engine()
        # Verify current first
        with engine.begin() as conn:
            row = conn.execute(
                text("SELECT password FROM customer_details WHERE user_id = :uid"),
                {"uid": user_id}
            ).fetchone()
            
            if not row or row.password != current_password:
                return False, "Incorrect current password"
            
            conn.execute(
                text("UPDATE customer_details SET password = :pw, require_password_change = FALSE WHERE user_id = :uid"),
                {"pw": new_password, "uid": user_id}
            )
        return True, "Password changed successfully"
    except Exception as e:
        return False, str(e)

def reset_password_admin(user_id, temp_password):
    try:
        engine = get_engine()
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE customer_details SET password = :pw, require_password_change = TRUE WHERE user_id = :uid"),
                {"pw": temp_password, "uid": user_id}
            )
        return True, "Password reset (User must change on next login)"
    except Exception as e:
        return False, str(e)
