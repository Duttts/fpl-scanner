import pandas as pd
import requests
import streamlit as st

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(
    page_title="FPL Dynamic Signal Scanner", page_icon="⚽", layout="wide"
)

st.title("⚽ FPL Custom Signal & Threshold Scanner")
st.markdown(
    "Filter live Fantasy Premier League data dynamically. Type a minimum threshold for any metric, or leave it blank/none to skip it."
)


# --- 2. LOAD LIVE FPL DATA ---
@st.cache_data(ttl=3600)
def load_fpl_data():
  url = "https://fantasy.premierleague.com/api/bootstrap-static/"
  response = requests.get(url)
  if response.status_code != 200:
    st.error("Failed to fetch live data from Fantasy Premier League API.")
    return None, None

  data = response.json()
  players = pd.DataFrame(data["elements"])
  teams = pd.DataFrame(data["teams"])
  element_types = pd.DataFrame(data["element_types"])

  # Map team names
  team_mapping = teams.set_index("id")["short_name"].to_dict()
  players["team_name"] = players["team"].map(team_mapping)

  # Map position names (Goalkeeper, Defender, Midfielder, Forward)
  position_mapping = element_types.set_index("id")["singular_name"].to_dict()
  players["position"] = players["element_type"].map(position_mapping)

  # Convert price from FPL integer format (e.g. 45 -> 4.5) to float
  players["now_cost"] = players["now_cost"] / 10.0

  # Convert key object columns to numeric safely
  numeric_cols = [
      "now_cost",
      "total_points",
      "influence",
      "threat",
      "creativity",
      "selected_by_percent",
      "form",
      "expected_goals",
      "expected_assists",
  ]
  for col in numeric_cols:
    if col in players.columns:
      players[col] = pd.to_numeric(players[col], errors="coerce")

  return players, data


with st.spinner("Connecting to live FPL data feed..."):
  df_players, raw_data = load_fpl_data()

if df_players is not None:
  # --- 3. SIDEBAR CONTROL PANEL ---
  st.sidebar.header("🔍 Filter Parameters")

  # Position Filter
  positions = ["All"] + list(df_players["position"].unique())
  selected_position = st.sidebar.selectbox("Position", positions)

  # Max Price Slider
  min_p, max_p = (
      float(df_players["now_cost"].min()),
      float(df_players["now_cost"].max()),
  )
  max_price = st.sidebar.slider(
      "Max Price (m)", min_value=min_p, max_value=max_p, value=max_p, step=0.1
  )

  st.sidebar.markdown("---")
  st.sidebar.subheader("Threshold Sliders (Optional)")
  st.sidebar.markdown(
      "Leave a box empty or set to 0 to ignore that requirement."
  )

  # Optional Numeric Threshold Inputs
  min_influence = st.sidebar.number_input(
      "Min Influence", min_value=0.0, value=0.0, step=10.0
  )
  min_threat = st.sidebar.number_input(
      "Min Threat", min_value=0.0, value=0.0, step=10.0
  )
  min_creativity = st.sidebar.number_input(
      "Min Creativity", min_value=0.0, value=0.0, step=10.0
  )
  min_xg = st.sidebar.number_input(
      "Min Expected Goals (xG)", min_value=0.0, value=0.0, step=0.05
  )
  min_form = st.sidebar.number_input(
      "Min Form", min_value=0.0, value=0.0, step=0.5
  )

  # --- 4. APPLY CONDITIONAL LOGIC & FILTERING ---
  filtered_df = df_players.copy()

  # Apply Position Filter
  if selected_position != "All":
    filtered_df = filtered_df[filtered_df["position"] == selected_position]

  # Apply Price Filter
  filtered_df = filtered_df[filtered_df["now_cost"] <= max_price]

  # Apply Threshold Filters dynamically (only if greater than 0)
  if min_influence > 0:
    filtered_df = filtered_df[filtered_df["influence"] >= min_influence]
  if min_threat > 0:
    filtered_df = filtered_df[filtered_df["threat"] >= min_threat]
  if min_creativity > 0:
    filtered_df = filtered_df[filtered_df["creativity"] >= min_creativity]
  if min_xg > 0:
    filtered_df = filtered_df[filtered_df["expected_goals"] >= min_xg]
  if min_form > 0:
    filtered_df = filtered_df[filtered_df["form"] >= min_form]

  # Clean up display names and columns
  filtered_df["Player"] = (
      filtered_df["first_name"] + " " + filtered_df["second_name"]
  )

  display_columns = [
      "Player",
      "team_name",
      "position",
      "now_cost",
      "total_points",
      "form",
      "influence",
      "threat",
      "creativity",
      "expected_goals",
      "selected_by_percent",
  ]

  # Sort by total points descending by default
  filtered_df = filtered_df.sort_values(by="total_points", ascending=False)

  # --- 5. RENDER RESULTS ON SCREEN ---
  st.subheader(f"Matching Shortlist ({len(filtered_df)} players found)")

  if not filtered_df.empty:
    st.dataframe(
        filtered_df[display_columns].rename(
            columns={
                "team_name": "Team",
                "position": "Pos",
                "now_cost": "Price (£m)",
                "total_points": "Points",
                "selected_by_percent": "Ownership %",
                "expected_goals": "xG",
            }
        ),
        use_container_width=True,
    )
  else:
    st.warning(
        "No players match this exact combination of filters. Try loosening"
        " your parameters or setting some thresholds back to zero/none."
    )
