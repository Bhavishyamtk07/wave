import streamlit as st
import pandas as pd
import time
import datetime
import re
import os
import db_manager as db
import scanner
from streamlit_autorefresh import st_autorefresh 
import plotly.express as px
import plotly.graph_objects as go

import calendar
import plotly.express as px # Requires: pip install plotly

# --- SETUP & STATE ---
st.set_page_config(page_title="AirMark Attendance", layout="wide", page_icon="📡")

# --- CUSTOM CSS ---
st.markdown("""
    <style>
    .wave-title {
        font-family: 'Helvetica Neue', sans-serif; font-size: 3rem; font-weight: 800;
        text-align: center;
        background: -webkit-linear-gradient(45deg, #00d2ff, #3a7bd5, #ffffff);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        margin-bottom: 0px; margin-top: -20px;
    }
    .wave-subtitle { text-align: center; color: #b0c4de; font-size: 1.2rem; margin-top: -10px; margin-bottom: 30px; }
    .sync-icon { font-size: 2.5rem; text-align: center; margin-top: 15px; }
    @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
    .sync-spinner {
        font-size: 2.5rem; display: inline-block;
        animation: spin 1.5s linear infinite; margin-top: 15px; text-align: center;
    }
    </style>
""", unsafe_allow_html=True)

# --- SESSION STATE ---
if 'start_time' not in st.session_state: st.session_state.start_time = None
if 'running' not in st.session_state: st.session_state.running = False
if 'scan_cycles' not in st.session_state: st.session_state.scan_cycles = 0
if 'review_mode' not in st.session_state: st.session_state.review_mode = False
if 'finalized_mode' not in st.session_state: st.session_state.finalized_mode = False
if 'manual_overrides' not in st.session_state: st.session_state.manual_overrides = {}
if 'final_report_data' not in st.session_state: st.session_state.final_report_data = None

# db.init_master_db()

# --- UTILS ---
def validate_mac(mac):
    # Strict Format: XX:XX:XX:XX:XX:XX
    return re.match(r"^([0-9A-Fa-f]{2}[:]){5}([0-9A-Fa-f]{2})$", mac)

def validate_roll(roll):
    # Range 0-100
    try:
        r = int(roll)
        return 0 <= r <= 100
    except:
        return False

def categorize_status(count, max_cycles):
    if max_cycles == 0: return "Absent", "grey"
    ratio = count / max_cycles
    if ratio >= 0.75: return "Present", "green"
    elif ratio >= 0.25: return "Action Required", "orange"
    elif count > 0: return "Suspicious", "red"
    else: return "Absent", "grey"

# --- HEADER ---
head_c1, head_c2, head_c3 = st.columns([1, 8, 1])
with head_c1:
    status_placeholder = st.empty()
    if not st.session_state.running:
        status_placeholder.markdown('<div class="sync-icon">📡</div>', unsafe_allow_html=True)
with head_c2:
    st.markdown('<h1 class="wave-title">WAVE</h1>', unsafe_allow_html=True)
    st.markdown('<div class="wave-subtitle">Wi-Fi Attendance Verification Engine</div>', unsafe_allow_html=True)

# --- TABS ---
if st.session_state.finalized_mode:
    # Special View for Final Report
    tabs = ["✅ Final Report"]
    tab_final = st.tabs(tabs)[0]
else:
    tab1, tab2, tab5, tab3, tab4, tab6 = st.tabs(["📡 Live Session", "🛠️ Manage Students", "🏫 Manage Subjects", "📊 View Registry", "🚫 Blocklist", "📈 Analytics" ])

# ==========================================
# FINAL REPORT VIEW (Post-Submission)
# ==========================================
if st.session_state.finalized_mode:
    with tab_final:
        st.header("Final Attendance Report")
        
        if st.session_state.final_report_data is not None:
            df = st.session_state.final_report_data
            
            # 1. Show Present
            present_df = df[df['Status'] == 'Present']
            st.success(f"### 🟢 Present ({len(present_df)})")
            st.dataframe(present_df[['Name', 'Roll', 'MAC']], use_container_width=True, hide_index=True)
            
            st.divider()
            
            # 2. Dropdown for Absent
            absent_df = df[df['Status'] != 'Present']
            with st.expander(f"🔴 View Absent / Others ({len(absent_df)})"):
                st.dataframe(absent_df[['Name', 'Roll', 'MAC', 'Status']], use_container_width=True, hide_index=True)
                
            # 3. Back Button (Refresh)
            st.divider()
            if st.button("⬅️ Back to Home / Start New Session"):
                # Reset Everything
                st.session_state.running = False
                st.session_state.review_mode = False
                st.session_state.finalized_mode = False
                st.session_state.scan_cycles = 0
                st.session_state.manual_overrides = {}
                st.session_state.final_report_data = None
                st.rerun()

# ==========================================
# TAB 5: MANAGE SUBJECTS
# ==========================================
if not st.session_state.finalized_mode:
    with tab5:
        st.header("🏫 Faculty & Subject Database")
        c_add, c_view = st.columns(2)
        with c_add:
            st.subheader("Add New Subject")
            with st.form("sub_form", clear_on_submit=True):
                sub_name = st.text_input("Subject Name")
                fac_name = st.text_input("Faculty Name")
                if st.form_submit_button("Add"):
                    if sub_name and fac_name:
                        safe_sub = "".join(x for x in sub_name if x.isalnum())
                        success, msg = db.add_faculty_subject(safe_sub, fac_name)
                        if success: st.success(f"✅ Added {safe_sub}")
                        else: st.error(msg)
                    else: st.warning("Fill all fields.")
        with c_view:
            st.subheader("Current Subjects")
            fac_df = db.get_all_faculty()
            if not fac_df.empty:
                st.dataframe(fac_df[['subject', 'faculty_name']], hide_index=True, use_container_width=True)
                opts = fac_df['subject'].tolist()
                del_sub = st.selectbox("Remove Subject", opts)
                if st.button("❌ Remove"):
                    db.remove_faculty_subject(del_sub)
                    st.rerun()

# ==========================================
# TAB 1: LIVE SESSION
# ==========================================
if not st.session_state.finalized_mode:
    with tab1:
        # Subject Selection
        db_subjects = db.get_faculty_subjects_list()
        subject_options = db_subjects if db_subjects else ["General - Default"]
        selected_full = st.sidebar.selectbox("Select Class", subject_options)
        
        if " - " in selected_full:
            selected_subject = selected_full.split(" - ")[0]
            current_faculty = selected_full.split(" - ")[1]
            st.sidebar.caption(f"Faculty: {current_faculty}")
        else:
            selected_subject = selected_full

        session_db_path = db.get_session_db_name(selected_subject)

        # Sidebar Controls
        with st.sidebar:
            st.divider()
            if not st.session_state.running and not st.session_state.review_mode:
                if st.button("▶️ START SESSION", type="primary", use_container_width=True):
                    st.session_state.running = True
                    st.session_state.start_time = time.time()
                    st.session_state.scan_cycles = 0
                    st.session_state.manual_overrides = {}
                    db.init_session_db(session_db_path)
                    db.reset_session_table(session_db_path)
                    st.rerun()
            
            elif st.session_state.running:
                # REFRESH TIME: 15 Seconds
                st_autorefresh(interval=15000, key="attendance_ping")
                elapsed = time.time() - st.session_state.start_time
                st.metric("Session Duration", str(datetime.timedelta(seconds=int(elapsed))))
                
                # TOTAL ONLINE vs TOTAL REGISTERED
                reg_count = len(db.get_all_registered())
                
                # Get current active count (Active devices minus blocked)
                # We need to fetch this from the last scan result or DB
                # Just using log DB for stats
                log_df_stat = db.get_session_data(session_db_path)
                # Estimate online now? 
                # Better: calculate from the scan we are about to do.
                
                if st.button("🛑 STOP & REVIEW", type="secondary", use_container_width=True):
                    st.session_state.running = False
                    st.session_state.review_mode = True
                    st.rerun()

        # PHASE 1: LIVE MONITORING
        if st.session_state.running:
            st.subheader(f"🔴 Live Monitoring: {selected_subject}")
            
            # Animation
            status_placeholder.markdown('<div class="sync-spinner">🔄</div>', unsafe_allow_html=True)
            
            # SCANNING (15s cycle handled by autorefresh)
            with st.spinner("Scanning Network..."):
                active_devs = scanner.get_active_devices() # 15s timeout inside scanner
                blocklist = db.get_blocklist()
                allowed_devs = [d for d in active_devs if d['mac'] not in blocklist]
                
                st.session_state.scan_cycles += 1
                db.update_session_log(session_db_path, allowed_devs)
            
            status_placeholder.markdown('<div class="sync-icon">✅</div>', unsafe_allow_html=True)
            
            # FETCH DATA
            log_df = db.get_session_data(session_db_path)
            reg_df = db.get_all_registered()
            
            current_active_macs = [d['mac'] for d in allowed_devs]
            
            # Show Total Online / Total Registered
            tot_reg = len(reg_df)
            tot_online_known = len(reg_df[reg_df['mac'].isin(current_active_macs)])
            st.metric("Total Online (Registered)", f"{tot_online_known} / {tot_reg}")
            
            # TABLES
            known_online = reg_df[reg_df['mac'].isin(current_active_macs)]
            known_offline = reg_df[~reg_df['mac'].isin(current_active_macs)]
            unknowns = log_df[(log_df['is_unknown'] == 1) & (log_df['mac'].isin(current_active_macs))]
            
            # FIXED HEIGHT CONTAINER (To prevent jumping)
            with st.container(height=500):
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.markdown(f"### 🟢 Online ({len(known_online)})")
                    if not known_online.empty:
                        # Merge to get last_seen
                        disp = pd.merge(known_online, log_df[['mac', 'last_seen']], on='mac', how='left')
                        st.dataframe(disp[['name', 'last_seen']], hide_index=True, use_container_width=True)
                    else: st.caption("None")
                
                with c2:
                    st.markdown(f"### 🔴 Offline ({len(known_offline)})")
                    if not known_offline.empty:
                        st.dataframe(known_offline[['name', 'roll_no']], hide_index=True, use_container_width=True)
                    else: st.caption("None")
                
                with c3:
                    st.markdown(f"### ⚠️ Unknown ({len(unknowns)})")
                    if not unknowns.empty:
                        st.dataframe(unknowns[['mac', 'last_seen']], hide_index=True, use_container_width=True)
                    else: st.caption("None")

        # PHASE 2: REVIEW MODE
        elif st.session_state.review_mode:
            st.subheader("🧐 Session Review")
            
            log_df = db.get_session_data(session_db_path)
            reg_df = db.get_all_registered()
            
            # Data Prep
            full_df = pd.merge(reg_df, log_df[['mac', 'count']], on='mac', how='left').fillna({'count': 0})
            
            # Calculate Categories
            full_df['Calculated_Status'] = full_df.apply(lambda r: categorize_status(r['count'], st.session_state.scan_cycles)[0], axis=1)
            
            # Apply Overrides
            def get_final_status(row):
                return st.session_state.manual_overrides.get(row['mac'], row['Calculated_Status'])
            
            full_df['Final_Status'] = full_df.apply(get_final_status, axis=1)
            
            # SORTING: Present -> Action Req -> Suspicious -> Unknown (handled later)
            # Custom Sort Order
            status_order = {"Present": 0, "Action Required": 1, "Suspicious": 2, "Absent": 3}
            full_df['Sort_Rank'] = full_df['Final_Status'].map(status_order)
            full_df = full_df.sort_values(by='Sort_Rank')
            
            # 1. DISPLAY KNOWN (Excluding Absent for now)
            active_view_df = full_df[full_df['Final_Status'] != 'Absent']
            
            st.write("### 1. Attendance Review")
            for idx, row in active_view_df.iterrows():
                mac = row['mac']
                status = row['Final_Status']
                
                with st.container():
                    c1, c2, c3, c4 = st.columns([2, 1, 2, 2])
                    c1.write(f"**{row['name']}** ({row['roll_no']})")
                    c2.write(f"{int(row['count'])} / {st.session_state.scan_cycles}")
                    
                    if status == "Present": c3.success(status)
                    elif status == "Action Required": c3.warning(status)
                    elif status == "Suspicious": c3.error(status)
                    
                    # Buttons
                    if c4.button("✅", key=f"p_{mac}"):
                        st.session_state.manual_overrides[mac] = "Present"
                        st.rerun()
                    if c4.button("❌", key=f"a_{mac}"):
                        st.session_state.manual_overrides[mac] = "Absent"
                        st.rerun()
                    st.divider()

            # 2. UNKNOWN DEVICES (With Inline Add)
            unknown_df = log_df[log_df['is_unknown'] == 1].copy()
            if not unknown_df.empty:
                st.write("### 2. Unknown Devices")
                for idx, row in unknown_df.iterrows():
                    mac = row['mac']
                    cnt = int(row['count'])
                    
                    # Container for Unknown Row
                    with st.container():
                        uc1, uc2, uc3 = st.columns([2, 3, 1])
                        uc1.write(f"**{mac}**")
                        uc1.caption(f"Seen: {cnt} times")
                        
                        # Inline Add Form
                        with uc2:
                            with st.expander("➕ Add Student", expanded=False):
                                with st.form(key=f"add_unk_{mac}"):
                                    n_in = st.text_input("Name")
                                    r_in = st.text_input("Roll (0-100)")
                                    if st.form_submit_button("Save"):
                                        if validate_roll(r_in) and n_in:
                                            suc, msg = db.register_student(mac, n_in, r_in)
                                            if suc:
                                                db.update_log_after_registration(session_db_path, mac, n_in, r_in)
                                                st.success("Added!")
                                                time.sleep(1)
                                                st.rerun()
                                            else: st.error(msg)
                                        else: st.error("Invalid Input")
                        
                        # Block Action
                        if uc3.button("🚫", key=f"blk_unk_{mac}", help="Block Device"):
                            db.block_mac(mac)
                            st.rerun()
                        st.divider()

            # 3. DROPDOWN FOR ABSENTIES
            absent_df = full_df[full_df['Final_Status'] == 'Absent']
            with st.expander(f"📉 View Absent ({len(absent_df)})"):
                for idx, row in absent_df.iterrows():
                    mac = row['mac']
                    ac1, ac2, ac3 = st.columns([3, 2, 1])
                    ac1.write(f"{row['name']} ({row['roll_no']})")
                    if ac3.button("Mark Present", key=f"mp_{mac}"):
                        st.session_state.manual_overrides[mac] = "Present"
                        st.rerun()

            # FINAL SUBMIT
            st.divider()
            if st.button("💾 Finalize & Save Report", type="primary"):
                # Compile Final Data
                final_data = []
                
                # Registered
                for _, r in full_df.iterrows():
                    final_data.append({
                        'Name': r['name'], 'Roll': r['roll_no'], 'MAC': r['mac'],
                        'Status': r['Final_Status']
                    })
                
                # Create DF
                final_df = pd.DataFrame(final_data)
                
                # Save
                db.save_final_attendance(selected_subject, final_df)
                
                # Cleanup Log
                try: 
                    if os.path.exists(session_db_path): os.remove(session_db_path)
                except: pass
                
                # Store in Session for Final View
                st.session_state.final_report_data = final_df
                st.session_state.finalized_mode = True
                st.rerun()

# ==========================================
# TAB 2: MANAGE STUDENTS (Strict Validation)
# ==========================================

if not st.session_state.finalized_mode:
    with tab2:
        st.header("Manage Students")
        
        # ADD SECTION
        with st.expander("Add New Student", expanded=True):
            with st.form("add_std"):
                c1, c2 = st.columns(2)
                mac_in = c1.text_input("MAC (XX:XX:XX:XX:XX:XX)").upper().strip()
                name_in = c2.text_input("Name")
                
                c3, c4 = st.columns(2)
                roll_in = c3.text_input("Roll No (0-100)")
                email_in = c4.text_input("Email (e.g., DE22..., CE23...)")
                
                if st.form_submit_button("Register"):
                    if not validate_mac(mac_in):
                        st.error("Invalid MAC Format!")
                    elif not validate_roll(roll_in):
                        st.error("Roll No must be 0-100.")
                    elif not name_in or not email_in:
                        st.error("Name and Email are required.")
                    else:
                        # Pass the new email variable to the database manager
                        suc, msg = db.register_student(mac_in, name_in, roll_in, email_in)
                        if suc: st.success(f"Registered {name_in}")
                        else: st.error(msg)
        
        # EDIT SECTION (Removed Seq No, added Actions)
        st.subheader("Registered List")
        if st.button("Refresh List"): st.rerun()
        
        all_students = db.get_all_registered()
        
        for idx, row in all_students.iterrows():
            mac = row['mac']
            
            with st.container():
                c1, c2, c3, c4 = st.columns([2, 1, 2, 1])
                c1.write(f"**{row['name']}**")
                c2.write(f"Roll: {row['roll_no']}")
                c3.write(f"MAC: {mac}")
                
                # Actions: Edit | Delete | Block
                with c4:
                    with st.popover("⚙️"):
                        st.write("Actions")
                        
                        # EDIT
                        with st.expander("Edit"):
                            with st.form(key=f"ed_{mac}"):
                                new_name = st.text_input("Name", row['name'])
                                new_roll = st.text_input("Roll", row['roll_no'])
                                if st.form_submit_button("Update"):
                                    if validate_roll(new_roll):
                                        db.update_student(mac, new_name, new_roll)
                                        st.rerun()
                                    else: st.error("Invalid Roll")
                        
                        # DELETE
                        if st.button("🗑️ Delete", key=f"del_{mac}"):
                            db.delete_student(mac)
                            st.rerun()

                        # BLOCK
                        if st.button("🚫 Block", key=f"bl_{mac}"):
                            db.block_mac(mac) # Moves to blocklist, removes from students
                            st.rerun()
            st.divider()

# ==========================================
# TAB 3: VIEW REGISTRY (Simple View)
# ==========================================
if not st.session_state.finalized_mode:
    with tab3:
        # User requested specific "Three vertical dots" here? 
        # I implemented the detailed list in Tab 2. 
        # This tab can just be a clean dataframe view without seq_no.
        st.header("Registry View")
        reg_df = db.get_all_registered()
        if not reg_df.empty:
            st.dataframe(reg_df[['name', 'roll_no', 'mac']], hide_index=True, use_container_width=True)
        else:
            st.info("Empty Registry")

# ==========================================
# TAB 4: BLOCKLIST (Persistent)
# ==========================================
if not st.session_state.finalized_mode:
    with tab4:
        st.header("Blocklist Management")
        
        blocked_macs = db.get_blocklist()
        
        if not blocked_macs:
            st.success("Blocklist is empty.")
        else:
            for b_mac in blocked_macs:
                c1, c2 = st.columns([4, 2])
                c1.write(f"🔒 {b_mac}")
                
                # CONFIRMATION LOGIC
                # Using session state key for specific mac confirmation
                confirm_key = f"confirm_unblock_{b_mac}"
                
                if st.session_state.get(confirm_key, False):
                    c2.warning("Are you sure?")
                    col_y, col_n = c2.columns(2)
                    if col_y.button("Yes", key=f"y_{b_mac}"):
                        db.unblock_mac(b_mac)
                        st.session_state[confirm_key] = False
                        st.rerun()
                    if col_n.button("No", key=f"n_{b_mac}"):
                        st.session_state[confirm_key] = False
                        st.rerun()
                else:
                    if c2.button("Remove", key=f"rm_{b_mac}"):
                        st.session_state[confirm_key] = True
                        st.rerun()
                st.divider()


# ==========================================
# TAB 6: ANALYTICS & REPORTS
# ==========================================
if not st.session_state.finalized_mode:
    with tab6:
        st.header("📊 Advanced Analytics & Insights")
        
        # 1. Load Data from Supabase
        df_master = db.get_all_attendance_records()
        
        if df_master.empty:
            st.info("ℹ️ No attendance records found in the database yet. Run a session and save attendance first.")
            st.stop()
            
        try:
            df_master['Date_Obj'] = pd.to_datetime(df_master['Date'])
        except Exception as e:
            st.error(f"❌ Error processing date formats: {e}")
            st.stop()

        sub_t1, sub_t2 = st.tabs(["👨‍🏫 Faculty Dashboard", "🎓 Student Portal"])

        # ==========================================
        # --- FACULTY VIEW ---
        # ==========================================
        with sub_t1:
            st.markdown("### 🎛️ Session Filters")
            c_filt1, c_filt2 = st.columns(2)
            
            # Subject Filter
            sub_list = ["All Subjects"] + list(df_master['Subject'].dropna().unique())
            sel_sub = c_filt1.selectbox("Target Subject", sub_list, label_visibility="collapsed")
            
            # Date Range Filter
            d_min, d_max = df_master['Date_Obj'].min().date(), df_master['Date_Obj'].max().date()
            sel_dates = c_filt2.date_input("Date Range", [d_min, d_max], label_visibility="collapsed")
            
            # Apply Filters
            df_filt = df_master.copy()
            if sel_sub != "All Subjects":
                df_filt = df_filt[df_filt['Subject'] == sel_sub]
            
            if isinstance(sel_dates, list) and len(sel_dates) == 2:
                df_filt = df_filt[(df_filt['Date_Obj'].dt.date >= sel_dates[0]) & (df_filt['Date_Obj'].dt.date <= sel_dates[1])]

            st.divider()

            if not df_filt.empty:
                # --- KPI METRICS ---
                total_sessions = df_filt['Date'].nunique()
                total_records = len(df_filt)
                total_present = len(df_filt[df_filt['Status'] == 'Present'])
                avg_att = round((total_present / total_records) * 100, 1) if total_records > 0 else 0
                unique_students = df_filt['MAC'].nunique()

                st.markdown("### 📈 Top-Level Metrics")
                k1, k2, k3, k4 = st.columns(4)
                k1.metric("Total Sessions Conducted", total_sessions)
                k2.metric("Unique Students Tracked", unique_students)
                k3.metric("Overall Class Health", f"{avg_att}%", delta="Target: 75%", delta_color="off" if avg_att < 75 else "normal")
                k4.metric("Total Pings Processed", total_records)

                st.write("") # Spacer

                # --- VISUALIZATIONS ---
                v_col1, v_col2 = st.columns([2, 1])

                with v_col1:
                    # Daily Trend Area Chart
                    daily_trend = df_filt.groupby('Date').apply(
                        lambda x: (x['Status'] == 'Present').sum() / len(x) * 100
                    ).reset_index(name='Attendance %')
                    
                    fig_trend = px.area(daily_trend, x='Date', y='Attendance %', 
                                        title="Daily Attendance Trend (%)", 
                                        markers=True, color_discrete_sequence=['#3a7bd5'])
                    fig_trend.update_layout(yaxis_range=[0, 105], margin=dict(l=0, r=0, t=40, b=0))
                    st.plotly_chart(fig_trend, use_container_width=True)

                with v_col2:
                    # Present vs Absent Donut Chart
                    status_counts = df_filt['Status'].value_counts().reset_index()
                    status_counts.columns = ['Status', 'Count']
                    
                    fig_pie = px.pie(status_counts, values='Count', names='Status', hole=0.6,
                                     title="Overall Distribution",
                                     color='Status', color_discrete_map={'Present': '#39d353', 'Absent': '#f85149', 'Suspicious': '#d29922'})
                    fig_pie.update_traces(textinfo='percent', hoverinfo='label+value')
                    fig_pie.update_layout(showlegend=False, margin=dict(l=0, r=0, t=40, b=0))
                    
                    # Add total center text
                    fig_pie.add_annotation(x=0.5, y=0.5, text=f"{avg_att}%", font=dict(size=30, family='Helvetica Neue', color='#00d2ff'), showarrow=False)
                    st.plotly_chart(fig_pie, use_container_width=True)

                st.divider()

                # --- AT-RISK STUDENTS ---
                st.markdown("### ⚠️ Defaulters (Below 75%)")
                student_stats = df_filt.groupby(['Roll', 'Name']).apply(
                    lambda x: pd.Series({
                        'Total Classes': len(x),
                        'Attended': (x['Status'] == 'Present').sum(),
                        'Attendance %': round((x['Status'] == 'Present').sum() / len(x) * 100, 1)
                    })
                ).reset_index()
                
                at_risk = student_stats[student_stats['Attendance %'] < 75.0].sort_values('Attendance %')
                if not at_risk.empty:
                    st.dataframe(at_risk, use_container_width=True, hide_index=True)
                else:
                    st.success("✅ Excellent! No students are currently below the 75% threshold.")
            else:
                st.info("No data available for the selected filters.")

        # ==========================================
        # --- STUDENT VIEW (GitHub Style) ---
        # ==========================================
        with sub_t2:
            st.markdown("### 🔍 Student Contribution Graph")
            st.caption("Check your attendance footprint across the semester.")
            
            c_s1, c_s2 = st.columns([1, 2])
            s_roll = c_s1.text_input("Enter Roll No", placeholder="e.g. 101")
            s_sub = c_s2.selectbox("Select Subject", df_master['Subject'].dropna().unique(), key="s_cal_sub")

            if s_roll:
                # Filter data for the specific subject
                df_sub = df_master[df_master['Subject'] == s_sub].copy()
                
                if df_sub.empty:
                    st.warning("No sessions recorded for this subject yet.")
                else:
                    # Filter data for the specific student
                    df_student = df_sub[df_sub['Roll'].astype(str) == s_roll.strip()]
                    
                    if df_student.empty:
                        st.error(f"No records found for Roll No {s_roll} in {s_sub}.")
                    else:
                        student_name = df_student['Name'].iloc[0]
                        total = len(df_sub['Date_Obj'].unique()) # Total sessions that actually happened
                        attended = len(df_student[df_student['Status'] == 'Present'])
                        perc = round((attended / total) * 100, 1) if total > 0 else 0

                        # Summary Header
                        st.markdown(f"#### {student_name}'s Record")
                        sc1, sc2, sc3 = st.columns(3)
                        sc1.metric("Attendance Score", f"{perc}%")
                        sc2.metric("Sessions Attended", f"{attended} / {total}")
                        if perc >= 75: sc3.success("Status: Secure ✅")
                        else: sc3.error("Status: At Risk ⚠️")
                        
                        st.write("") # Spacer

                        # --- BUILD GITHUB HEATMAP (HTML/CSS) ---
                        # 1. Determine Grid Range
                        start_date = df_sub['Date_Obj'].min().date()
                        end_date = df_sub['Date_Obj'].max().date()
                        
                        # Pad to start on a Monday and end on a Sunday
                        start_date = start_date - datetime.timedelta(days=start_date.weekday())
                        end_date = end_date + datetime.timedelta(days=6 - end_date.weekday())
                        
                        all_dates = pd.date_range(start_date, end_date)
                        session_dates = set(df_sub['Date_Obj'].dt.date)
                        student_status = dict(zip(df_student['Date_Obj'].dt.date, df_student['Status']))

                        # 2. Inject CSS
                        css = """
                        <style>
                        .gh-wrapper { display: flex; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }
                        .gh-days { display: grid; grid-template-rows: repeat(7, 15px); gap: 4px; margin-right: 8px; font-size: 10px; color: #7d8590; text-align: right; line-height: 15px;}
                        .gh-grid { display: grid; grid-template-rows: repeat(7, 15px); grid-auto-flow: column; gap: 4px; overflow-x: auto; padding-bottom: 10px;}
                        .gh-cell { width: 15px; height: 15px; border-radius: 3px; cursor: crosshair; transition: transform 0.1s;}
                        .gh-cell:hover { transform: scale(1.3); outline: 1px solid #000;}
                        .bg-empty { background-color: #2e3036; opacity: 0.1; } /* Dates outside range */
                        .bg-gray { background-color: #ebedf0; } /* No session */
                        .bg-green { background-color: #39d353; } /* Present */
                        .bg-red { background-color: #f85149; } /* Absent */
                        
                        /* Dark mode adjustments */
                        @media (prefers-color-scheme: dark) {
                            .bg-gray { background-color: #161b22; }
                            .bg-empty { opacity: 0; }
                        }
                        </style>
                        """

                        # 3. Generate Grid Cells
                        cells_html = ""
                        for d in all_dates:
                            date_val = d.date()
                            
                            # Case 1: Date is outside actual class timeline
                            if date_val < df_sub['Date_Obj'].min().date() or date_val > df_sub['Date_Obj'].max().date():
                                color_cls = "bg-empty"
                                title = ""
                            # Case 2: A session happened
                            elif date_val in session_dates:
                                stat = student_status.get(date_val, "Absent")
                                color_cls = "bg-green" if stat == "Present" else "bg-red"
                                title = f"{date_val.strftime('%b %d, %Y')} - {stat}"
                            # Case 3: Inside timeline, but no session that day
                            else:
                                color_cls = "bg-gray"
                                title = f"{date_val.strftime('%b %d, %Y')} - No Session"

                            cells_html += f'<div class="gh-cell {color_cls}" title="{title}"></div>'

                        # 4. Assemble HTML
                        html = f"""
                        {css}
                        <div class="gh-wrapper">
                            <div class="gh-days">
                                <div>Mon</div><div></div><div>Wed</div><div></div><div>Fri</div><div></div><div></div>
                            </div>
                            <div class="gh-grid">
                                {cells_html}
                            </div>
                        </div>
                        <div style="font-size: 11px; color: #7d8590; margin-top: 10px; display: flex; align-items: center; gap: 5px;">
                            <span>Less</span>
                            <div class="gh-cell bg-gray"></div>
                            <div class="gh-cell bg-red"></div>
                            <div class="gh-cell bg-green"></div>
                            <span>More</span>
                        </div>
                        """
                        
                        st.markdown(html, unsafe_allow_html=True)
                        st.divider()
                        
                        # Detailed History Log
                        with st.expander("Show Detailed History"):
                            st.dataframe(df_student[['Date', 'Time', 'Status']].sort_values('Date', ascending=False), use_container_width=True, hide_index=True)