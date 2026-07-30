import pandas as pd
import requests
import streamlit as st

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="FPL Performance & Form Dashboard", page_icon="⚽", layout="wide"
)

st.title("⚽ FPL Player Data & Momentum Tracker")
st.write(
    "Analyze live player data from the official FPL API and filter out players"
    " whose form has gone cold."
)


# --- DATA FETCHING ---
@st.cache_data(ttl=3600)  # Caches data for 1 hour to keep app fast
def load_fpl_data():
  url = "https://fantasy.premierleague.com/api/bootstrap-static/"
  response = requests.get(url)
  if response.status_code != 200:
    st.error("Failed to fetch data from FPL API.")
    return pd.DataFrame()

  data = response.json()
  players = pd.DataFrame(data["elements"])
  teams = pd.DataFrame(data["teams"])

  # Map team IDs to team short names for clarity
  team_mapping = dict(zip(teams["id"], teams["short_name"]))
  players["team_name"] = players["team"].map(team_mapping)

  # Map position types
  position_mapping = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
  position_mapping_long = {
      1: "Goalkeeper",
      2: "Defender",
      3: "Midfielder",
      4: "Forward",
  }
  players["position"] = players["element_type"].map(position_mapping)
  players["position_long"] = players["element_type"].map(position_mapping_long)

  # Format cost (FPL prices are multiplied by 10 in the API, e.g., 105 = £10.5m)
  players["cost"] = players["now_cost"] / 10.0

  return players


with st.spinner("Loading live FPL data..."):
  df = load_fpl_data()

if df.empty:
  st.stop()


# --- SIDEBAR FILTERS ---
st.sidebar.header("Filter Options")

# 1. Short-Term Momentum Form Filter
st.sidebar.markdown("### ⚡ Short-Term Momentum")
min_form = st.sidebar.slider(
    "Minimum Recent Form (Last 30 Days avg)",
    min_value=0.0,
    max_value=10.0,
    value=0.0,
    step=0.5,
)

# 2. Position Filter
positions = ["All", "GK", "DEF", "MID", "FWD"]
selected_position = st.sidebar.selectbox("Position", positions)

# 3. Max Price Filter
max_price = st.sidebar.slider(
    "Max Price (£m)",
    min_value=4.0,
    max_value=15.0,
    value=15.0,
    step=0.5,
)


# --- APPLY FILTERS TO DATAFRAME ---
filtered_df = df.copy()

# Ensure form is numeric
filtered_df["form"] = pd.to_numeric(filtered_df["form"], errors="coerce")

# Apply short-term form filter
filtered_df = filtered_df[filtered_df["form"] >= min_form]

# Apply position filter
if selected_position != "All":
  filtered_df = filtered_df[filtered_df["position"] == selected_position]

# Apply price filter
filtered_df = filtered_df[filtered_df["cost"] <= max_price]


# --- MAIN DISPLAY TABLE ---
st.subheader(
    f"Player Results ({len(filtered_df)} players matching criteria)"
)

# Select key columns to display cleanly
display_columns = [
    "web_name",
    "team_name",
    "position",
    "cost",
    "form",
    "total_points",
    "selected_by_percent",
    "goals_scored",
    "assists",
    "ict_index",
]

# Rename columns for cleaner readability on screen
rename_dict = {
    "web_name": "Player",
    "team_name": "Team",
    "position": "Pos",
    "cost": "Price (£m)",
    "form": "Form",
    "total_points": "Total Pts",
    "selected_by_percent": "Selected %",
    "goals_scored": "Goals",
    "assists": "Assists",
    "ict_index": "ICT Index",
}

output_df = filtered_df[display_columns].rename(columns=rename_dict)

# Sort by form default descending
output_df = output_df.sort_values(by="Form", ascending=False)

# Render the interactive dataframe table
st.dataframe(output_df, use_container_width=True, hide_index=True)
