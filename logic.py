import pandas as pd
from sqlalchemy import text
from datetime import datetime
from database import get_engine

# ---------- HELPER ----------
def sanitize_part_number(part_number):
    """
    Sanitizes part number:
    1. Removes *, @, +
    2. Replaces 'O' (letter) with '0' (number)
    3. Strips whitespace
    """
    if not part_number:
        return ""
        
    s = str(part_number).upper() # Normalize case
    
    # Remove special chars: *, @, +
    for char in ['*', '@', '+']:
        s = s.replace(char, '')
        
    # Replace O with 0
    s = s.replace('O', '0')
    
    return s.strip()

# ---------- STOCK MANAGEMENT ----------
# ---------- STOCK MANAGEMENT ----------
def upload_parts_stock(df_parts: pd.DataFrame, stock_type: str):
    df = df_parts.copy()
    df.columns = df.columns.str.strip().str.lower()
    
    column_mapping = {
        'part_number': 'part_number',
        'description': 'description',
        'stock': 'free_stock',
        'price($)': 'price'
    }

    # Rename mapped columns
    actual_map = {}
    for col in df.columns:
        if col in column_mapping:
            actual_map[col] = column_mapping[col]
        elif 'supersede' in col.lower(): # fuzzy match for superseded
            actual_map[col] = 'superseded'
            
    df = df.rename(columns=actual_map)
    
    # Sanitization: Ensure Price is numeric
    if 'price' in df.columns:
        # Convert to string, clean, then to numeric
        df['price'] = df['price'].astype(str).str.replace('$', '').str.replace(',', '').str.strip()
        df['price'] = pd.to_numeric(df['price'], errors='coerce').fillna(0)

    
    # Sanitization
    if 'part_number' in df.columns:
        df['part_number'] = df['part_number'].astype(str).str.strip()
        
    # Add metadata
    df['stock_type'] = stock_type
    df['is_active'] = True
    
    engine = get_engine()
    with engine.begin() as conn:
        # Soft Delete: Mark existing active items of this stock_type as inactive
        conn.execute(
            text("UPDATE parts_stock SET is_active = FALSE WHERE stock_type = :st AND is_active = TRUE"),
            {"st": stock_type}
        )
        
        # Insert New
        # Filter to allowed columns. Removed legacy delivery prices.
        allowed_cols = ['part_number', 'description', 'free_stock', 'price', 'stock_type', 'is_active', 'superseded']
        df_final = df[[c for c in allowed_cols if c in df.columns]]
        
        df_final.to_sql("parts_stock", con=conn, if_exists="append", index=False)

def reset_stock(stock_type: str):
    engine = get_engine()
    with engine.begin() as conn:
        # Hard Delete
        conn.execute(
            text("DELETE FROM parts_stock WHERE stock_type = :st"),
            {"st": stock_type}
        )

def get_parts_like(prefix, stock_type, adjustment_percent=0):
    # Search Logic: Sanitize Input FIRST
    sanitized_input = sanitize_part_number(prefix)
    
    # Still strip hyphens for the DB search logic key (cleaned_prefix)
    # But now we base it on the sanitized input
    cleaned_prefix = sanitized_input.replace("-", "").strip()
    
    engine = get_engine()
    with engine.begin() as conn:
        rows = conn.execute(
            text("""
            SELECT part_number, description, free_stock,
                   price, stock_type, superseded
            FROM parts_stock
            WHERE (part_number ILIKE :prefix OR part_number ILIKE :raw_prefix OR description ILIKE :prefix OR superseded ILIKE :prefix)
              AND stock_type = :st
              AND is_active = TRUE
            ORDER BY 
                CASE 
                    WHEN part_number ILIKE :exact_start THEN 1 
                    ELSE 2 
                END, 
                part_number
            LIMIT 50
            """),
            {
                "prefix": f"%{cleaned_prefix}%",
                "raw_prefix": f"%{str(prefix).strip()}%",
                "exact_start": f"{cleaned_prefix}%",
                "st": stock_type
            },
        ).fetchall()
        
    results = []
    seen_parts = set()
    
    # Helper to process row
    def process_row(row_dict):
        pn = row_dict['part_number']
        if pn in seen_parts:
            return None
        seen_parts.add(pn)
        
        # Apply Adjustment: base * (1 + pct/100)
        base = float(row_dict['price'] or 0)
        row_dict['price'] = round(base * (1 + adjustment_percent / 100.0), 2)
        return row_dict

    # 1. Process initial results
    for row in rows:
        d = dict(row._mapping)
        processed = process_row(d)
        if processed:
            # Recursive Supersession Check
            def check_supersession(current_part_data, depth=0):
                if depth > 5: return None # Prevent infinite loops
                
                free_stock = current_part_data.get('free_stock') or 0
                sup = current_part_data.get('superseded')
                
                # Logic: If superseded exists (Removed stock check: always show if exists)
                if sup and str(sup).strip():
                    sup_clean = str(sup).strip()
                    # Query DB for this specific part
                    with engine.begin() as conn2:
                        sup_rows = conn2.execute(
                            text("""
                            SELECT part_number, description, free_stock, price, stock_type, superseded
                            FROM parts_stock
                            WHERE part_number = :pn AND stock_type = :st AND is_active = TRUE
                            """),
                            {"pn": sup_clean, "st": stock_type}
                        ).fetchall()
                        
                    for s_row in sup_rows:
                        sd = dict(s_row._mapping)
                        
                        # Apply adjustment to superseded part too
                        s_processed_inner = process_row(sd.copy()) # Copy to avoid mutating shared cache if any
                        if s_processed_inner:
                            # Attach as object to the PARENT
                            # If this superseded part IS superseded recursively, call again
                            s_processed_inner['is_superseded_replacement'] = True
                            
                            # Recursion
                            resup = check_supersession(s_processed_inner, depth+1)
                            if resup:
                                s_processed_inner['superseded_part'] = resup
                            
                            return s_processed_inner
                return None

            # Attach superseded info to the result
            sup_obj = check_supersession(processed)
            if sup_obj:
               processed['superseded_part'] = sup_obj
               # Also set a flag for UI
               processed['has_supersession'] = True

            results.append(processed)
            
    # Simple object class that supports dot notation and nested objects
    class PartObj:
        def __init__(self, **entries):
            for k, v in entries.items():
                if isinstance(v, dict):
                    self.__dict__[k] = PartObj(**v)
                else:
                    self.__dict__[k] = v
            
    return [PartObj(**r) for r in results]

def get_part_by_number(part_number, stock_type):
    engine = get_engine()
    with engine.begin() as conn:
        row = conn.execute(
            text("""
            SELECT part_number, description, free_stock, price
            FROM parts_stock
            WHERE part_number = :part_number 
              AND stock_type = :st
              AND is_active = TRUE
            """),
            {"part_number": part_number, "st": stock_type},
        ).fetchone()
    return row

# ---------- CART MANAGEMENT ----------
def add_to_cart_db(user_id, part_number, description, qty, price, supersedes=None):
    # Sanitize
    part_number = sanitize_part_number(part_number)
    
    engine = get_engine()
    with engine.begin() as conn:
        # Check if exists
        curr = conn.execute(
            text("SELECT id, qty FROM cart WHERE user_id = :uid AND part_number = :pn"),
            {"uid": user_id, "pn": part_number}
        ).fetchone()
        
        if curr:
            # UPSERT: Update existing
            new_qty = curr.qty + qty
            conn.execute(
                text("UPDATE cart SET qty = :qty WHERE id = :id"),
                {"qty": new_qty, "id": curr.id}
            )
        else:
            # Insert New
            conn.execute(
                text("""
                INSERT INTO cart (user_id, part_number, description, qty, price, supersedes)
                VALUES (:user_id, :part_number, :description, :qty, :price, :supersedes)
                """),
                {
                    "user_id": user_id,
                    "part_number": part_number,
                    "description": description,
                    "qty": qty,
                    "price": price,
                    "supersedes": supersedes
                }
            )

def get_user_cart(user_id, stock_type='parts_stock'):
    engine = get_engine()
    with engine.begin() as conn:
        # Join with stock to get real-time availability
        rows = conn.execute(
            text("""
            SELECT c.id, c.part_number, c.supersedes, c.description, c.qty, c.price,
                   p.free_stock as available_qty
            FROM cart c
            LEFT JOIN parts_stock p ON c.part_number = p.part_number AND p.stock_type = :st AND p.is_active = TRUE
            WHERE c.user_id = :user_id
            ORDER BY c.timestamp DESC
            """),
            {"user_id": user_id, "st": stock_type}
        ).fetchall()
        
    results = []
    for row in rows:
        d = dict(row._mapping)
        req = d['qty']
        avail = d['available_qty'] or 0
        
        # Logic: Allocated = min(Req, Stock)
        if avail >= req:
            d['allocated_qty'] = req
            d['status'] = "Fully Allocated"
        elif avail > 0:
            d['allocated_qty'] = avail
            d['status'] = "Partial Fulfillment"
        else:
            d['allocated_qty'] = 0
            d['status'] = "Out of Stock"
            
        d['no_record'] = False # existed in cart means valid
        
        # Back Order calculation: Requested Qty - Current Stock, otherwise 0
        d['back_order'] = max(0, req - avail)
        
        results.append(d)
        
    return results

def remove_from_cart_db(cart_id):
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM cart WHERE id = :id"),
            {"id": cart_id}
        )

def update_cart_item_db(cart_id, new_qty):
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE cart SET qty = :qty WHERE id = :id"),
            {"qty": new_qty, "id": cart_id}
        )

def clear_cart_db(user_id):
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM cart WHERE user_id = :user_id"),
            {"user_id": user_id}
        )

# ---------- ORDER PROCESSING ----------
def create_order(user_id, items, stock_type):
    # items is list of dict: {part_number, description, qty (This is REQUESTED), price, ...}
    
    total_alloc_price = 0
    engine = get_engine()
    
    try:
        with engine.begin() as conn:
            # 1. Create Order Header (Initial total 0, update later)
            result = conn.execute(
                text("INSERT INTO orders (user_id, total_price, stock_type) VALUES (:uid, 0, :stype) RETURNING order_id"),
                {"uid": user_id, "stype": stock_type}
            )
            order_id = result.fetchone()[0]
            
            for item in items:
                # 2. Check Live Stock
                # Lock row if possible, or just select
                row = conn.execute(
                    text("SELECT free_stock FROM parts_stock WHERE part_number = :pn AND stock_type = :stype"),
                    {"pn": item['part_number'], "stype": stock_type}
                ).fetchone()
                
                current_stock = row.free_stock if row else 0
                requested_qty = item['qty'] # The user's input
                
                # 3. Cap Allocation
                allocated_qty = min(requested_qty, current_stock)
                
                # 4. Deduct Stock (Only if allocated > 0)
                if allocated_qty > 0:
                    conn.execute(
                        text("UPDATE parts_stock SET free_stock = free_stock - :qty WHERE part_number = :pn AND stock_type = :stype"),
                        {"qty": allocated_qty, "pn": item['part_number'], "stype": stock_type}
                    )
                
                # 5. Insert Line Item
                # qty -> allocated_qty
                # requested_qty -> requested_qty
                
                conn.execute(
                    text("""
                    INSERT INTO order_items 
                    (order_id, part_number, description, qty, requested_qty, available_qty, price, supersedes)
                    VALUES (:oid, :pn, :desc, :qty, :req, :avail, :price, :supersedes)
                    """),
                    {
                        "oid": order_id,
                        "pn": item['part_number'],
                        "desc": item['description'],
                        "qty": allocated_qty, # SAVED AS ALLOCATED
                        "req": requested_qty, # SAVED AS REQUESTED
                        "avail": current_stock, # Snapshot of stock at time of order
                        "price": item['price'],
                        "supersedes": item.get('supersedes')
                    }
                )
                
                total_alloc_price += (allocated_qty * item['price'])
                
            # 6. Update Header Total
            conn.execute(
                text("UPDATE orders SET total_price = :tot WHERE order_id = :oid"),
                {"tot": total_alloc_price, "oid": order_id}
            )
            
            # 7. Clear Cart
            conn.execute(text("DELETE FROM cart WHERE user_id = :uid"), {"uid": user_id})
            
        return True, order_id
    except Exception as e:
        return False, str(e)

# ---------- BULK PROCESSING ----------
def process_bulk_enquiry(df_bulk, stock_type, adjustment_percent=0):
    engine = get_engine()
    df = df_bulk.copy()
    
    # Normalize headers
    df.columns = [str(c).strip().lower() for c in df.columns]

    # Handle S.No if exists or first column
    if 's.no' in df.columns:
        sno_col = 's.no'
        # ensure it is numeric and fill blanks if any
        df[sno_col] = pd.to_numeric(df[sno_col], errors='coerce')
    else:
        # Check first column
        if len(df.columns) > 0 and 's' in df.columns[0].lower() and 'no' in df.columns[0].lower():
             df = df.rename(columns={df.columns[0]: 's.no'})
             sno_col = 's.no'
        else:
             # Auto-populate if missing
             df.insert(0, 's.no', range(1, len(df) + 1))
             sno_col = 's.no'

    # Fill blank S.No
    df[sno_col] = df[sno_col].fillna(pd.Series(range(1, len(df) + 1)))

    # New parts_order file contains only: part_number, qty
    col_map = {}
    for c in df.columns:
        if c == sno_col: continue # Skip sno
        if 'part' in c or 'number' in c:
            col_map[c] = 'part_number'
        elif 'qty' in c or 'quantity' in c:
            col_map[c] = 'qty'
    
    df = df.rename(columns=col_map)
    
    if 'part_number' not in df.columns:
         # Try to find a col that isn't sno or qty
         for c in df.columns:
             if c not in ['s.no', 'qty']:
                 df = df.rename(columns={c: 'part_number'})
                 break
            
    # Check for required columns
    required = ['part_number', 'qty']
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}. Found: {list(df.columns)}")

    # Record original sort order based on S.No or part_number
    # We'll use s.no as the primary sorter
    df = df.sort_values(by='s.no')

    # Aggregation: Group by lookup_part_number to merge duplicates IS REMOVED 
    # as per requirement to maintain original sort order and potentially multiple lines of same part.
    # However, if user wants to group, we can, but let's keep it as is for individual row control.
            
    # Clean Part Number (Sanitization)
    if 'part_number' in df.columns:
        # Preserve Original
        df['original_part_number'] = df['part_number']
        # Sanitize for lookup
        df['lookup_part_number'] = df['part_number'].apply(lambda x: sanitize_part_number(x).replace("-", ""))
    
    # Preparation
    all_stock = []
    with engine.connect() as conn:
        try:
             all_stock = conn.execute(
                 text("SELECT part_number, description, free_stock, price, superseded FROM parts_stock WHERE stock_type = :st AND is_active = TRUE"),
                 {"st": stock_type}
             ).fetchall()
        except Exception as e:
             print(f"DB Error: {e}")
             
    stock = pd.DataFrame([dict(row._mapping) for row in all_stock])

    if not stock.empty:
         stock['match_key'] = stock['part_number'].apply(lambda x: str(x).replace("-", "").strip())
    else:
         stock['match_key'] = pd.Series(dtype='object')
    
    if adjustment_percent != 0:
        stock['price'] = stock['price'].fillna(0) * (1 + adjustment_percent / 100.0)
        stock['price'] = stock['price'].round(2)
    
    # Merge on Matches
    # Use suffixes to avoid duplicate columns (like part_number) that cause confusion later
    df = df.merge(stock, left_on="lookup_part_number", right_on="match_key", how="left", suffixes=('', '_stock'))
    
    # After merge, we might have 'part_number' from DF and 'part_number_stock' from stock.
    # We want to use the 'part_number_stock' if available, otherwise fallback.
    if 'part_number_stock' in df.columns:
        df['real_part_number'] = df['part_number_stock'].combine_first(df['part_number'])
    else:
        df['real_part_number'] = df['part_number']

    df["available_qty"] = df["free_stock"].fillna(0).astype(int)
    
    stock_unique = stock.drop_duplicates(subset=['part_number'])
    stock_unique_norm = stock.drop_duplicates(subset=['match_key'])
    
    stock_map = stock_unique.set_index('part_number', drop=False).to_dict('index')
    stock_map_norm = stock_unique_norm.set_index('match_key', drop=False).to_dict('index')
    
    results_list = []
    
    for idx, row in df.iterrows():
        orig_pn = row['original_part_number']
        desc = row['description'] 
        avail = row['available_qty']
        price = row['price']
        req_qty = row['qty']
        sno = row[sno_col]
        real_pn = row['real_part_number']
        
        if pd.isna(desc):
             results_list.append({
                 'S.No': sno,
                 'original_part_number': orig_pn,
                 'description': None,
                 'price': 0,
                 'available_qty': 0,
                 'requested_qty': req_qty,
                 'allocated_qty': 0,
                 'back_order': req_qty,
                 'no_record': True,
                 'status': "Invalid Part",
                 'allocated_part_number': None,
                 'supersedes': None
             })
             continue

        alloc_orig = min(req_qty, avail)
        # Back Order calculation: ALWAYS based on original part's deficit
        # regardless of whether a superseded part was used to fulfill the remaining need.
        back_order_orig = max(0, req_qty - alloc_orig)
        remainder = req_qty - alloc_orig
        
        sup_pointer = row.get('superseded')
        superseded_part_data = None
        
        if remainder > 0 and pd.notna(sup_pointer) and str(sup_pointer).strip():
             new_pn = str(sup_pointer).strip()
             new_pn_clean = new_pn.replace("-", "")
             
             if new_pn in stock_map:
                superseded_part_data = stock_map[new_pn]
             elif new_pn_clean in stock_map_norm:
                superseded_part_data = stock_map_norm[new_pn_clean]
        
        sup_display = str(sup_pointer).strip() if pd.notna(sup_pointer) and str(sup_pointer).strip() else None

        if remainder <= 0:
            results_list.append({
                 'S.No': str(sno),
                 'original_part_number': orig_pn,
                 'description': desc,
                 'price': price,
                 'available_qty': avail,
                 'requested_qty': req_qty,
                 'allocated_qty': alloc_orig,
                 'back_order': 0,
                 'no_record': False,
                 'status': "Fully Allocated",
                 'allocated_part_number': real_pn,
                 'supersedes': sup_display
             })
             
        elif superseded_part_data and int(superseded_part_data.get('free_stock') or 0) > 0:
            # Trigger: If Requested Qty > Available Stock of the original part.
            # Superseded Inclusion: If a superseded part exists with stock > 0, it must be added as a new row immediately below the original part.
            
            # Original Part Row
            results_list.append({
                 'S.No': str(sno),
                 'original_part_number': orig_pn,
                 'description': desc,
                 'price': price,
                 'available_qty': avail,
                 'requested_qty': req_qty,
                 'allocated_qty': alloc_orig,
                 'back_order': back_order_orig,
                 'no_record': False,
                 'status': "Partial - Split" if alloc_orig > 0 else "Out of Stock",
                 'allocated_part_number': real_pn,
                 'supersedes': sup_display
             })

            sup_avail = int(superseded_part_data.get('free_stock') or 0)
            sup_price = float(superseded_part_data.get('price') or 0)
            alloc_sup = min(remainder, sup_avail)
            
            # Superseded Part Row (Sub-decimal S.No)
            results_list.append({
                 'S.No': f"{sno}.1", 
                 'original_part_number': orig_pn,
                 'description': f"(Superseded) {superseded_part_data['description']}",
                 'price': sup_price,
                 'available_qty': sup_avail,
                 'requested_qty': 0, # Requirement show (Superseded) or similar? Example shows empty or marker
                 'allocated_qty': alloc_sup,
                 'back_order': 0, # Requirement says Back Order always on original
                 'no_record': False,
                 'status': "Superseded fulfillment",
                 'allocated_part_number': superseded_part_data['part_number'],
                 'supersedes': None
             })

        else:
            # Standard fulfillment (Partial or OOS)
            results_list.append({
                 'S.No': str(sno),
                 'original_part_number': orig_pn,
                 'description': desc,
                 'price': price,
                 'available_qty': avail,
                 'requested_qty': req_qty,
                 'allocated_qty': alloc_orig,
                 'back_order': back_order_orig,
                 'no_record': False,
                 'status': "Partial" if alloc_orig > 0 else "Out of Stock",
                 'allocated_part_number': real_pn,
                 'supersedes': sup_display
             })

    output_df = pd.DataFrame(results_list)
    
    if not output_df.empty:
        # Re-sort to maintain original order
        output_df = output_df.sort_values(by=['S.No', 'status'], ascending=[True, False]).reset_index(drop=True)

        output_df['display_part_number'] = output_df['allocated_part_number'].combine_first(output_df['original_part_number'])
        
        # Rename to match requirements
        rename_map = {
            'display_part_number': 'Part Number',
            'S.No': 'S.No',
            'original_part_number': 'Requested Input',
            'description': 'Description',
            'price': 'Price',
            'available_qty': 'Available_Qty',
            'requested_qty': 'Requested_Qty',
            'allocated_qty': 'Allocated_Qty',
            'back_order': 'Back Order',
            'no_record': 'No Record',
            'status': 'Status',
            'supersedes': 'Supersedes',
            'allocated_part_number': 'real_part_number'
        }
        
        output_df = output_df.rename(columns=rename_map)
        
        # Order columns strictly
        strict_cols = ['S.No', 'Part Number', 'Description', 'Price', 'Available_Qty', 'Requested_Qty', 'Allocated_Qty', 'Back Order', 'Supersedes', 'Status', 'No Record', 'real_part_number', 'Requested Input']
        output_df = output_df[[c for c in strict_cols if c in output_df.columns]]

    return output_df

# ---------- ADMIN FUNCTIONS ----------
def get_all_orders():
    engine = get_engine()
    with engine.begin() as conn:
        # Get Headers
        headers = conn.execute(
            text("SELECT order_id, user_id, total_price, order_status, stock_type, timestamp FROM orders ORDER BY timestamp DESC")
        ).fetchall()
        
    return [dict(row._mapping) for row in headers]

def get_order_details(order_id):
    engine = get_engine()
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, order_id, part_number, description, qty, requested_qty, available_qty, price, no_record_flag, supersedes FROM order_items WHERE order_id = :oid"),
            {"oid": order_id}
        ).fetchall()
    return [dict(row._mapping) for row in rows]

def restore_stock_from_order(conn, order_id):
    """
    Adds back the ALLOCATED quantity (qty) from order_items to parts_stock.
    MUST be called within an active transaction (conn).
    """
    # 1. Get items to restore
    items = conn.execute(
        text("SELECT part_number, qty FROM order_items WHERE order_id = :oid"),
        {"oid": order_id}
    ).fetchall()
    
    # 2. Identify stock type from header
    header = conn.execute(
        text("SELECT stock_type FROM orders WHERE order_id = :oid"),
        {"oid": order_id}
    ).fetchone()
    
    if not header:
        return # Orphaned items?
        
    stype = header.stock_type
    
    for item in items:
        # Restore only if something was allocated
        if item.qty > 0:
            conn.execute(
                text("UPDATE parts_stock SET free_stock = free_stock + :qty WHERE part_number = :pn AND stock_type = :stype"),
                {"qty": item.qty, "pn": item.part_number, "stype": stype}
            )

def update_order_status(order_id, status):
    engine = get_engine()
    try:
        with engine.begin() as conn:
            # Check current status first to prevent double-restoration?
            # Ideally yes, but simplified here. 
            # If transitioning FROM Pending/Accepted TO Rejected -> Restore.
            # If transitioning FROM Rejected TO Accepted -> Deduct again? (Not implemented yet, assumed one-way or careful admin)
            
            # Simple Rule: If New Status is Rejected, Restore Stock.
            # WARNING: If Admin clicks Reject twice, it duplicates stock? 
            # Guard: Only restore if current status is NOT Rejected.
            
            curr = conn.execute(text("SELECT order_status FROM orders WHERE order_id = :oid"), {"oid": order_id}).fetchone()
            if curr and curr.order_status != 'Rejected' and status == 'Rejected':
                restore_stock_from_order(conn, order_id)
            
            conn.execute(
                text("UPDATE orders SET order_status = :status WHERE order_id = :oid"),
                {"status": status, "oid": order_id}
            )
        return True, "Updated"
    except Exception as e:
        return False, str(e)

def delete_order(order_id):
    engine = get_engine()
    try:
        with engine.begin() as conn:
            # RESTORE STOCK BEFORE DELETE
            restore_stock_from_order(conn, order_id)
            
            conn.execute(text("DELETE FROM order_items WHERE order_id = :oid"), {"oid": order_id})
            conn.execute(text("DELETE FROM orders WHERE order_id = :oid"), {"oid": order_id})
        return True, "Deleted"
    except Exception as e:
        return False, str(e)

def delete_all_users_history():
    engine = get_engine()
    try:
        with engine.begin() as conn:
            # Restore stock for all non-rejected orders before wiping
            orders = conn.execute(text("SELECT order_id FROM orders WHERE order_status != 'Rejected'")).fetchall()
            for row in orders:
                restore_stock_from_order(conn, row.order_id)
                
            conn.execute(text("DELETE FROM order_items"))
            conn.execute(text("DELETE FROM orders"))
        return True, "All history deleted and stock restored where applicable"
    except Exception as e:
        return False, str(e)

def delete_all_orders(stock_type):
    engine = get_engine()
    try:
        with engine.begin() as conn:
            # Restore stock for all non-rejected orders of this type
            orders = conn.execute(
                text("SELECT order_id FROM orders WHERE stock_type = :st AND order_status != 'Rejected'"),
                {"st": stock_type}
            ).fetchall()
            for row in orders:
                restore_stock_from_order(conn, row.order_id)

            conn.execute(
                text("""
                DELETE FROM order_items 
                WHERE order_id IN (SELECT order_id FROM orders WHERE stock_type = :st)
                """),
                {"st": stock_type}
            )
            
            # Delete Orders
            conn.execute(
                text("DELETE FROM orders WHERE stock_type = :st"),
                {"st": stock_type}
            )
            return True, "All orders deleted and stock restored"
    except Exception as e:
        return False, str(e)

# ---------- USER MANAGEMENT (ADMIN) ----------
def get_all_users():
    engine = get_engine()
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT user_id, user_name, mail_id, phone_number, is_active, role, assigned_stock_type, price_adjustment_percent FROM customer_details ORDER BY user_id")
        ).fetchall()
    results = [dict(row._mapping) for row in rows]
    for r in results:
        r['price_adjustment_percent'] = float(r['price_adjustment_percent'] or 0)
    return results

def update_user_status(user_id, is_active):
    engine = get_engine()
    try:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE customer_details SET is_active = :status WHERE user_id = :uid"),
                {"status": is_active, "uid": user_id}
            )
        return True, "Updated"
    except Exception as e:
        return False, str(e)

def update_user_role(user_id, role):
    engine = get_engine()
    try:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE customer_details SET role = :role WHERE user_id = :uid"),
                {"role": role, "uid": user_id}
            )
        return True, "Updated"
    except Exception as e:
        return False, str(e)

def update_user_stock_assignment(user_id, stock_type):
    engine = get_engine()
    try:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE customer_details SET assigned_stock_type = :st WHERE user_id = :uid"),
                {"st": stock_type, "uid": user_id}
            )
        return True, "Updated"
    except Exception as e:
        return False, str(e)

def update_user_price_adjustment(user_id, percent):
    engine = get_engine()
    try:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE customer_details SET price_adjustment_percent = :pct WHERE user_id = :uid"),
                {"pct": percent, "uid": user_id}
            )
        return True, "Updated"
    except Exception as e:
        return False, str(e)

def force_schema_cleanup():
    engine = get_engine()
    log = []
    try:
        with engine.begin() as conn:
            try:
                conn.execute(text("ALTER TABLE cart DROP COLUMN IF EXISTS delivery_area"))
                log.append("Dropped delivery_area from cart.")
            except Exception as e:
                log.append(f"Cart Error: {e}")
                
            try:
                conn.execute(text("ALTER TABLE order_items DROP COLUMN IF EXISTS delivery_area"))
                log.append("Dropped delivery_area from order_items.")
            except Exception as e:
                log.append(f"Items Error: {e}")
                
        return True, " | ".join(log)
    except Exception as e:
        return False, str(e)

# ---------- PROFILE & HISTORY ----------
def get_stock_csv(stock_type):
    engine = get_engine()
    # Read active parts for the assigned stock type with aliases
    # df = pd.read_sql(
    #     text("""
    #     SELECT part_number, description, free_stock as stock, price as "price($)" 
    #     FROM parts_stock 
    #     WHERE stock_type = :st AND is_active = TRUE
    #     """), 
    #     engine,
    #     params={"st": stock_type}
    # )
    df = pd.read_sql(
        text("""
        SELECT part_number, description, free_stock as stock
        FROM parts_stock 
        WHERE stock_type = :st AND is_active = TRUE
        """), 
        engine,
        params={"st": stock_type}
    )
    return df.to_csv(index=False).encode('utf-8')

def get_user_orders(user_id):
    engine = get_engine()
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT order_id, total_price, order_status, timestamp FROM orders WHERE user_id = :uid ORDER BY timestamp DESC"),
            {"uid": user_id}
        ).fetchall()
    return [dict(row._mapping) for row in rows]
