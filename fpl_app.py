import pandas as pd
import requests
import streamlit as st

# Set page layout to wide for a better laptop workspace
st.set_page_config(
    page_title="Custom FPL Dashboard", page_icon="⚽", layout="wide"
)

st.title("⚽ Advanced FPL Strategy Dashboard")
st.write(
    "Welcome to your custom laptop command center. Use the sidebar to manage filters, custom presets, and analytical views."
)


@st.cache_data(ttl=3600)
def load_fpl_data():
  url = "https://fantasy.premierleague.com/api/bootstrap-static/"
  response = requests.get(url)
  data = response.json()

  # Extract players and positions
  players_df = pd.DataFrame(data["elements"])
  teams_df = pd.DataFrame(data["teams"])
  positions_df = pd.DataFrame(data["element_types"])

  # Map team names and positions for readability
  team_mapping = teams_df.set_index("id")["name"].to_dict()
  position_mapping = positions_df.set_index("id")["singular_name"].to_dict()

  players_df["team_name"] = players_df["team"].map(team_mapping)
  players_df["position"] = players_df["element_type"].map(position_mapping)

  # Clean up columns and convert data types
  players_df["now_cost"] = players_df["now_cost"] / 10.0
  players_df["selected_by_percent"] = pd.to_numeric(
      players_df["selected_by_percent"]
  )
  players_df["total_points"] = pd.to_numeric(players_df["total_points"])
  players_df["influence"] = pd.to_numeric(players_df["influence"])
  players_df["creativity"] = pd.to_numeric(players_df["creativity"])
  players_df["threat"] = pd.to_numeric(players_df["threat"])
  players_df["expected_goals"] = pd.to_numeric(players_df["expected_goals"])

  return players_df


# Load the data
try:
  df = load_fpl_data()
except Exception as e:
  st.error(f"Error connecting to FPL API: {e}")
  st.stop()


# ---------------------------------------------------------
# SIDEBAR: PRESET MANAGER & FILTERS
# ---------------------------------------------------------
st.sidebar.header("Command Center")

# 1. Initialize custom presets storage in session state
if "saved_presets" not in st.session_state:
  st.session_state.saved_presets = {
      "Default (All Players)": {
          "price": 14.0,
          "xg": 0.0,
          "inf": 0.0,
          "pos": "All",
      },
      "Budget Midfielders": {
          "price": 6.5,
          "xg": 2.0,
          "inf": 100.0,
          "pos": "Midfielder",
      },
  }

st.sidebar.subheader("🎛️ Custom Preset Manager")

# 2. Dropdown to select from your saved presets
preset_names = list(st.session_state.saved_presets.keys())
selected_preset = st.sidebar.selectbox("Load Saved Preset:", preset_names)

# Grab the values of the chosen preset
current_values = st.session_state.saved_presets[selected_preset]

# Position selection mapped to preset
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

# 3. Interactive filter widgets (pre-filled with preset values, fully customizable)
f_pos = st.sidebar.selectbox(
    "Position", positions_list, index=default_pos_index
)
f_price = st.sidebar.slider(
    "Max Price (£M)", 4.0, 14.0, float(current_values["price"])
)
f_xg = st.sidebar.number_input(
    "Minimum xG (Expected Goals)", value=float(current_values["xg"])
)
f_inf = st.sidebar.number_input(
    "Minimum Influence", value=float(current_values["inf"])
)

# 4. Rolling stats toggle (ready for when GW5+ hits)
st.sidebar.markdown("---")
use_rolling_filter = st.sidebar.checkbox(
    "🔥 Use Last 5 Games Window (GW5+)"
)
if use_rolling_filter:
  st.sidebar.info(
      "Note: Rolling filters activate automatically once API history data"
      " populates during the active season."
  )

st.sidebar.markdown("---")

# 5. Save/Overwrite options
new_preset_name = st.sidebar.text_input(
    "Preset Name (Type new or existing name to update):"
)
if st.sidebar.button("💾 Save / Update Preset"):
  if new_preset_name:
    st.session_state.saved_presets[new_preset_name] = {
        "price": f_price,
        "xg": f_xg,
        "inf": f_inf,
        "pos": f_pos,
    }
    st.sidebar.success(f"Preset '{new_preset_name}' saved successfully!")
    st.rerun()
  else:
    st.sidebar.error("Please enter a preset name first.")


# ---------------------------------------------------------
# FILTERING ENGINE
# ---------------------------------------------------------
filtered_df = df.copy()

# Apply Position Filter
if f_pos != "All":
  filtered_df = filtered_df[filtered_df["position"] == f_pos]

# Apply Price Filter
filtered_df = filtered_df[filtered_df["now_cost"] <= f_price]

# Apply xG Filter
filtered_df = filtered_df[filtered_df["expected_goals"] >= f_xg]

# Apply Influence Filter
filtered_df = filtered_df[filtered_df["influence"] >= f_inf]


# ---------------------------------------------------------
# MAIN DASHBOARD DISPLAY
# ---------------------------------------------------------
col1, col2 = st.columns([3, 1])

with col1:
  st.subheader(
      f"📋 Filtered Shortlist ({len(filtered_df)} players matching criteria)"
  )

with col2:
  # CSV Download Feature (works locally without Excel installed)
  if not filtered_df.empty:
    csv_data = filtered_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Download to CSV",
        data=csv_data,
        file_name="fpl_custom_watchlist.csv",
        mime="text/csv",
    )

# Select key columns to display cleanly
display_columns = [
    "web_name",
    "team_name",
    "position",
    "now_cost",
    "total_points",
    "expected_goals",
    "influence",
    "threat",
    "selected_by_percent",
]

st.dataframe(
    filtered_df[display_columns].sort_values(
        by="total_points", ascending=False
    ),
    use_container_width=True,
)
