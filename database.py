import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

@st.cache_resource
def get_engine() -> Engine:
    try:
        return create_engine(st.secrets["database"]["url"])
    except Exception as e:
        st.error(f"Failed to connect to database: {e}")
        raise e

def init_db():
    engine = get_engine()
    with engine.begin() as conn:
        # Customer Details
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS customer_details (
            user_id INTEGER PRIMARY KEY,
            user_name TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            mail_id TEXT,
            phone_number TEXT,
            is_active BOOLEAN DEFAULT FALSE,
            role TEXT DEFAULT 'Standard User',
            assigned_stock_type TEXT DEFAULT 'parts_stock',
            require_password_change BOOLEAN DEFAULT FALSE
        );
        """))
        
        # Soft Migration: Add columns if they don't exist
        try:
            conn.execute(text("ALTER TABLE customer_details ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT FALSE"))
            conn.execute(text("ALTER TABLE customer_details ADD COLUMN IF NOT EXISTS role TEXT DEFAULT 'Standard User'"))
            conn.execute(text("ALTER TABLE customer_details ADD COLUMN IF NOT EXISTS assigned_stock_type TEXT DEFAULT 'parts_stock'"))
            conn.execute(text("ALTER TABLE customer_details ADD COLUMN IF NOT EXISTS require_password_change BOOLEAN DEFAULT FALSE"))
            conn.execute(text("ALTER TABLE customer_details ADD COLUMN IF NOT EXISTS price_adjustment_percent NUMERIC DEFAULT 0"))
        except Exception as e:
            pass
        
        # Parts Stock
        # Note: We are removing the PRIMARY KEY on part_number to allow:
        # 1. Same part in different stock types (parts_stock vs HBD_stock)
        # 2. Soft deletes (multiple versions of same part, only one active)
        # We will use a composite index or just rely on logic for uniqueness of active items.
        
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS parts_stock (
            id SERIAL PRIMARY KEY,
            part_number TEXT,
            description TEXT,
            free_stock INTEGER,
            price NUMERIC,
            stock_type TEXT DEFAULT 'parts_stock',
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """))
        
        # Migration for parts_stock is trickier if table exists with PK on part_number.
        # SQLite vs Postgres differences matter here. User seems to be using Postgres (SERIAL).
        # We will attempt to add columns.
        try:
            conn.execute(text("ALTER TABLE parts_stock ADD COLUMN IF NOT EXISTS stock_type TEXT DEFAULT 'parts_stock'"))
            conn.execute(text("ALTER TABLE parts_stock ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE"))
            conn.execute(text("ALTER TABLE parts_stock ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"))
            conn.execute(text("ALTER TABLE parts_stock ADD COLUMN IF NOT EXISTS price NUMERIC"))
            conn.execute(text("ALTER TABLE parts_stock ADD COLUMN IF NOT EXISTS superseded TEXT"))
            # Ideally we drop PK constraint on part_number if it exists, but that's hard to do generically without knowing constraint name.
            # For now, we assume if it fails, user might need to drop table or we handle it.
            # Let's try to drop the constraint if we can guess the name or if it's just 'parts_stock_pkey'
            conn.execute(text("ALTER TABLE parts_stock DROP CONSTRAINT IF EXISTS parts_stock_pkey"))
            # If we dropped PK, we should add a new ID column if it doesn't exist? 
            # Adding SERIAL column to existing table is possible.
            conn.execute(text("ALTER TABLE parts_stock ADD COLUMN IF NOT EXISTS id SERIAL PRIMARY KEY"))
        except Exception as e:
            # If validation fails (e.g. multiple primary keys), we might need manual intervention or just proceed.
            # print(f"Migration warning: {e}")
            pass
        
        # Order Header
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id SERIAL PRIMARY KEY,
            user_id INTEGER,
            total_price NUMERIC,
            order_status TEXT DEFAULT 'Pending',
            stock_type TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """))
        
        try:
            conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS stock_type TEXT"))
        except Exception:
            pass

        # Order Details (Line Items)
        # Note: description and price here ACT as the snapshot.
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS order_items (
            id SERIAL PRIMARY KEY,
            order_id INTEGER REFERENCES orders(order_id),
            part_number TEXT,
            description TEXT,
            qty INTEGER,
            requested_qty INTEGER,
            available_qty INTEGER,
            price NUMERIC,
            no_record_flag BOOLEAN DEFAULT FALSE,
            supersedes TEXT
        );
        """))
        
        # Soft Migration
        try:
             conn.execute(text("ALTER TABLE order_items ADD COLUMN IF NOT EXISTS requested_qty INTEGER"))
             conn.execute(text("ALTER TABLE order_items ADD COLUMN IF NOT EXISTS supersedes TEXT"))
        except Exception:
             pass
        
        # Cart (Persistence)
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS cart (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            part_number TEXT,
            description TEXT,
            qty INTEGER,
            price NUMERIC,
            supersedes TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """))
        
        # Cleanup Legacy Columns
        try:
            conn.execute(text("ALTER TABLE cart DROP COLUMN IF EXISTS delivery_area"))
            conn.execute(text("ALTER TABLE order_items DROP COLUMN IF EXISTS delivery_area"))
            conn.execute(text("ALTER TABLE cart ADD COLUMN IF NOT EXISTS supersedes TEXT"))
        except Exception:
            pass

def get_next_user_id():
    engine = get_engine()
    with engine.begin() as conn:
        result = conn.execute(text("SELECT MAX(user_id) FROM customer_details"))
        max_id = result.scalar()
        return 1001 if max_id is None else max_id + 1
