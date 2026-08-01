import pandas as pd
import requests
import streamlit as st

# Set page layout to wide for your laptop workspace
st.set_page_config(
    page_title="Custom FPL Dashboard", page_icon="⚽", layout="wide"
)

st.title("⚽ Advanced FPL Strategy Dashboard")
st.write(
    "Welcome to your custom laptop command center. Complete with your full"
    " filter suite, custom preset manager, and rolling last-X-games filter"
    " support."
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

  # Convert columns cleanly
  players_df["now_cost"] = players_df["now_cost"] / 10.0
  players_df["selected_by_percent"] = pd.to_numeric(
      players_df["selected_by_percent"]
  )
  players_df["total_points"] = pd.to_numeric(players_df["total_points"])
  players_df["influence"] = pd.to_numeric(players_df["influence"])
  players_df["creativity"] = pd.to_numeric(players_df["creativity"])
  players_df["threat"] = pd.to_numeric(players_df["threat"])
  players_df["expected_goals"] = pd.to_numeric(players_df["expected_goals"])
  players_df["expected_assists"] = pd.to_numeric(
      players_df["expected_assists"]
  )
  players_df["form"] = pd.to_numeric(players_df["form"])

  for col in ["clean_sheets", "goals_conceded"]:
    if col in players_df.columns:
      players_df[col] = pd.to_numeric(players_df[col], errors="coerce").fillna(
          0.0
      )
    else:
      players_df[col] = 0.0

  return players_df, data["events"]


# Load the main dataset and events info
try:
  df, events_data = load_fpl_data()
except Exception as e:
  st.error(f"Error connecting to FPL API: {e}")
  st.stop()


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
          # Take the last N completed games of the current season
          recent_games = history[-num_games:]
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

          rolling_records.append({
              "id": pid,
              "rolling_xg": sum_xg,
              "rolling_xa": sum_xa,
              "rolling_influence": sum_inf,
              "rolling_creativity": sum_creat,
              "rolling_threat": sum_threat,
              "rolling_points": sum_pts,
              "rolling_clean_sheets": sum_cs,
              "rolling_goals_conceded": sum_gc,
          })
    except:
      continue

  if rolling_records:
    return pd.DataFrame(rolling_records)
  return pd.DataFrame()


# ---------------------------------------------------------
# SIDEBAR: CUSTOM PRESET MANAGER & FULL FILTERS
# ---------------------------------------------------------
st.sidebar.header("Command Center")

# Initialize custom presets in session state with full parameter sets
if "saved_presets" not in st.session_state:
  st.session_state.saved_presets = {
      "Default (All Players)": {
          "pos": "All",
          "price": 14.0,
          "form": 0.0,
          "xg": 0.0,
          "xa": 0.0,
          "inf": 0.0,
          "creat": 0.0,
          "threat": 0.0,
          "clean_sheets": 0.0,
          "goals_conceded": 40.0,
      },
      "Budget Defensive Core": {
          "pos": "Defender",
          "price": 5.5,
          "form": 0.0,
          "xg": 0.0,
          "xa": 0.0,
          "inf": 0.0,
          "creat": 0.0,
          "threat": 0.0,
          "clean_sheets": 2.0,
          "goals_conceded": 5.0,
      },
  }

st.sidebar.subheader("🎛️ Custom Preset Manager")

preset_names = list(st.session_state.saved_presets.keys())
selected_preset = st.sidebar.selectbox("Load Saved Preset:", preset_names)

# Pull chosen preset dictionary values
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
st.sidebar.subheader("⚙️ Full Filter Parameters")

# Interactive Filter Widgets pre-filled with preset values
f_pos = st.sidebar.selectbox(
    "Position", positions_list, index=default_pos_index
)
f_price = st.sidebar.slider(
    "Max Price (£M)", 4.0, 14.0, float(current_values["price"])
)
f_form = st.sidebar.number_input(
    "Minimum Form", value=float(current_values["form"])
)
f_xg = st.sidebar.number_input(
    "Minimum xG (Expected Goals)", value=float(current_values["xg"])
)
f_xa = st.sidebar.number_input(
    "Minimum xA (Expected Assists)", value=float(current_values["xa"])
)
f_inf = st.sidebar.number_input(
    "Minimum Influence", value=float(current_values["inf"])
)
f_creat = st.sidebar.number_input(
    "Minimum Creativity", value=float(current_values["creat"])
)
f_threat = st.sidebar.number_input(
    "Minimum Threat", value=float(current_values["threat"])
)
f_cs = st.sidebar.number_input(
    "Minimum Clean Sheets", value=float(current_values["clean_sheets"])
)
f_gc = st.sidebar.slider(
    "Max Goals Conceded", 0, 40, int(current_values["goals_conceded"])
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
      "Switches xG, xA, Threat, and Points metrics to aggregate strictly from"
      " the chosen recent match block."
  )

st.sidebar.markdown("---")

# Save / Update Preset Option
new_preset_name = st.sidebar.text_input(
    "Preset Name (Type new or existing name to update):"
)
if st.sidebar.button("💾 Save / Update Preset"):
  if new_preset_name:
    st.session_state.saved_presets[new_preset_name] = {
        "pos": f_pos,
        "price": f_price,
        "form": f_form,
        "xg": f_xg,
        "xa": f_xa,
        "inf": f_inf,
        "creat": f_creat,
        "threat": f_threat,
        "clean_sheets": f_cs,
        "goals_conceded": f_gc,
    }
    st.sidebar.success(f"Preset '{new_preset_name}' saved successfully!")
    st.rerun()
  else:
    st.sidebar.error("Please enter a preset name first.")


# ---------------------------------------------------------
# FILTERING & ROLLING ENGINE
# ---------------------------------------------------------
filtered_df = df.copy()

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
      # Remap filter columns to target rolling metrics instead of whole season totals
      filtered_df["expected_goals"] = filtered_df["rolling_xg"]
      filtered_df["expected_assists"] = filtered_df["rolling_xa"]
      filtered_df["influence"] = filtered_df["rolling_influence"]
      filtered_df["creativity"] = filtered_df["rolling_creativity"]
      filtered_df["threat"] = filtered_df["rolling_threat"]
      filtered_df["total_points"] = filtered_df["rolling_points"]
      filtered_df["clean_sheets"] = filtered_df["rolling_clean_sheets"]
      filtered_df["goals_conceded"] = filtered_df["rolling_goals_conceded"]

# Apply Full Suite of Filters
if f_pos != "All":
  filtered_df = filtered_df[filtered_df["position"] == f_pos]

filtered_df = filtered_df[filtered_df["now_cost"] <= f_price]
filtered_df = filtered_df[filtered_df["form"] >= f_form]
filtered_df = filtered_df[filtered_df["expected_goals"] >= f_xg]
filtered_df = filtered_df[filtered_df["expected_assists"] >= f_xa]
filtered_df = filtered_df[filtered_df["influence"] >= f_inf]
filtered_df = filtered_df[filtered_df["creativity"] >= f_creat]
filtered_df = filtered_df[filtered_df["threat"] >= f_threat]
filtered_df = filtered_df[filtered_df["clean_sheets"] >= f_cs]
filtered_df = filtered_df[filtered_df["goals_conceded"] <= f_gc]


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
    "total_points",
    "form",
    "expected_goals",
    "expected_assists",
    "influence",
    "creativity",
    "threat",
    "clean_sheets",
    "goals_conceded",
    "selected_by_percent",
]

st.dataframe(
    filtered_df[display_columns].sort_values(
        by="total_points", ascending=False
    ),
    use_container_width=True,
)
