import streamlit as st
import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import json
from datetime import datetime
import urllib.parse

# Page config
st.set_page_config(
    page_title="Warehouse System",
    page_icon="📦",
    layout="wide"
)

# Sheet IDs
HANDOVER_SHEET_ID = "1aUfprh_6DwhwVRVKk2PUj_OpeAtz0U_42i5ERTqJfB4"
BUNDLING_SHEET_ID = "1pePWTFWezLEsRQylyHiWhvYh6gpxoEx1DaXfjWXsKEs"
HANDOVER_TAB = "Inbound Dump"
BUNDLING_TAB = "Albash working-2"

# OAuth Scopes
SCOPES = [
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/spreadsheets'
]

def get_oauth_config():
    """Get OAuth configuration from Streamlit secrets"""
    return {
        "web": {
            "client_id": st.secrets["GOOGLE_CLIENT_ID"],
            "client_secret": st.secrets["GOOGLE_CLIENT_SECRET"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [st.secrets["REDIRECT_URI"]]
        }
    }

def get_authorization_url():
    """Generate Google OAuth authorization URL"""
    flow = Flow.from_client_config(
        get_oauth_config(),
        scopes=SCOPES,
        redirect_uri=st.secrets["REDIRECT_URI"]
    )
    auth_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )
    return auth_url, state

def handle_oauth_callback(auth_code, state):
    """Handle OAuth callback and get credentials"""
    try:
        flow = Flow.from_client_config(
            get_oauth_config(),
            scopes=SCOPES,
            redirect_uri=st.secrets["REDIRECT_URI"],
            state=state
        )
        flow.fetch_token(code=auth_code)
        credentials = flow.credentials
        
        # Get user info
        user_info_service = build('oauth2', 'v2', credentials=credentials)
        user_info = user_info_service.userinfo().get().execute()
        
        return credentials, user_info
    except Exception as e:
        st.error(f"Authentication error: {str(e)}")
        return None, None

def get_sheets_service(credentials):
    """Create Sheets API service with user credentials"""
    creds = Credentials(
        token=credentials['token'],
        refresh_token=credentials.get('refresh_token'),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=st.secrets["GOOGLE_CLIENT_ID"],
        client_secret=st.secrets["GOOGLE_CLIENT_SECRET"],
        scopes=SCOPES
    )
    return build('sheets', 'v4', credentials=creds)

def search_handover(service, search_term):
    """Search in Handover sheet"""
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=HANDOVER_SHEET_ID,
            range=f"'{HANDOVER_TAB}'!A3:Z1000"
        ).execute()
        
        values = result.get('values', [])
        if not values:
            return None, None, []
        
        headers = values[0]
        data_rows = values[1:]
        
        # Find matching rows
        matches = []
        for idx, row in enumerate(data_rows):
            row_extended = row + [''] * (len(headers) - len(row))
            for cell in row_extended:
                if search_term.lower() in str(cell).lower():
                    matches.append({
                        'row_index': idx + 4,  # +4 because headers at row 3, data starts row 4
                        'data': dict(zip(headers, row_extended))
                    })
                    break
        
        return headers, data_rows, matches
    except HttpError as e:
        if e.resp.status == 403:
            st.error("❌ Aapko is sheet ka access nahi hai. Sheet owner se permission lein.")
        else:
            st.error(f"Error: {str(e)}")
        return None, None, []

def search_bundling(service, search_term):
    """Search in Bundling sheet"""
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=BUNDLING_SHEET_ID,
            range=f"'{BUNDLING_TAB}'!A1:Z1000"
        ).execute()
        
        values = result.get('values', [])
        if not values:
            return None, None, []
        
        headers = values[0]
        data_rows = values[1:]
        
        # Find matching rows
        matches = []
        for idx, row in enumerate(data_rows):
            row_extended = row + [''] * (len(headers) - len(row))
            for cell in row_extended:
                if search_term.lower() in str(cell).lower():
                    matches.append({
                        'row_index': idx + 2,  # +2 because headers at row 1, data starts row 2
                        'data': dict(zip(headers, row_extended))
                    })
                    break
        
        return headers, data_rows, matches
    except HttpError as e:
        if e.resp.status == 403:
            st.error("❌ Aapko is sheet ka access nahi hai. Sheet owner se permission lein.")
        else:
            st.error(f"Error: {str(e)}")
        return None, None, []

def mark_handover(service, row_index, user_name):
    """Mark order as handed over with note"""
    try:
        # Get sheet ID for notes
        spreadsheet = service.spreadsheets().get(spreadsheetId=HANDOVER_SHEET_ID).execute()
        sheet_id = None
        for sheet in spreadsheet['sheets']:
            if sheet['properties']['title'] == HANDOVER_TAB:
                sheet_id = sheet['properties']['sheetId']
                break
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        note_text = f"Handed over by {user_name} on {timestamp}"
        
        # Update Handedover Status column (find column index)
        result = service.spreadsheets().values().get(
            spreadsheetId=HANDOVER_SHEET_ID,
            range=f"'{HANDOVER_TAB}'!A3:Z3"
        ).execute()
        headers = result.get('values', [[]])[0]
        
        handover_col_idx = None
        for idx, header in enumerate(headers):
            if 'handedover' in header.lower() or 'handed' in header.lower():
                handover_col_idx = idx
                break
        
        if handover_col_idx is None:
            st.error("Handedover Status column not found")
            return False
        
        # Convert to column letter
        col_letter = chr(65 + handover_col_idx) if handover_col_idx < 26 else chr(64 + handover_col_idx // 26) + chr(65 + handover_col_idx % 26)
        
        # Update cell value
        service.spreadsheets().values().update(
            spreadsheetId=HANDOVER_SHEET_ID,
            range=f"'{HANDOVER_TAB}'!{col_letter}{row_index}",
            valueInputOption='USER_ENTERED',
            body={'values': [['Done']]}
        ).execute()
        
        # Add note to cell
        if sheet_id is not None:
            requests = [{
                'updateCells': {
                    'range': {
                        'sheetId': sheet_id,
                        'startRowIndex': row_index - 1,
                        'endRowIndex': row_index,
                        'startColumnIndex': handover_col_idx,
                        'endColumnIndex': handover_col_idx + 1
                    },
                    'rows': [{
                        'values': [{
                            'note': note_text
                        }]
                    }],
                    'fields': 'note'
                }
            }]
            service.spreadsheets().batchUpdate(
                spreadsheetId=HANDOVER_SHEET_ID,
                body={'requests': requests}
            ).execute()
        
        return True
    except Exception as e:
        st.error(f"Error marking handover: {str(e)}")
        return False

def mark_bundling_status(service, row_index, status, user_name):
    """Mark bundling order status"""
    try:
        # Get sheet ID
        spreadsheet = service.spreadsheets().get(spreadsheetId=BUNDLING_SHEET_ID).execute()
        sheet_id = None
        for sheet in spreadsheet['sheets']:
            if sheet['properties']['title'] == BUNDLING_TAB:
                sheet_id = sheet['properties']['sheetId']
                break
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        note_text = f"Marked '{status}' by {user_name} on {timestamp}"
        
        # Get headers to find Packing Status column
        result = service.spreadsheets().values().get(
            spreadsheetId=BUNDLING_SHEET_ID,
            range=f"'{BUNDLING_TAB}'!A1:Z1"
        ).execute()
        headers = result.get('values', [[]])[0]
        
        packing_col_idx = None
        for idx, header in enumerate(headers):
            if 'packing' in header.lower() and 'status' in header.lower():
                packing_col_idx = idx
                break
        
        if packing_col_idx is None:
            st.error("Packing Status column not found")
            return False
        
        col_letter = chr(65 + packing_col_idx) if packing_col_idx < 26 else chr(64 + packing_col_idx // 26) + chr(65 + packing_col_idx % 26)
        
        # Update cell value
        service.spreadsheets().values().update(
            spreadsheetId=BUNDLING_SHEET_ID,
            range=f"'{BUNDLING_TAB}'!{col_letter}{row_index}",
            valueInputOption='USER_ENTERED',
            body={'values': [[status]]}
        ).execute()
        
        # Add note
        if sheet_id is not None:
            requests = [{
                'updateCells': {
                    'range': {
                        'sheetId': sheet_id,
                        'startRowIndex': row_index - 1,
                        'endRowIndex': row_index,
                        'startColumnIndex': packing_col_idx,
                        'endColumnIndex': packing_col_idx + 1
                    },
                    'rows': [{
                        'values': [{
                            'note': note_text
                        }]
                    }],
                    'fields': 'note'
                }
            }]
            service.spreadsheets().batchUpdate(
                spreadsheetId=BUNDLING_SHEET_ID,
                body={'requests': requests}
            ).execute()
        
        return True
    except Exception as e:
        st.error(f"Error marking bundling status: {str(e)}")
        return False

def get_pending_handover(service):
    """Get pending handover orders"""
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=HANDOVER_SHEET_ID,
            range=f"'{HANDOVER_TAB}'!A3:Z1000"
        ).execute()
        
        values = result.get('values', [])
        if not values:
            return []
        
        headers = values[0]
        data_rows = values[1:]
        
        # Find handover status column
        handover_col_idx = None
        for idx, header in enumerate(headers):
            if 'handedover' in header.lower() or 'handed' in header.lower():
                handover_col_idx = idx
                break
        
        if handover_col_idx is None:
            return []
        
        # Find pending orders
        pending = []
        for idx, row in enumerate(data_rows):
            row_extended = row + [''] * (len(headers) - len(row))
            status = row_extended[handover_col_idx] if handover_col_idx < len(row_extended) else ''
            if status.lower() not in ['done', 'completed', 'yes']:
                pending.append({
                    'row_index': idx + 4,
                    'data': dict(zip(headers, row_extended))
                })
        
        return pending[:50]  # Return max 50
    except Exception as e:
        st.error(f"Error getting pending list: {str(e)}")
        return []

# ============== MAIN APP ==============

def main():
    st.title("📦 Warehouse System")
    st.caption("Handover & Bundling Management")
    
    # Check for OAuth callback
    query_params = st.query_params
    
    # Handle OAuth callback
    if 'code' in query_params and 'credentials' not in st.session_state:
        auth_code = query_params.get('code')
        state = query_params.get('state', st.session_state.get('oauth_state'))
        
        with st.spinner("Logging in..."):
            credentials, user_info = handle_oauth_callback(auth_code, state)
            
            if credentials and user_info:
                st.session_state['credentials'] = {
                    'token': credentials.token,
                    'refresh_token': credentials.refresh_token,
                    'token_uri': credentials.token_uri,
                    'client_id': credentials.client_id,
                    'client_secret': credentials.client_secret,
                }
                st.session_state['user_info'] = user_info
                st.query_params.clear()
                st.rerun()
    
    # Check if logged in
    if 'credentials' not in st.session_state:
        st.markdown("---")
        st.markdown("### 🔐 Login Required")
        st.info("Please login with your Google account to access the warehouse system.")
        
        if st.button("🔑 Login with Google", type="primary", use_container_width=True):
            auth_url, state = get_authorization_url()
            st.session_state['oauth_state'] = state
            st.markdown(f'<meta http-equiv="refresh" content="0;url={auth_url}">', unsafe_allow_html=True)
        
        st.markdown("---")
        st.markdown("##### ℹ️ Note")
        st.markdown("- You need access to the warehouse sheets to use this app")
        st.markdown("- Your Google account email will be recorded for handover tracking")
        return
    
    # User is logged in
    user_info = st.session_state['user_info']
    user_name = user_info.get('name', user_info.get('email', 'Unknown'))
    user_email = user_info.get('email', '')
    
    # Sidebar
    with st.sidebar:
        st.markdown(f"### 👤 {user_name}")
        st.caption(user_email)
        if st.button("🚪 Logout", use_container_width=True):
            del st.session_state['credentials']
            del st.session_state['user_info']
            st.rerun()
        st.markdown("---")
    
    # Get sheets service
    try:
        service = get_sheets_service(st.session_state['credentials'])
    except Exception as e:
        st.error(f"Error connecting to Google Sheets: {str(e)}")
        if st.button("🔄 Re-login"):
            del st.session_state['credentials']
            del st.session_state['user_info']
            st.rerun()
        return
    
    # Main tabs
    tab1, tab2, tab3 = st.tabs(["🔍 Search & Handover", "📦 Bundling", "📋 Pending List"])
    
    # TAB 1: Search & Handover
    with tab1:
        st.markdown("### Search Order")
        search_col1, search_col2 = st.columns([3, 1])
        with search_col1:
            search_term = st.text_input("Enter Order No, Vendor, or any keyword", key="handover_search")
        with search_col2:
            st.markdown("<br>", unsafe_allow_html=True)
            search_btn = st.button("🔍 Search", key="handover_search_btn", use_container_width=True)
        
        if search_btn and search_term:
            with st.spinner("Searching..."):
                headers, data, matches = search_handover(service, search_term)
                
                if matches:
                    st.success(f"✅ Found {len(matches)} result(s)")
                    
                    for match in matches:
                        with st.expander(f"📄 Row {match['row_index']} - {match['data'].get('Order No', match['data'].get('order no', 'N/A'))}", expanded=True):
                            col1, col2 = st.columns(2)
                            
                            data_items = list(match['data'].items())
                            mid = len(data_items) // 2
                            
                            with col1:
                                for key, value in data_items[:mid]:
                                    st.markdown(f"**{key}:** {value}")
                            with col2:
                                for key, value in data_items[mid:]:
                                    st.markdown(f"**{key}:** {value}")
                            
                            st.markdown("---")
                            if st.button(f"✅ Mark Handover", key=f"handover_{match['row_index']}", type="primary"):
                                if mark_handover(service, match['row_index'], user_name):
                                    st.success(f"✅ Marked as handed over by {user_name}")
                                    st.balloons()
                else:
                    st.warning("❌ No results found")
    
    # TAB 2: Bundling
    with tab2:
        st.markdown("### Search Bundling Order")
        bcol1, bcol2 = st.columns([3, 1])
        with bcol1:
            bundling_search = st.text_input("Enter Order ID, Bundle ID, or Customer", key="bundling_search")
        with bcol2:
            st.markdown("<br>", unsafe_allow_html=True)
            bundling_btn = st.button("🔍 Search", key="bundling_search_btn", use_container_width=True)
        
        if bundling_btn and bundling_search:
            with st.spinner("Searching..."):
                headers, data, matches = search_bundling(service, bundling_search)
                
                if matches:
                    st.success(f"✅ Found {len(matches)} result(s)")
                    
                    for match in matches:
                        with st.expander(f"📦 Row {match['row_index']} - {match['data'].get('Fleek/Order ID', match['data'].get('Bundle ID', 'N/A'))}", expanded=True):
                            col1, col2 = st.columns(2)
                            
                            data_items = list(match['data'].items())
                            mid = len(data_items) // 2
                            
                            with col1:
                                for key, value in data_items[:mid]:
                                    st.markdown(f"**{key}:** {value}")
                            with col2:
                                for key, value in data_items[mid:]:
                                    st.markdown(f"**{key}:** {value}")
                            
                            st.markdown("---")
                            status_col1, status_col2, status_col3 = st.columns(3)
                            with status_col1:
                                if st.button("✅ Packed", key=f"packed_{match['row_index']}"):
                                    if mark_bundling_status(service, match['row_index'], "Packed", user_name):
                                        st.success("Marked as Packed!")
                            with status_col2:
                                if st.button("⏸️ Hold", key=f"hold_{match['row_index']}"):
                                    if mark_bundling_status(service, match['row_index'], "Hold", user_name):
                                        st.success("Marked as Hold!")
                            with status_col3:
                                if st.button("❌ Issue", key=f"issue_{match['row_index']}"):
                                    if mark_bundling_status(service, match['row_index'], "Issue", user_name):
                                        st.success("Marked as Issue!")
                else:
                    st.warning("❌ No results found")
    
    # TAB 3: Pending List
    with tab3:
        st.markdown("### Pending Handover Orders")
        if st.button("🔄 Refresh List", key="refresh_pending"):
            st.session_state['pending_refreshed'] = True
        
        with st.spinner("Loading pending orders..."):
            pending = get_pending_handover(service)
            
            if pending:
                st.info(f"📋 Showing {len(pending)} pending orders")
                
                for item in pending:
                    order_no = item['data'].get('Order No', item['data'].get('order no', 'N/A'))
                    vendor = item['data'].get('Vendor', item['data'].get('vendor', 'N/A'))
                    
                    col1, col2, col3 = st.columns([2, 2, 1])
                    with col1:
                        st.markdown(f"**{order_no}**")
                    with col2:
                        st.markdown(f"{vendor}")
                    with col3:
                        if st.button("✅", key=f"pending_{item['row_index']}", help="Mark Handover"):
                            if mark_handover(service, item['row_index'], user_name):
                                st.success("Done!")
                                st.rerun()
                    st.markdown("---")
            else:
                st.success("🎉 No pending orders!")

if __name__ == "__main__":
    main()
