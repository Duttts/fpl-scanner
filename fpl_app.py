import streamlit as st
import pandas as pd
import requests

# ==========================================
# 1. SETUP & CONFIGURATION (Streamlit UI)
# ==========================================
st.set_page_config(page_title="FPL Predictive Scanner", layout="wide")

st.sidebar.title("FPL AI Manager Hub")
st.sidebar.markdown("---")

# Existing or new Manager ID input
manager_id = st.sidebar.text_input("Enter your FPL Manager ID:", value="")

st.sidebar.markdown("---")
st.sidebar.subheader("📅 Fixture Horizon Settings")
gw_horizon = st.sidebar.slider(
    "Lookahead Gameweeks", 
    min_value=1, 
    max_value=5, 
    value=1, 
    step=1,
    help="Select how many upcoming gameweeks to average opponent attacking threat over."
)

# ==========================================
# 2. API FETCHING & DATA LOADERS
# ==========================================
@st.cache_data(ttl=3600)
def fetch_fpl_bootstrap():
    url = "https://fantasy.premierleague.com/api/bootstrap-static/"
    r = requests.get(url)
    return r.json() if r.status_code == 200 else {}

@st.cache_data(ttl=3600)
def fetch_fpl_fixtures():
    url = "https://fantasy.premierleague.com/api/fixtures/"
    r = requests.get(url)
    return r.json() if r.status_code == 200 else []

@st.cache_data(ttl=3600)
def fetch_user_team(manager_id):
    headers = {"User-Agent": "Mozilla/5.0"}
    
    # Auto-detect current/next active gameweek from bootstrap data
    raw_data = fetch_fpl_bootstrap()
    current_gw = 1
    try:
        events = raw_data.get("events", [])
        for ev in events:
            if ev.get("is_current") or ev.get("is_next"):
                current_gw = ev.get("id")
                if ev.get("is_current"):
                    break 
    except Exception:
        pass

    url = f"https://fantasy.premierleague.com/api/entry/{manager_id}/event/{current_gw}/picks/"
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            picks_data = r.json().get("picks", [])
            if picks_data:
                return [p["element"] for p in picks_data]
                
        # Fallback to GW 1 if current fails
        if current_gw > 1:
            url_gw1 = f"https://fantasy.premierleague.com/api/entry/{manager_id}/event/1/picks/"
            r1 = requests.get(url_gw1, headers=headers, timeout=15)
            if r1.status_code == 200:
                picks_data1 = r1.json().get("picks", [])
                if picks_data1:
                    return [p["element"] for p in picks_data1]
    except Exception:
        pass

    return []

# ==========================================
# 3. SAFE MULTI-WEEK HORIZON FUNCTION (NEW)
# ==========================================
@st.cache_data
def get_safe_horizon_stats(team_id, fixtures_data, teams_data, target_gws=3):
    """
    Safely calculates opponent stats over a specific number of upcoming FPL gameweeks,
    handling blank gameweeks (0 fixtures) and double gameweeks (2+ fixtures) cleanly.
    """
    current_active_gw = 1
    try:
        current_active_gw = next(
            (f["event"] for f in fixtures_data if not f.get("finished") and f.get("event") is not None), 
            1
        )
    except Exception:
        pass

    end_gw = current_active_gw + target_gws - 1
    total_threat = 0.0
    fixture_count = 0
    opponent_display_list = []

    # Loop through each FPL gameweek in the chosen window range
    for gw in range(current_active_gw, end_gw + 1):
        gw_fixtures = [
            f for f in fixtures_data 
            if f.get("event") == gw and (f["team_h"] == team_id or f["team_a"] == team_id)
        ]
        
        # Handle Blank Gameweek safely
        if not gw_fixtures:
            opponent_display_list.append(f"GW{gw}: [Blank]")
            continue
            
        # Handle Normal or Double Gameweek
        for fix in gw_fixtures:
            is_home = fix["team_h"] == team_id
            opp_id = fix["team_a"] if is_home else fix["team_h"]
            
            opp_name = next((t["name"] for t in teams_data if t["id"] == opp_id), "Unknown")
            venue = "(H)" if is_home else "(A)"
            
            opponent_display_list.append(f"{opp_name} {venue}")
            
            # If tracking team-level threat scores, factor them in here:
            # opp_threat = team_attacking_threat_dict.get(opp_id, 1.0)
            # total_threat += opp_threat
            fixture_count += 1

    avg_threat = (total_threat / fixture_count) if fixture_count > 0 else 0.0

    return {
        "avg_threat": avg_threat,
        "fixtures_summary": ", ".join(opponent_display_list)
    }

# ==========================================
# 4. MAIN DASHBOARD EXECUTION
# ==========================================
bootstrap_data = fetch_fpl_bootstrap()
fixtures = fetch_fpl_fixtures()

if bootstrap_data and fixtures:
    teams_bootstrap = bootstrap_data.get("teams", [])
    players_bootstrap = bootstrap_data.get("elements", [])
    
    st.title("⚽ FPL Squad Auditor & Horizon Predictor")
    
    if manager_id:
        try:
            user_team_ids = fetch_user_team(int(manager_id))
            if user_team_ids:
                st.success(f"Successfully loaded team for Manager ID: {manager_id}!")
                
                # Filter players matching user squad
                squad_players = [p for p in players_bootstrap if p["id"] in user_team_ids]
                
                processed_rows = []
                for player in squad_players:
                    # Fetch multi-week horizon data using the slider variable (gw_horizon)
                    horizon_data = get_safe_horizon_stats(
                        team_id=player["team"],
                        fixtures_data=fixtures,
                        teams_data=teams_bootstrap,
                        target_gws=gw_horizon
                    )
                    
                    # Map team name safely
                    team_name = next((t["name"] for t in teams_bootstrap if t["id"] == player["team"]), "Unknown")
                    
                    processed_rows.append({
                        "Player": player["web_name"],
                        "Team": team_name,
                        "Position Code": player["element_type"],
                        "Upcoming Fixtures": horizon_data["fixtures_summary"],
                        "Opponent Threat Score": horizon_data["avg_threat"],
                        "Total Points": player["total_points"]
                    })
                
                df_squad = pd.DataFrame(processed_rows)
                st.dataframe(df_squad, use_container_width=True)
                
            else:
                st.warning("Could not fetch team picks. Ensure your Manager ID is correct and GW1 has concluded.")
        except ValueError:
            st.error("Please enter a valid numeric Manager ID.")
    else:
        st.info("👈 Enter your FPL Manager ID in the sidebar to run your squad audit.")
else:
    st.error("Failed to connect to the FPL API. Please check your network connection.")
