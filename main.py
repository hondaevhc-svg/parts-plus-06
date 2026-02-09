import streamlit as st
import pandas as pd
import time # Added for sleep
import database
import auth
import logic
from datetime import datetime

# Page Config
st.set_page_config(page_title="Parts Order System", layout="wide", page_icon="🔧")


# Hide Streamlit UI elements (Aggressive - Runs First)
hide_ui_style = """
<style>
/* 1. Hide the Hamburger Menu (Top Right) */
#MainMenu {visibility: hidden;}
/* 2. Hide the Footer (Made with Streamlit) */
footer {visibility: hidden;}
/* 3. Hide the Header Decoration */
header {visibility: hidden;}
/* 4. Hide the 'Manage App' Button (Bottom Right) */
.stDeployButton {display:none;}
[data-testid="stToolbar"] {visibility: hidden !important; display: none !important;}
[data-testid="stHeader"] {visibility: hidden !important; display: none !important;}
/* 5. Specific fix for 'Manage app' button in some versions */
[data-testid="manage-app-button"] {display: none !important;}
/* Remove top padding caused by hiding header */
.block-container {padding-top: 1rem;}
</style>
"""
st.markdown(hide_ui_style, unsafe_allow_html=True)

# Initialize DB
database.init_db()

# Session State Init
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "user" not in st.session_state:
    st.session_state.user = None
if "cart_refresh" not in st.session_state:
    st.session_state.cart_refresh = 0

# company logo url
COMPANY_LOGO =  "partsplus.png"


# Hero image filename
HERO_IMAGE = "hero_parts_collage.png"

def login_page():
    # Header with Logo
    try:
        st.image(COMPANY_LOGO, width=300)
    except Exception:
        st.warning("Company logo not found. Please upload 'parts_world_logo.png'")
    
    # Main Layout: 2 Columns
    col_hero, col_login = st.columns([2, 1], gap="large")
    
    with col_hero:
        # Hero Image and marketing text
        try:
            st.image(HERO_IMAGE, use_container_width=True)
        except:
            st.info("Hero image not found. Please upload 'hero_parts_collage.png'")
        
        st.markdown("""
        ### Premium Parts for Honda & GM
        Welcome to **Parts-World**. We specialize in providing high-quality authentic and aftermarket parts.
        - 🚀 Fast Delivery
        - 📦 Real-time Stock Availability
        - 🔧 Bulk Order Processing
        """)
        

    with col_login:
        st.markdown("### 🔐 User Access")
        tab1, tab2 = st.tabs(["Login", "Register"])
        
        with tab1:
            with st.form("login_form", clear_on_submit=False):
                username = st.text_input("Username", key="login_user")
                password = st.text_input("Password", type="password", key="login_pass")
                submit_login = st.form_submit_button("Login", type="primary", use_container_width=True)
                
            if submit_login:
                res = auth.authenticate_user(username, password)
                if res and "error" in res:
                    st.error(res["error"])
                elif res:
                    st.session_state.logged_in = True
                    st.session_state.user = res
                    st.success("Logged in successfully!")
                    st.rerun()
                else:
                    st.error("Invalid credentials")

        with tab2:
            with st.form("register_form", clear_on_submit=False):
                new_user = st.text_input("New Username", key="reg_user")
                new_pass = st.text_input("New Password", type="password", key="reg_pass")
                email = st.text_input("Email", key="reg_email")
                phone = st.text_input("Phone", key="reg_phone")
                submit_register = st.form_submit_button("Register", use_container_width=True)
            
            if submit_register:
                if new_user and new_pass:
                    success, msg = auth.register_user(new_user, new_pass, email, phone)
                    if success:
                        st.success(f"Registered! ID: {msg}")
                    else:
                        st.error(f"Failed: {msg}")
                else:
                    st.error("Username/Password required.")

def show_cart_ui(user_id):
    st.markdown("### 🛒 My Cart")
    stock_type = st.session_state.user.get('assigned_stock_type', 'parts_stock')
    cart_items = logic.get_user_cart(user_id, stock_type)
    
    if not cart_items:
        st.info("Cart is empty.")
        return

    # --- PREPARE DATA FOR TABLE VIEW ---
    # Goal: Sort items so that Superseded parts appear immediately below their Original parts.
    
    # 1. Map items
    item_map = {item['part_number']: item for item in cart_items}
    
    # 2. Build Hierarchy
    parents = []
    children = []
    
    for item in cart_items:
        sup_text = item.get('supersedes')
        is_child = False
        if sup_text and "Supersedes" in str(sup_text):
            parts = str(sup_text).split("Supersedes ")
            if len(parts) > 1:
                parent_pn = parts[1].strip()
                # If parent is ALSO in cart, this is a child. 
                # If parent not in cart (standalone replacement?), treat as parent/standalone.
                if parent_pn in item_map:
                    children.append(item)
                    is_child = True
        
        if not is_child:
            parents.append(item)

    # 3. Sort Parents (e.g. by Timestamp or Name)
    # Database usually returns by timestamp desc. Let's keep that or sort alphabetic?
    # Keep DB order for parents is usually best for "recent added".
    
    ordered_items = []
    # Map Children to Parent PN for fast lookup
    child_map = {}
    for c in children:
        sup_text = c.get('supersedes')
        p_pn = str(sup_text).split("Supersedes ")[1].strip()
        if p_pn not in child_map:
            child_map[p_pn] = []
        child_map[p_pn].append(c)
        
    for p in parents:
        ordered_items.append(p)
        # Check for children
        if p['part_number'] in child_map:
            ordered_items.extend(child_map[p['part_number']])
            
    # Create DataFrame
    df = pd.DataFrame(ordered_items)
    
    # Standardize column names for config
    df = df.rename(columns={
        'part_number': 'Part Number',
        'qty': 'Requested_Qty',
        'description': 'Description',
        'price': 'Price',
        'available_qty': 'Available_Qty',
        'allocated_qty': 'Allocated_Qty',
        'back_order': 'Back Order',
        'supersedes': 'Supersedes',
        'status': 'Status',
        'no_record': 'No Record'
    })

    if 'S.No' not in df.columns:
        df.insert(0, 'S.No', range(1, len(df) + 1))
    if 'Select' not in df.columns:
        df.insert(0, 'Select', True)

    # Columns to show
    cols = ['Select', 'S.No', 'Part Number', 'Description', 'Price', 'Available_Qty', 'Requested_Qty', 'Allocated_Qty', 'Back Order', 'Supersedes', 'Status', 'No Record', 'id']
    final_cols = [c for c in cols if c in df.columns]
    df = df[final_cols]

    edited_df = st.data_editor(
        df,
        key="cart_editor",
        hide_index=True,
        column_config=get_standard_config(),
        num_rows="dynamic", # Allow deleting rows
        use_container_width=True
    )
    
    # --- SAVE LOGIC ---
    # Update DB if quantities changed
    if st.button("Save Changes & Recalculate"):
        # 1. Update/Add items
        for index, row in edited_df.iterrows():
             if pd.notna(row.get('id')):
                 db_item = next((x for x in cart_items if x['id'] == row['id']), None)
                 if db_item:
                     new_qty = row.get('Requested_Qty')
                     if new_qty is not None and new_qty != db_item['qty']:
                         logic.update_cart_item_db(row['id'], new_qty)
             
        # 2. Delete items that were removed in the editor
        # (Compare IDs in edited_df vs cart_items)
        if not edited_df.empty:
            current_ids = set(edited_df['id'].dropna())
            for item in cart_items:
                if item['id'] not in current_ids:
                    logic.remove_from_cart_db(item['id'])
        else:
            # If editor is empty, clear cart
            logic.clear_cart_db(user_id)
            
        st.success("Cart Updated!")
        st.rerun()

    # --- TOTALS & ACTIONS ---
    selected_rows = edited_df[edited_df["Select"] == True]
    
    total_req = 0
    total_alloc = 0
    
    for _, row in selected_rows.iterrows():
        price = row.get('Price', 0)
        req = row.get('Requested_Qty', 0)
        alloc = row.get('Allocated_Qty', 0)
        total_req += price * req
        total_alloc += price * alloc
        
    c1, c2 = st.columns(2)
    c1.metric("Total (Requested)", f"${total_req:.2f}")
    c2.metric("Total (Allocated)", f"${total_alloc:.2f}")

    cl, cr = st.columns([1, 1])
    with cl:
        if st.button("Clear Cart"):
            logic.clear_cart_db(user_id)
            st.rerun()
    with cr:
        if st.button("Checkout Selected", type="primary", use_container_width=True):
            if selected_rows.empty:
                st.warning("No items selected.")
                return
            
            # Prepare Items
            items_to_order = selected_rows.to_dict('records')
            # Fix keys
            for item in items_to_order:
                item['part_number'] = item.get('Part Number')
                item['qty'] = item.get('Requested_Qty')
                item['price'] = item.get('Price')
                item['description'] = item.get('Description')
                item['supersedes'] = item.get('Supersedes')
            
            stock_type = st.session_state.user.get('assigned_stock_type', 'parts_stock')
            success, msg = logic.create_order(user_id, items_to_order, stock_type)
            
            if success:
                # Remove ordered items
                for _, row in selected_rows.iterrows():
                    logic.remove_from_cart_db(row['id'])
                st.balloons()
                st.success(f"Order Placed! #{msg}")
                time.sleep(2)
                st.rerun()
            else:
                st.error(f"Order Failed: {msg}")

def display_order_history(user_id, key_prefix="default"):
    st.markdown("### 📜 Order History")
    orders = logic.get_user_orders(user_id)
    
    if not orders:
        st.info("No past orders.")
        return

    # Prepare DataFrame
    df = pd.DataFrame(orders)
    # Add S.No
    df.insert(0, 'S.No', range(1, len(df) + 1))
    
    # Check what columns we have: order_id, total_price, order_status, timestamp
    # Rename for display
    # Sort by ID desc
    user_orders = sorted(orders, key=lambda x: x['order_id'], reverse=True)
    
    for row in user_orders:
        # Calculate Dual Totals for Header
        # We need details to sum them. 
        # CAUTION: Fetching details for EVERY order in history might be slow if many orders.
        # Efficient way: The 'orders' table only has total_alloc_price. 
        # To show Total Requested in header, we need to sum it from items.
        # We can do this on query or just fetch here.
        
        details = logic.get_order_details(row['order_id'])
        
        header_tot_req = 0
        header_tot_alloc = 0
        for d in details:
            p = d.get('price', 0) or 0
            header_tot_req += p * (d.get('requested_qty', 0) or 0)
            header_tot_alloc += p * (d.get('qty', 0) or 0) # qty is allocated
            
        custom_label = f"#{row['order_id']} | {row['timestamp'].strftime('%Y-%m-%d %H:%M')} | Req: ${header_tot_req:.2f} | Alloc: ${header_tot_alloc:.2f} | {row['order_status']}"
        
        with st.expander(custom_label):
            # Details View
            if details:
                # Helper to format filename
                # [Source]-[Type]-[User]-[Time]
                # Source: nmc vs hbd determined from stock_type or prefix? 
                # Current user's stock type dictates the view usually.
                # Or assume NMC/HBD prefix based on order's stock_type.
                # Order row has `stock_type`.
                src_code = "nmc" if row.get('stock_type') == 'parts_stock' else "hbd"
                timestamp_str = datetime.now().strftime("%Y%m%d-%H%M")
                
                # Dual Totals
                tot_req = 0
                tot_alloc = 0
                
                d_df = pd.DataFrame(details)
                
                # Pre-processing for Clean display
                # DB 'qty' is actually the Allocated amount saved in order_items.qty
                # DB 'requested_qty' is Requested.
                
                # Map columns to Standard 10
                # Map columns to Standard Headers
                d_df['Select'] = False
                d_df.insert(0, 'S.No', range(1, len(d_df) + 1))
                
                # Correct internal keys to match Standard Config
                d_df = d_df.rename(columns={
                    'part_number': 'Part Number',
                    'requested_qty': 'Requested_Qty',
                    'description': 'Description',
                    'price': 'Price',
                    'available_qty': 'Available_Qty',
                    'qty': 'Allocated_Qty',
                    'no_record_flag': 'No Record',
                    'supersedes': 'Supersedes'
                })
                
                # Back Order Calculation for display
                if 'Requested_Qty' in d_df.columns and 'Allocated_Qty' in d_df.columns:
                    d_df['Back Order'] = (d_df['Requested_Qty'] - d_df['Allocated_Qty']).clip(lower=0)
                
                # Status Calculation
                def get_status(r):
                    req = r.get('Requested_Qty', 0) or 0
                    alloc = r.get('Allocated_Qty', 0) or 0
                    if alloc >= req: return "Fully Allocated"
                    if alloc > 0: return "Partial Fulfillment"
                    return "Out of Stock"
                
                d_df['Status'] = d_df.apply(get_status, axis=1)
                
                # Reorder
                cols = ['Select', 'S.No', 'Part Number', 'Description', 'Price', 'Available_Qty', 'Requested_Qty', 'Allocated_Qty', 'Back Order', 'Supersedes', 'Status', 'No Record']
                final_cols = [c for c in cols if c in d_df.columns]
                d_df = d_df[final_cols]
                
                # Calculate Totals
                for _, i_row in d_df.iterrows():
                    p = i_row.get('price', 0) or 0
                    tot_req += p * (i_row.get('requested_qty', 0) or 0)
                    tot_alloc += p * (i_row.get('allocated_qty', 0) or 0)
                
                c1, c2 = st.columns(2)
                c1.metric("Total (Requested)", f"${tot_req:.2f}")
                c2.metric("Total (Allocated)", f"${tot_alloc:.2f}")

                st.write("Order Items:")
                st.dataframe(
                    d_df, 
                    hide_index=True,
                    column_config=get_standard_config()
                )
                
                # File Name: [Source]-[Type]-[User]-[Time]
                # Type = order-[id]
                 
                fname = f"{src_code}-order-{row['order_id']}-{user_id}-{timestamp_str}.csv"
                
                # Download Button for this order
                # We need to construct a CSV for this order
                csv_data = d_df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label=f"Download Order #{row['order_id']}",
                    data=csv_data,
                    file_name=fname,
                    mime="text/csv",
                    key=f"{key_prefix}_dl_{row['order_id']}"
                )
            else:
                st.warning("No items found for this order.")

# Standard Table Configuration
def get_standard_config():
    return {
        "Select": st.column_config.CheckboxColumn("Select", default=False, width=None),
        "S.No": st.column_config.TextColumn("S.No", width=None, disabled=True),
        "Part Number": st.column_config.TextColumn("Part Number", width=None, disabled=True),
        "Description": st.column_config.TextColumn("Description", width=None, disabled=True),
        "Price": st.column_config.NumberColumn("Price", format="%.2f", width=None, disabled=True),
        "Available_Qty": st.column_config.NumberColumn("Available Qty", width=None, disabled=True, format="%d"),
        "Requested_Qty": st.column_config.NumberColumn("Required Qty", width=None, min_value=0, format="%d"),
        "Allocated_Qty": st.column_config.NumberColumn("Allocated Qty", width=None, disabled=True, format="%d"),
        "Back Order": st.column_config.NumberColumn("Back Order", width=None, disabled=True, format="%d"),
        "Supersedes": st.column_config.TextColumn("Supersedes", width=None, disabled=True),
        "Status": st.column_config.TextColumn("Status", width=None, disabled=True),
        "No Record": st.column_config.CheckboxColumn("No Record", width=None, disabled=True),
        "id": None,
        "real_part_number": None,
        "Requested Input": None,
        # Legacy compatibility
        "part_number": None,
        "description": None,
        "price": None,
        "available_qty": None,
        "requested_qty": None,
        "allocated_qty": None,
        "back_order": None,
        "supersedes": None,
        "status": None,
        "no_record": None,
        "qty": None
    }

def parts_enquiry_tab():
    st.subheader("Parts Enquiry & Cart")
    
    col_search, col_cart = st.columns([1, 1], gap="medium")
    
    with col_search:
        st.markdown("### 🔍 Search Parts")
        search = st.text_input("Search Part Number or Description", placeholder="Type to search...", label_visibility="collapsed")
        
        if search:
            user_stock = st.session_state.user.get('assigned_stock_type', 'parts_stock')
            user_adj = st.session_state.user.get('price_adjustment_percent', 0.0)
            results = logic.get_parts_like(search, user_stock, user_adj)
            
            if results:
                # Convert results to DataFrame for table view
                res_data = []
                s_no_counter = 1
                
                def add_to_results(part_obj, is_superseded=False, parent_pn=None):
                    nonlocal s_no_counter
                    pn = part_obj.part_number
                    
                    # Avoid duplicates in the same search result view if possible
                    # (Though get_parts_like already has seen_parts logic)
                    
                    res_data.append({
                        'S.No': s_no_counter,
                        'Part Number': pn,
                        'Description': part_obj.description,
                        'Price': part_obj.price,
                        'Available_Qty': int(getattr(part_obj, 'free_stock', 0) or 0),
                        'Requested_Qty': 1 if int(getattr(part_obj, 'free_stock', 0) or 0) > 0 else 0,
                        'Supersedes': parent_pn if is_superseded else getattr(part_obj, 'superseded_part', None).part_number if hasattr(part_obj, 'superseded_part') and part_obj.superseded_part else None,
                        'Select': False
                    })
                    s_no_counter += 1
                    
                    # Recursively add superseded parts if they exist
                    sup_part = getattr(part_obj, 'superseded_part', None)
                    if sup_part:
                        add_to_results(sup_part, is_superseded=True, parent_pn=pn)

                for r in results:
                    add_to_results(r)
                    
                df_results = pd.DataFrame(res_data)
                
                # Show results in data_editor
                edited_results = st.data_editor(
                    df_results,
                    key="enquiry_editor",
                    hide_index=True,
                    column_config=get_standard_config(),
                    use_container_width=True
                )
                
                if st.button("Add Selected to Cart", type="primary", use_container_width=True):
                    selected = edited_results[edited_results['Select'] == True]
                    if selected.empty:
                        st.warning("No items selected.")
                    else:
                        for _, row in selected.iterrows():
                            # Find the matching result object to handle recursive supersession if needed
                            # But for the table view, we just add the part directly as selected.
                            # Requirement: "Selection & Cart Entry: * Include a checkbox for item selection and a dedicated Required Qty input field on each row."
                            
                            logic.add_to_cart_db(
                                st.session_state.user['user_id'],
                                row['Part Number'],
                                row['Description'],
                                row['Requested_Qty'],
                                row['Price'],
                                supersedes=row['Supersedes'] if row['Supersedes'] else None
                            )
                        st.success("Selected items added to cart!")
                        time.sleep(0.5)
                        st.rerun()
            else:
                st.warning("No parts found.")
        else:
            st.info("Start typing to search for parts...")

    with col_cart:
        show_cart_ui(st.session_state.user['user_id'])
        
    st.divider()
    display_order_history(st.session_state.user['user_id'], key_prefix="enquiry")

def bulk_order_tab():
    st.subheader("Bulk Order Upload")
    
    col_info, col_dl = st.columns([3, 1])
    with col_info:
        st.info("Upload CSV with columns: part_number, qty. Description and Price will be fetched automatically.")
    with col_dl:
        # Template
        template_df = pd.DataFrame([{"part_number": "EXAMPLE-123", "qty": 10}])
        st.download_button(
            label="📥 Download Template",
            data=template_df.to_csv(index=False).encode('utf-8'),
            file_name="bulk_order_template.csv",
            mime="text/csv",
            key="bulk_templ_btn"
        )

    uploaded = st.file_uploader("Upload CSV", type="csv")
    
    if "bulk_stage" not in st.session_state:
        st.session_state.bulk_stage = None
    if "bulk_df" not in st.session_state:
        st.session_state.bulk_df = pd.DataFrame() # Initialize empty DataFrame

    if uploaded:
        try:
            # If a new file is uploaded, process it
            # FIX: Only process if NOT in success state (to avoid overwriting success msg)
            if st.session_state.bulk_stage != "success" and (st.session_state.bulk_stage != "review" or uploaded.name != st.session_state.get("last_uploaded_file_name")):
                df_in = pd.read_csv(uploaded)
                user_stock = st.session_state.user.get('assigned_stock_type', 'parts_stock')
                user_adj = st.session_state.user.get('price_adjustment_percent', 0.0)
                review_df = logic.process_bulk_enquiry(df_in, user_stock, user_adj)
                st.session_state.bulk_df = review_df
                st.session_state.bulk_stage = "review"
                st.session_state.last_uploaded_file_name = uploaded.name
            
            bulk_df = st.session_state.bulk_df.copy() # Work with a copy
            
            st.info("Markup: Edit values below. Uncheck items to exclude from order.")
            
            # Staging Editor
            # Logic creates 'Part Number' (Original), 'Description', 'Price', 'Stock', 'Allocated', 'No Record', 'Status'
            # System cols: 'real_part_number', 'supersedes', 'qty'
            
            # Map for Display Config (Column Config expects keys to match DF columns)
            # Our DF has capitalized keys optionally? Logic returned Capitalized 'Part Number'.
            # Let's Normalize to standard Keys for the Editor Config to work (which uses 'part_number', 'description' etc)
            # OR Update Config to handle 'Part Number'.
            # Better: Rename columns here to match Standard Config keys.
            
            # Ensure columns are present for config mapping
            # logic.py returns capitalized headers.
            
            # Ensure Select
            if 'Select' not in bulk_df.columns:
                bulk_df.insert(0, 'Select', True)
            
            # Columns to Show (Streamlit data_editor shows columns in this order)
            cols = ['Select', 'S.No', 'Part Number', 'Description', 'Price', 'Available_Qty', 'Requested_Qty', 'Allocated_Qty', 'Back Order', 'Supersedes', 'Status', 'No Record', 'real_part_number']
            
            # Ensure columns are present for config mapping
            # logic.py returns capitalized headers: Part Number, Requested_Qty, etc.
            
            # Ensure Select
            if 'Select' not in bulk_df.columns:
                bulk_df.insert(0, 'Select', True)
            
            # Columns to Show (Streamlit data_editor shows columns in this order)
            cols = ['Select', 'S.No', 'Part Number', 'Description', 'Price', 'Available_Qty', 'Requested_Qty', 'Allocated_Qty', 'Back Order', 'Supersedes', 'Status', 'No Record', 'real_part_number']
            
            # Ensure case-sensitive keys match what get_standard_config expects
            expected_renames = {
                'part_number': 'Part Number',
                'description': 'Description',
                'price': 'Price',
                'available_qty': 'Available_Qty',
                'requested_qty': 'Requested_Qty',
                'allocated_qty': 'Allocated_Qty',
                'back_order': 'Back Order',
                'no_record': 'No Record',
                'status': 'Status',
                'supersedes': 'Supersedes'
            }
            bulk_df = bulk_df.rename(columns=lambda x: expected_renames.get(x.lower().replace(" ", "_"), x))

            final_cols = [c for c in cols if c in bulk_df.columns]
            bulk_df = bulk_df[final_cols]
            
            # HIDE TABLE IF SUCCESS
            if st.session_state.bulk_stage == "success":
                 st.success("Bulk Order Processed Successfully! See Order History below.")
                 if st.button("Start New Bulk Order"):
                     st.session_state.bulk_stage = None # Go back to start
                     st.session_state.pop("bulk_df", None) # Clear data
                     st.session_state.pop("last_uploaded_file_name", None)
                     st.rerun()
            else:
                edited_df = st.data_editor(
                    bulk_df,
                    key="bulk_editor",
                    hide_index=True,
                    column_config=get_standard_config(),
                    num_rows="dynamic", # Allow deleting rows
                    use_container_width=True
                )
                
                # Button Logic
                if edited_df is not None:
                    selected_rows = edited_df[edited_df["Select"] == True]
                    
                    # Recalculate Total on Fly
                    total_est_req = 0
                    total_est_alloc = 0
                    
                    for _, row in selected_rows.iterrows():
                        p = row.get('Price', 0)
                        if pd.notna(p):
                            total_est_req += p * (row.get('Requested_Qty', 0) or 0)
                            alloc = row.get('Allocated_Qty', 0)
                            total_est_alloc += p * alloc
                    
                    c1, c2 = st.columns(2)
                    c1.metric("Total (Requested)", f"${total_est_req:.2f}")
                    c2.metric("Total (Allocated)", f"${total_est_alloc:.2f}", delta_color="normal")
                    
                    if st.button("Process Bulk Order (Selected Only)", type="primary"):
                        if selected_rows.empty:
                            st.warning("No rows selected.")
                        else:
                            # Validation loop
                            valid_items = []
                            for _, row in selected_rows.iterrows():
                                 if not row.get('No Record', False):
                                     # Use REAL Part Number if available (for supersession)
                                     pn = row.get('real_part_number')
                                     if pd.isna(pn) or str(pn) == "":
                                         pn = row['Part Number']
                                         
                                     # Standardize Item Dict for Create Order
                                     item = {
                                         "part_number": pn,
                                         "description": row['Description'],
                                         "qty": int(row['Requested_Qty']), # Req Qty
                                         "price": float(row['Price']),
                                         "supersedes": row.get('Supersedes')
                                     }
                                     valid_items.append(item)
                            
                            if not valid_items:
                                 st.warning("No valid items to order (Check allocation).")
                            else:
                                stock_type = st.session_state.user.get('assigned_stock_type', 'parts_stock')
                                success, msg = logic.create_order(st.session_state.user['user_id'], valid_items, stock_type)
                                
                                if success:
                                    st.session_state.bulk_stage = "success"
                                    st.rerun()
                                else:
                                    st.error(f"Order failed: {msg}")

        except Exception as e:
            st.error(f"Error processing file: {e}")
            st.session_state.bulk_stage = None # Reset stage on error
            st.session_state.pop("bulk_df", None)
            st.session_state.pop("last_uploaded_file_name", None)
    elif st.session_state.bulk_stage == "success":
        # If no file uploaded but previous state was success, show success message
        st.success("Bulk Order Processed Successfully! See Order History below.")
        if st.button("Start New Bulk Order"):
            st.session_state.bulk_stage = None
            st.session_state.pop("bulk_df", None)
            st.session_state.pop("last_uploaded_file_name", None)
            st.rerun()
    else:
        st.info("Upload a CSV file to begin a bulk order.")

    st.divider()
    display_order_history(st.session_state.user['user_id'], key_prefix="bulk")

def admin_dashboard():
    st.subheader("Admin Dashboard")
    
    # 1. User Management (Editable)
    st.markdown("### 👥 User Management")
    users = logic.get_all_users()
    if users:
        df_users = pd.DataFrame(users)
        # Ensure correct column order and types
        df_users['assigned_stock_type'] = df_users['assigned_stock_type'].fillna('parts_stock')
        
        edited_users = st.data_editor(
            df_users,
            key="user_editor",
            hide_index=True,
            column_config={
                "user_id": st.column_config.NumberColumn("ID", disabled=True, width=None),
                "user_name": st.column_config.TextColumn("Username", disabled=True, width=None),
                "mail_id": st.column_config.TextColumn("Email", disabled=True, width=None),
                "phone_number": st.column_config.TextColumn("Phone", disabled=True, width=None),
                "is_active": st.column_config.CheckboxColumn("Active?", default=False, width=None),
                "role": st.column_config.SelectboxColumn("Role", options=["Standard User", "Admin"], width=None),
                "assigned_stock_type": st.column_config.SelectboxColumn("Assigned Stock", options=["parts_stock", "HBD_stock"], width=None),
                "price_adjustment_percent": st.column_config.NumberColumn("Price Adj %", format="%.2f%%", help="Positive for markup, Negative for discount", width=None)
            },
            use_container_width=True
        )
        
        if st.button("Save User Changes"):
            # Compare original vs edited to apply updates
            # Ideally we only update changed rows.
            # For simplicity, we loop all and update if changed (or just update all if small).
            # Let's iterate over edited_users.
            
            for index, row in edited_users.iterrows():
                # Find original
                orig = next((u for u in users if u['user_id'] == row['user_id']), None)
                if orig:
                    # Update Status
                    if row['is_active'] != orig['is_active']:
                        logic.update_user_status(row['user_id'], row['is_active'])
                    # Update Role
                    if row['role'] != orig['role']:
                        logic.update_user_role(row['user_id'], row['role'])
                    # Update Stock Assignment
                    # Update Stock Assignment
                    if row['assigned_stock_type'] != orig['assigned_stock_type']:
                        logic.update_user_stock_assignment(row['user_id'], row['assigned_stock_type'])
                    # Update Price Adjustment
                    # Handle NaN or None
                    new_adj = row.get('price_adjustment_percent', 0)
                    orig_adj = orig.get('price_adjustment_percent', 0)
                    # Convert to float for comparison
                    try:
                        new_adj = float(new_adj)
                    except: 
                        new_adj = 0.0
                        
                    if new_adj != float(orig_adj):
                        logic.update_user_price_adjustment(row['user_id'], new_adj)
            
            st.success("User updates saved!")
            st.rerun()
    else:
        st.info("No users found.")
        
    st.markdown("### 🔑 Password Management")
    st.caption("Generate Temporary Password (User will be forced to change it)")
    
    col_reset_1, col_reset_2 = st.columns(2)
    with col_reset_1:
         # Searchable Dropdown
         options = [f"{u['user_id']} | {u['user_name']}" for u in users]
         selected_reset = st.selectbox("Select User (ID | Name)", options, index=None, placeholder="Type to search ID or Name")
         temp_pass = st.selectbox("Temporary Password", options=["temp_pass_123", "password", "123456"]) # Replaced text_input with selectbox
    with col_reset_2:
         st.write("")
         st.write("")
         if st.button("Reset Password"):
             if selected_reset and temp_pass:
                 # Extract ID
                 target_uid = int(selected_reset.split(" | ")[0])
                 # Find name for msg
                 target_name = selected_reset.split(" | ")[1]
                 
                 success, msg = auth.reset_password_admin(target_uid, temp_pass)
                 if success:
                     st.success(f"Password reset for User {target_uid} ({target_name}). {msg}")
                 else:
                     st.error(msg)
             else:
                 st.error("Select User and Enter Password.")

    st.divider()

    # 2. Stock Management (Dual Streams)
    st.markdown("### 📦 Stock Management")
    tab_parts, tab_hbd = st.tabs(["Parts Stock", "HBD Stock"])
    
    with tab_parts:
        st.caption("Manage Standard Parts Stock")
        col1, col2 = st.columns(2)
        with col1:
             up_p = st.file_uploader("Upload Parts Stock (CSV: part_number, description, stock, price($))", type="csv", key="up_parts")
             if up_p:
                 try:
                     df = pd.read_csv(up_p)
                     upload_stype = "parts_stock"
                     if st.button(f"Upload to {upload_stype}"):
                        with st.status(f"Uploading {upload_stype}...", expanded=True) as status:
                            logic.upload_parts_stock(df, upload_stype)
                            status.update(label="Upload complete!", state="complete", expanded=False)
                        st.success(f"Successfully uploaded {len(df)} records to {upload_stype}")
                 except Exception as e:
                     st.error(f"Error: {e}")
        with col2:
            st.warning("Danger Zone")
            stock_type_to_reset = "parts_stock"
            with st.popover(f"RESET {stock_type_to_reset.replace('_', ' ').upper()}", use_container_width=True):
                st.warning(f"Are you sure you want to delete ALL data for {stock_type_to_reset}? This cannot be undone.")
                if st.button("Confirm Reset", type="danger", key="confirm_reset_parts"):
                    with st.status("Resetting stock...", expanded=True) as status:
                        logic.reset_stock(stock_type_to_reset)
                        status.update(label="Stock reset complete!", state="complete", expanded=False)
                    st.success(f"Stock reset successfully for {stock_type_to_reset}")
                    st.rerun()

    with tab_hbd:
        st.caption("Manage HBD Stock")
        col1, col2 = st.columns(2)
        with col1:
             up_h = st.file_uploader("Upload HBD Stock (CSV: part_number, description, stock, price($))", type="csv", key="up_hbd")
             if up_h:
                 try:
                     df = pd.read_csv(up_h)
                     upload_stype = "HBD_stock"
                     if st.button(f"Upload to {upload_stype}"):
                        with st.status(f"Uploading {upload_stype}...", expanded=True) as status:
                            logic.upload_parts_stock(df, upload_stype)
                            status.update(label="Upload complete!", state="complete", expanded=False)
                        st.success(f"Successfully uploaded {len(df)} records to {upload_stype}")
                 except Exception as e:
                     st.error(f"Error: {e}")
        with col2:
            st.warning("Danger Zone")
            stock_type_to_reset = "HBD_stock"
            with st.popover(f"RESET {stock_type_to_reset.replace('_', ' ').upper()}", use_container_width=True):
                st.warning(f"Are you sure you want to delete ALL data for {stock_type_to_reset}? This cannot be undone.")
                if st.button("Confirm Reset", type="danger", key="confirm_reset_hbd"):
                    with st.status("Resetting stock...", expanded=True) as status:
                        logic.reset_stock(stock_type_to_reset)
                        status.update(label="Stock reset complete!", state="complete", expanded=False)
                    st.success(f"Stock reset successfully for {stock_type_to_reset}")
                    st.rerun()

    st.divider()

    # 3. Order Management & Oversight (Split Tables)
    st.markdown("### 📋 Orders Overview")
    orders = logic.get_all_orders()
    
    if orders:
        # Separate orders
        df_orders = pd.DataFrame(orders)
        # Ensure stock_type exists (older orders might be null)
        if 'stock_type' not in df_orders.columns:
             df_orders['stock_type'] = 'parts_stock'
        df_orders['stock_type'] = df_orders['stock_type'].fillna('parts_stock')
        
        parts_orders = df_orders[df_orders['stock_type'] == 'parts_stock']
        hbd_orders = df_orders[df_orders['stock_type'] == 'HBD_stock']
        
        t1, t2 = st.tabs(["Parts Orders", "HBD Orders"])
        
        for tab, data, label in [(t1, parts_orders, "Parts"), (t2, hbd_orders, "HBD")]:
            with tab:
                if data.empty:
                    st.info(f"No {label} orders.")
                else:
                    st.dataframe(
                        data,
                        column_config={
                            "order_id": st.column_config.NumberColumn("Order ID", format="%d", width=None),
                            "user_id": st.column_config.NumberColumn("User ID", format="%d", width=None),
                            "total_price": st.column_config.NumberColumn("Total", format="$%.2f", width=None),
                            "order_status": st.column_config.TextColumn("Status", width=None),
                            "stock_type": st.column_config.TextColumn("Stock Type", width=None),
                            "timestamp": st.column_config.DatetimeColumn("Date", format="DD/MM/YYYY HH:mm", width=None)
                        },
                        use_container_width=True,
                        hide_index=True # Added hide_index
                    )
                    
                    st.warning("Danger Zone")
                    stype_orders = "parts_stock" if label == "Parts" else "HBD_stock"
                    with st.popover(f"CLEAR ALL {label.upper()} ORDERS", use_container_width=True):
                        st.warning(f"Are you sure you want to delete ALL {label} orders? This cannot be undone.")
                        if st.button("Clear Order Overview", type="danger", key=f"confirm_clear_{label}"):
                            with st.status("Clearing orders...", expanded=True) as status:
                                logic.delete_all_orders(stype_orders)
                                status.update(label="Orders cleared!", state="complete", expanded=False)
                            st.success(f"All orders cleared for {stype_orders}")
                            st.rerun()
                    
                    # Action handling per order (Simplified for list)
                    # To add "Accept/Reject", we probably need an expander per row or a selector.
                    # Requirement: "Action Icons: Include 'Accept' and 'Reject' actions... represented by checkmark/tick icons"
                    # Implementing actions in a bulk table is hard in pure Streamlit without custom components or data_editor with callback.
                    # Let's use the Expander loop approach for detailed actions as it was before, but filtered.
                    
                    for index, order in data.iterrows():
                        with st.expander(f"#{order['order_id']} | User: {order['user_id']} | ${order['total_price']} | {order['order_status']}"):
                            details = logic.get_order_details(order['order_id'])
                            st.dataframe(pd.DataFrame(details))
                            
                            c1, c2, c3 = st.columns(3)
                            if st.button("✅ Accept", key=f"acc_{label}_{order['order_id']}"):
                                logic.update_order_status(order['order_id'], "Accepted")
                                st.rerun()
                            if st.button("❌ Reject", key=f"rej_{label}_{order['order_id']}"):
                                logic.update_order_status(order['order_id'], "Rejected")
                                st.rerun()
                            if st.button("🗑️ Delete", key=f"del_one_{label}_{order['order_id']}"):
                                logic.delete_order(order['order_id'])
                                st.success("Deleted")
                                st.rerun()
        
        st.divider()
        st.warning("⚠️ GLOBAL DATA DELETION")
        with st.popover("DELETE ALL USERS' ORDER HISTORY (Global Wipe)", use_container_width=True):
            st.warning("Are you sure you want to delete ALL users' order history? This cannot be undone.")
            if st.button("Confirm Global Order History Wipe", type="danger", key="confirm_global_wipe"):
                with st.status("Wiping all order history...", expanded=True) as status:
                    logic.delete_all_users_history()
                    status.update(label="All order history wiped!", state="complete", expanded=False)
                st.success("All history wiped.")
                st.rerun()
    else:
        st.info("No orders found.")
        
    st.divider()
    st.markdown("### 🔧 Database Maintenance")
    if st.button("Force Drop Legacy Columns (Fix Schema)", type="primary"):
        success, msg = logic.force_schema_cleanup()
        if success:
            st.success(f"Cleanup executed: {msg}")
        else:
            st.error(f"Cleanup failed: {msg}")

def main_app():
    user = st.session_state.user
    
    # Force Password Change Check
    if user.get('require_password_change'):
        st.warning("⚠️ Security Alert: You must change your password to proceed.")
        
        with st.form("force_change_pass_form"):
            cur_pass = st.text_input("Current (Temp) Password", type="password", key="force_cur")
            n_p1 = st.text_input("New Password", type="password", key="force_n1")
            n_p2 = st.text_input("Confirm New", type="password", key="force_n2")
            
            if st.form_submit_button("Set New Password"):
                 if n_p1 != n_p2:
                     st.error("Mismatch")
                 else:
                     success, msg = auth.change_password(user['user_id'], cur_pass, n_p1)
                     if success:
                         st.success("Password Updated! Please continue.")
                         # Update session to remove flag
                         st.session_state.user['require_password_change'] = False
                         st.rerun()
                     else:
                         st.error(msg)
        
        return # Stop execution of main app

    
    # Sidebar
    try:
        st.sidebar.image(COMPANY_LOGO)
    except Exception:
        pass # Fail silently in sidebar or show text
    st.sidebar.markdown(f"Welcome, **{user['user_name']}**")
    if user.get("is_admin"):
        st.sidebar.badge("ADMIN")
        mode = st.sidebar.radio("Mode", ["Dashboard", "App View"])
    else:
        mode = "App View"
        
    if st.sidebar.button("Logout"):
        st.session_state.logged_in = False
        st.session_state.user = None
        st.rerun()
        
    # Main Content
    if mode == "Dashboard":
        admin_dashboard()
    else:
        tab1, tab2, tab3 = st.tabs(["Parts Enquiry", "Bulk Order", "Profile"])
        
        with tab1:
            parts_enquiry_tab()
        with tab2:
            bulk_order_tab()
        with tab3:
            st.subheader("Profile")
            new_mail = st.text_input("Email", value=user.get('mail_id') or "")
            new_phone = st.text_input("Phone", value=user.get('phone_number') or "")
            if st.button("Update Profile"):
                auth.update_profile(user['user_id'], new_mail, new_phone)
                st.session_state.user['mail_id'] = new_mail
                st.session_state.user['phone_number'] = new_phone
                st.success("Updated!")
            
            st.divider()
            st.markdown("### 🔐 Security")
            with st.expander("Change Password"):
                with st.form("change_pass_form"):
                    cur_pass = st.text_input("Current Password", type="password")
                    new_pass_1 = st.text_input("New Password", type="password")
                    new_pass_2 = st.text_input("Confirm New Password", type="password")
                    if st.form_submit_button("Update Password"):
                        if new_pass_1 != new_pass_2:
                            st.error("New passwords do not match")
                        else:
                            success, msg = auth.change_password(user['user_id'], cur_pass, new_pass_1)
                            if success:
                                st.success(msg)
                            else:
                                st.error(msg)
            
            st.divider()
            st.markdown("### 📥 Data Export")
            user_stock = st.session_state.user.get('assigned_stock_type', 'parts_stock')
            csv_data = logic.get_stock_csv(user_stock)
            
            # Name: [Source]-[Type]-[User]-[Time]
            src_code = "nmc" if user_stock == 'parts_stock' else "hbd"
            timestamp_str = datetime.now().strftime("%Y%m%d-%H%M")
            fname = f"{src_code}-stock-{user['user_id']}-{timestamp_str}.csv"
            
            st.download_button(
                label=f"Download My Stock File ({user_stock})",
                data=csv_data,
                file_name=fname,
                mime="text/csv"
            )

if not st.session_state.logged_in:
    # Persistence Check
    token = st.query_params.get("token")
    if token:
        # Simple Insecure Token currently just User ID
        try:
            uid = int(token)
            users = auth.get_all_users()
            u = next((x for x in users if x['user_id'] == uid), None)
            if u:
                st.session_state.logged_in = True
                st.session_state.user = u
                st.rerun()
        except:
             pass
             
    if not st.session_state.logged_in:
        login_page()
else:
    main_app()

