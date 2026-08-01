import pandas as pd
import requests
import streamlit as st

# Set page layout to wide for your laptop workspace
st.set_page_config(
    page_title="Custom FPL Dashboard", page_icon="⚽", layout="wide"
)

st.title("⚽ Advanced FPL Strategy Dashboard")
st.write(
    "Welcome to your custom laptop command center. Fully loaded with position,"
    " price, fixtures, minutes played (total & per 90), ICT metrics, xGI,"
    " defensive contributions, form, bonus points, BPS, rolling windows, and"
    " fully custom presets."
)


@st.cache_data(ttl=3600)
def load_fpl_data():
  url = "https://fantasy.premierleague.com/api/bootstrap-static/"
  response = requests.get(url)
  data = response.json()

  players_df = pd.DataFrame(data["elements"])
  teams_df = pd.DataFrame(data["teams"])
  positions_df = pd.DataFrame(data["element_types"])

  team_mapping = teams_df.set_index("id")["name"].to_dict()
  position_mapping = positions_df.set_index("id")["singular_name"].to_dict()

  players_df["team_name"] = players_df["team"].map(team_mapping)
  players_df["position"] = players_df["element_type"].map(position_mapping)

  # Convert columns cleanly and safely
  players_df["now_cost"] = players_df["now_cost"] / 10.0
  numeric_cols = [
      "selected_by_percent",
      "total_points",
      "influence",
      "creativity",
      "threat",
      "expected_goals",
      "expected_assists",
      "form",
      "minutes",
      "bps",
      "bonus",
      "clean_sheets",
      "goals_conceded",
  ]
  for col in numeric_cols:
    if col in players_df.columns:
      players_df[col] = pd.to_numeric(players_df[col], errors="coerce").fillna(
          0.0
      )
    else:
      players_df[col] = 0.0

  # Calculate Expected Goal Involvements (xGI)
  players_df["expected_goal_involvements"] = (
      players_df["expected_goals"] + players_df["expected_assists"]
  )

  # Calculate Per 90 metrics (preventing division by zero)
  players_df["minutes"] = players_df["minutes"].replace(0, 1)  # safe guard
  players_df["influence_per_90"] = (
      players_df["influence"] / players_df["minutes"]
  ) * 90
  players_df["threat_per_90"] = (
      players_df["threat"] / players_df["minutes"]
  ) * 90
  players_df["creativity_per_90"] = (
      players_df["creativity"] / players_df["minutes"]
  ) * 90
  players_df["xgi_per_90"] = (
      players_df["expected_goal_involvements"] / players_df["minutes"]
  ) * 90

  return players_df, data["events"], teams_df


# Load the main dataset, events info, and teams
try:
  df, events_data, teams_df = load_fpl_data()
except Exception as e:
  st.error(f"Error connecting to FPL API: {e}")
  st.stop()


# Fetch upcoming fixtures to display fixture difficulty / next opponents
@st.cache_data(ttl=3600)
def load_fixtures_data():
  try:
    r = requests.get("https://fantasy.premierleague.com/api/fixtures/")
    if r.status_code == 200:
      fixtures_df = pd.DataFrame(r.json())
      return fixtures_df
  except:
    pass
  return pd.DataFrame()


fixtures_df = load_fixtures_data()


# Helper function to fetch rolling last-X-games data once GW5+ is live
@st.cache_data(ttl=3600)
def fetch_rolling_data(player_ids, num_games=5):
  rolling_records = []
  for pid in player_ids:
    try:
      r = requests.get(
          f"https://fantasy.premierleague.com/api/element-summary/{pid}/"
      )
      if r.status_code == 200:
        history = r.json().get("history", [])
        if history:
          recent_games = history[-num_games:]
          sum_mins = sum(
              int(g.get("minutes", 0) or 0) for g in recent_games
          )
          sum_xg = sum(
              float(g.get("expected_goals", 0) or 0) for g in recent_games
          )
          sum_xa = sum(
              float(g.get("expected_assists", 0) or 0) for g in recent_games
          )
          sum_inf = sum(
              float(g.get("influence", 0) or 0) for g in recent_games
          )
          sum_creat = sum(
              float(g.get("creativity", 0) or 0) for g in recent_games
          )
          sum_threat = sum(
              float(g.get("threat", 0) or 0) for g in recent_games
          )
          sum_pts = sum(int(g.get("total_points", 0) or 0) for g in recent_games)
          sum_cs = sum(
              int(g.get("clean_sheets", 0) or 0) for g in recent_games
          )
          sum_gc = sum(
              int(g.get("goals_conceded", 0) or 0) for g in recent_games
          )
          sum_bps = sum(int(g.get("bps", 0) or 0) for g in recent_games)
          sum_bonus = sum(int(g.get("bonus", 0) or 0) for g in recent_games)

          div_mins = sum_mins if sum_mins > 0 else 1

          rolling_records.append({
              "id": pid,
              "rolling_minutes": sum_mins,
              "rolling_xg": sum_xg,
              "rolling_xa": sum_xa,
              "rolling_xgi": sum_xg + sum_xa,
              "rolling_influence": sum_inf,
              "rolling_creativity": sum_creat,
              "rolling_threat": sum_threat,
              "rolling_points": sum_pts,
              "rolling_clean_sheets": sum_cs,
              "rolling_goals_conceded": sum_gc,
              "rolling_bps": sum_bps,
              "rolling_bonus": sum_bonus,
              "rolling_inf_per_90": (sum_inf / div_mins) * 90,
              "rolling_creat_per_90": (sum_creat / div_mins) * 90,
              "rolling_threat_per_90": (sum_threat / div_mins) * 90,
              "rolling_xgi_per_90": ((sum_xg + sum_xa) / div_mins) * 90,
          })
    except:
      continue

  if rolling_records:
    return pd.DataFrame(rolling_records)
  return pd.DataFrame()


# ---------------------------------------------------------
# SIDEBAR: CUSTOM PRESET MANAGER & COMPLETE FILTER SUITE
# ---------------------------------------------------------
st.sidebar.header("Command Center")

# Initialize custom presets in session state with comprehensive parameters
if "saved_presets" not in st.session_state:
  st.session_state.saved_presets = {
      "Default (All Players)": {
          "pos": "All",
          "price": 14.0,
          "min_mode": "Total",
          "mins_val": 0,
          "form": 0.0,
          "xgi": 0.0,
          "inf": 0.0,
          "creat": 0.0,
          "threat": 0.0,
          "clean_sheets": 0.0,
          "goals_conceded": 40.0,
          "bonus": 0,
          "bps": 0,
          "max_fdr": 5,
      },
      "Elite Midfielder Core": {
          "pos": "Midfielder",
          "price": 12.0,
          "min_mode": "Total",
          "mins_val": 450,
          "form": 4.0,
          "xgi": 3.0,
          "inf": 150.0,
          "creat": 150.0,
          "threat": 150.0,
          "clean_sheets": 0.0,
          "goals_conceded": 40.0,
          "bonus": 2,
          "bps": 50,
          "max_fdr": 3,
      },
  }

st.sidebar.subheader("🎛️ Custom Preset Manager")

preset_names = list(st.session_state.saved_presets.keys())
selected_preset = st.sidebar.selectbox("Load Saved Preset:", preset_names)

# Pull chosen preset dictionary values safely
current_values = st.session_state.saved_presets[selected_preset]

positions_list = [
    "All",
    "Goalkeeper",
    "Defender",
    "Midfielder",
    "Forward",
]
default_pos_index = (
    positions_list.index(current_values["pos"])
    if current_values["pos"] in positions_list
    else 0
)

st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ Comprehensive Filter Suite")

# 1. Position & Price
f_pos = st.sidebar.selectbox(
    "Position", positions_list, index=default_pos_index
)
f_price = st.sidebar.slider(
    "Max Price (£M)", 4.0, 14.0, float(current_values.get("price", 14.0))
)

# 2. Minutes Played (Total vs Per 90 accumulation choice)
f_min_mode = st.sidebar.radio(
    "Minutes Filter Mode",
    ["Total", "Per 90 Accumulation"],
    index=(
        0 if current_values.get("min_mode", "Total") == "Total" else 1
    ),
)
if f_min_mode == "Total":
  f_mins = st.sidebar.number_input(
      "Minimum Total Minutes Played",
      value=int(current_values.get("mins_val", 0)),
      step=30,
  )
else:
  f_mins = st.sidebar.number_input(
      "Minimum Minutes Filter Threshold", value=0, step=30
  )

# 3. Fixture Difficulty Rating (FDR) Threshold
f_max_fdr = st.sidebar.slider(
    "Max Next FDR (Fixture Difficulty)",
    1,
    5,
    int(current_values.get("max_fdr", 5)),
)
st.sidebar.caption(
    "Filters based on upcoming opponent fixture difficulty ranking (1 = easiest,"
    " 5 = hardest)."
)

# 4. Form & Performance Metrics
f_form = st.sidebar.number_input(
    "Minimum Form", value=float(current_values.get("form", 0.0))
)
f_xgi = st.sidebar.number_input(
    "Minimum Expected Goal Involvements (xGI)",
    value=float(current_values.get("xgi", 0.0)),
)

# 5. ICT Metrics & Defensive Contributions
f_inf = st.sidebar.number_input(
    "Minimum Influence", value=float(current_values.get("inf", 0.0))
)
f_creat = st.sidebar.number_input(
    "Minimum Creativity", value=float(current_values.get("creat", 0.0))
)
f_threat = st.sidebar.number_input(
    "Minimum Threat", value=float(current_values.get("threat", 0.0))
)
f_cs = st.sidebar.number_input(
    "Minimum Clean Sheets",
    value=float(current_values.get("clean_sheets", 0.0)),
)
f_gc = st.sidebar.slider(
    "Max Goals Conceded",
    0,
    40,
    int(current_values.get("goals_conceded", 40)),
)

# 6. Bonus Points & Total BPS
f_bonus = st.sidebar.number_input(
    "Minimum Bonus Points", value=int(current_values.get("bonus", 0)), step=1
)
f_bps = st.sidebar.number_input(
    "Minimum Total BPS", value=int(current_values.get("bps", 0)), step=10
)

# Rolling Last-X-Games Window Toggle
st.sidebar.markdown("---")
use_rolling_filter = st.sidebar.checkbox(
    "🔥 Use Last X Games Rolling Window (GW5+)"
)
rolling_window_size = 5
if use_rolling_filter:
  rolling_window_size = st.sidebar.slider(
      "Number of Recent Games", 3, 10, 5, key="rolling_slider"
  )
  st.sidebar.caption(
      "Switches stats to aggregate strictly from the chosen recent match"
      " block."
  )

st.sidebar.markdown("---")

# Save / Update Custom Preset Option
new_preset_name = st.sidebar.text_input(
    "Preset Name (Type new or existing name to update):"
)
if st.sidebar.button("💾 Save / Update Preset"):
  if new_preset_name:
    st.session_state.saved_presets[new_preset_name] = {
        "pos": f_pos,
        "price": f_price,
        "min_mode": f_min_mode,
        "mins_val": f_mins,
        "form": f_form,
        "xgi": f_xgi,
        "inf": f_inf,
        "creat": f_creat,
        "threat": f_threat,
        "clean_sheets": f_cs,
        "goals_conceded": f_gc,
        "bonus": f_bonus,
        "bps": f_bps,
        "max_fdr": f_max_fdr,
    }
    st.sidebar.success(f"Preset '{new_preset_name}' saved successfully!")
    st.rerun()
  else:
    st.sidebar.error("Please enter a preset name first.")


# ---------------------------------------------------------
# FILTERING & ROLLING ENGINE
# ---------------------------------------------------------
filtered_df = df.copy()

# Map next fixture difficulty if available
if not fixtures_df.empty and "team" in filtered_df.columns:
  # Find next upcoming fixture for each team
  next_fixtures = fixtures_df[fixtures_df["finished"] == False].sort_values(
      "event"
  )
  team_fdr_map = {}
  for idx, row in filtered_df.iterrows():
    team_id = row["team"]
    # Get first unplayed fixture matching home or away
    team_fix = next_fixtures[
        (next_fixtures["team_h"] == team_id)
        | (next_fixtures["team_a"] == team_id)
    ].head(1)
    if not team_fix.empty:
      fix_row = team_fix.iloc[0]
      if fix_row["team_h"] == team_id:
        team_fdr_map[team_id] = fix_row.get("team_h_difficulty", 3)
      else:
        team_fdr_map[team_id] = fix_row.get("team_a_difficulty", 3)
    else:
      team_fdr_map[team_id] = 3
  filtered_df["next_fdr"] = filtered_df["team"].map(team_fdr_map).fillna(3)
else:
  filtered_df["next_fdr"] = 3

# If rolling window is enabled, fetch and merge sequence data
if use_rolling_filter:
  with st.spinner("Fetching latest player match history..."):
    rolling_df = fetch_rolling_data(
        filtered_df["id"].tolist(), num_games=rolling_window_size
    )
    if not rolling_df.empty:
      filtered_df = filtered_df.merge(rolling_df, on="id", how="left").fillna(
          0
      )
      filtered_df["minutes"] = filtered_df["rolling_minutes"]
      filtered_df["expected_goals"] = filtered_df["rolling_xg"]
      filtered_df["expected_assists"] = filtered_df["rolling_xa"]
      filtered_df["expected_goal_involvements"] = filtered_df["rolling_xgi"]
      filtered_df["influence"] = filtered_df["rolling_influence"]
      filtered_df["creativity"] = filtered_df["rolling_creativity"]
      filtered_df["threat"] = filtered_df["rolling_threat"]
      filtered_df["total_points"] = filtered_df["rolling_points"]
      filtered_df["clean_sheets"] = filtered_df["rolling_clean_sheets"]
      filtered_df["goals_conceded"] = filtered_df["rolling_goals_conceded"]
      filtered_df["bps"] = filtered_df["rolling_bps"]
      filtered_df["bonus"] = filtered_df["rolling_bonus"]
      filtered_df["influence_per_90"] = filtered_df["rolling_inf_per_90"]
      filtered_df["creativity_per_90"] = filtered_df["rolling_creat_per_90"]
      filtered_df["threat_per_90"] = filtered_df["rolling_threat_per_90"]
      filtered_df["xgi_per_90"] = filtered_df["rolling_xgi_per_90"]

# Apply Full Suite of Filters
if f_pos != "All":
  filtered_df = filtered_df[filtered_df["position"] == f_pos]

filtered_df = filtered_df[filtered_df["now_cost"] <= f_price]
filtered_df = filtered_df[filtered_df["next_fdr"] <= f_max_fdr]
filtered_df = filtered_df[filtered_df["form"] >= f_form]
filtered_df = filtered_df[
    filtered_df["expected_goal_involvements"] >= f_xgi
]
filtered_df = filtered_df[filtered_df["influence"] >= f_inf]
filtered_df = filtered_df[filtered_df["creativity"] >= f_creat]
filtered_df = filtered_df[filtered_df["threat"] >= f_threat]
filtered_df = filtered_df[filtered_df["clean_sheets"] >= f_cs]
filtered_df = filtered_df[filtered_df["goals_conceded"] <= f_gc]
filtered_df = filtered_df[filtered_df["bonus"] >= f_bonus]
filtered_df = filtered_df[filtered_df["bps"] >= f_bps]

# Minutes filter rule (Total vs Per 90 Accumulation threshold)
if f_min_mode == "Total":
  filtered_df = filtered_df[filtered_df["minutes"] >= f_mins]
else:
  # If per 90 mode threshold chosen, filter based on calculated accumulation rates
  filtered_df = filtered_df[filtered_df["xgi_per_90"] >= (f_mins / 90.0)]


# ---------------------------------------------------------
# MAIN DASHBOARD DISPLAY
# ---------------------------------------------------------
col1, col2 = st.columns([3, 1])

with col1:
  window_label = (
      f" (Last {rolling_window_size} Games Form)"
      if use_rolling_filter
      else " (Season Totals)"
  )
  st.subheader(
      f"📋 Filtered Shortlist{window_label} — {len(filtered_df)} players"
      " matching criteria"
  )

with col2:
  if not filtered_df.empty:
    csv_data = filtered_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Download to CSV",
        data=csv_data,
        file_name="fpl_custom_watchlist.csv",
        mime="text/csv",
    )

display_columns = [
    "web_name",
    "team_name",
    "position",
    "now_cost",
    "next_fdr",
    "total_points",
    "form",
    "minutes",
    "expected_goal_involvements",
    "xgi_per_90",
    "influence",
    "creativity",
    "threat",
    "clean_sheets",
    "goals_conceded",
    "bonus",
    "bps",
    "selected_by_percent",
]

st.dataframe(
    filtered_df[display_columns].sort_values(
        by="total_points", ascending=False
    ),
    use_container_width=True,
)
