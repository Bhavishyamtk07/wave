import pandas as pd
import datetime
import os
import streamlit as st
from supabase import create_client, Client

# --- SUPABASE CONNECTION ---
@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase: Client = init_connection()

# We no longer need init_master_db() as tables are managed in the Supabase cloud

# --- STUDENT MANAGEMENT ---
def register_student(mac, name, roll_no, email):
    try:
        # Insert directly into the Supabase 'students' table
        data, count = supabase.table('students').insert({
            "mac": mac,
            "name": name,
            "roll_no": roll_no,
            "email": email
        }).execute()
        return True, "Success"
    except Exception as e:
        err_msg = str(e)
        # Supabase will throw an error if the MAC, Roll, or Email violates a UNIQUE constraint
        if "duplicate key value" in err_msg.lower():
            return False, "MAC, Roll No, or Email is already registered!"
        return False, f"Database Error: {err_msg}"

# --- CONTINUATION OF STUDENT MANAGEMENT ---
def update_student(mac, name, roll_no):
    try:
        supabase.table('students').update({"name": name, "roll_no": roll_no}).eq("mac", mac).execute()
    except Exception as e: pass

def delete_student(mac):
    try:
        supabase.table('students').delete().eq("mac", mac).execute()
    except Exception as e: pass

def get_all_registered():
    try:
        response = supabase.table('students').select("*").execute()
        df = pd.DataFrame(response.data)
        if df.empty:
            return df
        
        # Safely sort the dataframe without crashing if roll_no contains text
        df['roll_no'] = df['roll_no'].astype(str)
        df = df.sort_values('roll_no')
        return df
    except Exception as e:
        st.error(f"🚨 Student Fetch Error: {e}")
        return pd.DataFrame(columns=['mac', 'name', 'roll_no', 'email'])


# --- BLOCKLIST FUNCTIONS ---
def get_blocklist():
    try:
        response = supabase.table('blocklist').select("mac").execute()
        return [row['mac'] for row in response.data] if response.data else []
    except: return []

def block_mac(mac):
    try:
        supabase.table('blocklist').insert({"mac": mac}).execute()
        # Also remove from students if they are there
        supabase.table('students').delete().eq("mac", mac).execute()
    except: pass

def unblock_mac(mac):
    try:
        supabase.table('blocklist').delete().eq("mac", mac).execute()
    except: pass


# --- FACULTY MANAGEMENT ---
def get_all_faculty():
    try:
        response = supabase.table('faculty_info').select("*").execute()
        return pd.DataFrame(response.data) if response.data else pd.DataFrame(columns=['subject', 'faculty_name'])
    except: return pd.DataFrame(columns=['subject', 'faculty_name'])

def add_faculty_subject(subject, faculty):
    try:
        supabase.table('faculty_info').insert({"subject": subject, "faculty_name": faculty}).execute()
        return True, "Added"
    except Exception as e: 
        return False, str(e)

def remove_faculty_subject(subject):
    try:
        supabase.table('faculty_info').delete().eq("subject", subject).execute()
    except: pass

def get_faculty_subjects_list():
    try:
        response = supabase.table('faculty_info').select("subject", "faculty_name").execute()
        if response.data:
            return [f"{row['subject']} - {row['faculty_name']}" for row in response.data]
        return []
    except: return []



    # --- SESSION LOGIC ---
def get_session_db_name(subject):
    # We no longer create local .db files. 
    # We just return the subject name to act as our session identifier in Supabase.
    return subject

def init_session_db(session_id):
    # The table is already created in Supabase, so we pass.
    pass

def reset_session_table(session_id):
    try:
        supabase.table('live_sessions').delete().eq("subject", session_id).execute()
    except: pass

def update_log_after_registration(session_id, mac, name, roll_no):
    try:
        supabase.table('live_sessions').update({
            "name": name, 
            "roll_no": roll_no, 
            "is_unknown": 0
        }).eq("mac", mac).eq("subject", session_id).execute()
    except: pass

def update_session_log(session_id, active_devices):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    registered_df = get_all_registered()
    known_macs = registered_df.set_index('mac').to_dict('index') if not registered_df.empty else {}
    
    # Get current session state from Supabase
    try:
        response = supabase.table('live_sessions').select("*").eq("subject", session_id).execute()
        current_logs = {row['mac']: row for row in response.data} if response.data else {}
    except:
        current_logs = {}

    for device in active_devices:
        mac = device['mac']
        
        if mac in current_logs:
            # Update existing device in session
            new_count = current_logs[mac]['count'] + 1
            name = known_macs[mac]['name'] if mac in known_macs else current_logs[mac]['name']
            roll = known_macs[mac]['roll_no'] if mac in known_macs else current_logs[mac]['roll_no']
            is_unk = 0 if mac in known_macs else 1
            
            try:
                supabase.table('live_sessions').update({
                    "count": new_count, "last_seen": timestamp,
                    "name": name, "roll_no": roll, "is_unknown": is_unk
                }).eq("mac", mac).eq("subject", session_id).execute()
            except: pass
        else:
            # Insert new device into session
            if mac in known_macs:
                name, roll, is_unk = known_macs[mac]['name'], known_macs[mac]['roll_no'], 0
            else:
                name, roll, is_unk = "Unknown", "N/A", 1
            
            try:
                supabase.table('live_sessions').insert({
                    "mac": mac, "subject": session_id,
                    "name": name, "roll_no": roll,
                    "first_seen": timestamp, "last_seen": timestamp,
                    "count": 1, "is_unknown": is_unk
                }).execute()
            except: pass

def get_session_data(session_id):
    try:
        response = supabase.table('live_sessions').select("*").eq("subject", session_id).execute()
        if response.data:
            return pd.DataFrame(response.data)
        return pd.DataFrame(columns=['mac', 'name', 'roll_no', 'count', 'is_unknown'])
    except: 
        return pd.DataFrame(columns=['mac', 'name', 'roll_no', 'count', 'is_unknown'])


# --- FINAL SAVE ---
def save_final_attendance(subject, attendance_df):
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    time_str = datetime.datetime.now().strftime("%H:%M:%S")
    
    records = []
    for _, row in attendance_df.iterrows():
        records.append({
            "date": date_str,
            "time": time_str,
            "subject": subject,
            "name": row.get('Name', ''),
            "roll_no": str(row.get('Roll', '')),
            "mac": row.get('MAC', ''),
            "status": row.get('Status', '')
        })
        
    try:
        if records:
            supabase.table('final_attendance').insert(records).execute()
    except Exception as e:
        st.error(f"🚨 Save Attendance Error: {e}")

# --- FETCH ANALYTICS DATA ---
def get_all_attendance_records():
    try:
        response = supabase.table('final_attendance').select("*").execute()
        if response.data:
            df = pd.DataFrame(response.data)
            df.rename(columns={
                'date': 'Date', 'time': 'Time', 'subject': 'Subject',
                'name': 'Name', 'roll_no': 'Roll', 'mac': 'MAC', 'status': 'Status'
            }, inplace=True)
            return df
        return pd.DataFrame()
    except Exception as e:
        st.error(f"🚨 Analytics Fetch Error: {e}")
        return pd.DataFrame()