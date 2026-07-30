import pandas as pd
import requests
import streamlit as st

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(
    page_title="FPL Dynamic Signal Scanner", page_icon="⚽", layout="wide"
)

st.title("⚽ FPL Custom Signal & Threshold Scanner")
st.markdown(
    "Filter live Fantasy Premier League data dynamically. Set a threshold only"
    " when you want to filter."
)


# --- 2. LOAD LIVE FPL & FIXTURE DATA ---
@st.cache_data(ttl=3600)
def load_fpl_data():
  url_bootstrap = "https://fantasy.premierleague.com/api/bootstrap-static/"
  url_fixtures = "https://fantasy.premierleague.com/api/fixtures/"

  response_b = requests.get(url_bootstrap)
  response_f = requests.get(url_fixtures)

  if response_b.status_code != 200 or response_f.status_code != 200:
    st.error("Failed to fetch live data from Fantasy Premier League API.")
    return None, None

  data = response_b.json()
  fixtures = response_f.json()

  players = pd.DataFrame(data["elements"])
  teams_df = pd.DataFrame(data["teams"])
  element_types = pd.DataFrame(data["element_types"])

  team_mapping = teams_df.set_index("id")["short_name"].to_dict()
  players["team_name"] = players["team"].map(team_mapping)

  position_mapping = element_types.set_index("id")["singular_name"].to_dict()
  players["position"] = players["element_type"].map(position_mapping)

  players["now_cost"] = players["now_cost"] / 10.0

  # Calculate Next 5 Fixture Difficulty Rating (FDR) for each team
  team_fdr_map = {}
  for team_id in teams_df["id"]:
    team_fixtures = [
        f
        for f in fixtures
        if (f["team_h"] == team_id or f["team_a"] == team_id)
        and not f["finished"]
    ]
    next_5 = team_fixtures[:5]

    if next_5:
      difficulties = []
      for f in next_5:
        if f["team_h"] == team_id:
          difficulties.append(f["team_h_difficulty"])
        else:
          difficulties.append(f["team_a_difficulty"])
      team_fdr_map[team_id] = round(sum(difficulties) / len(difficulties), 2)
    else:
      team_fdr_map[team_id] = 3.0  # Fallback neutral average

  players["next_5_fdr"] = players["team"].map(team_fdr_map)

  # Ensure defensive_contributions column exists safely
  if "defensive_contributions" not in players.columns:
    players["defensive_contributions"] = 0
  else:
    players["defensive_contributions"] = players[
        "defensive_contributions"
    ].fillna(0)

  # Ensure advanced tracking stats exist safely in raw payload
  advanced_cols_check = [
      "shots",
      "shots_in_the_box",
      "key_passes",
      "touches_in_penalty_area",
  ]
  for col in advanced_cols_check:
    if col not in players.columns:
      players[col] = 0
    else:
      players[col] = players[col].fillna(0)

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
      "expected_goal_involvements",
      "minutes",
      "next_5_fdr",
      "bps",
      "bonus",
      "defensive_contributions",
      "shots",
      "shots_in_the_box",
      "key_passes",
      "touches_in_penalty_area",
  ]
  for col in numeric_cols:
    if col in players.columns:
      players[col] = pd.to_numeric(players[col], errors="coerce")

  # --- CALCULATE RATES PER 90 ---
  def calc_per_90(row, col_name):
    return (
        round((row[col_name] / row["minutes"]) * 90, 2)
        if row["minutes"] > 0
        else 0.0
    )

  players["points_per_90"] = players.apply(
      lambda r: calc_per_90(r, "total_points"), axis=1
  )
  players["bps_per_90"] = players.apply(
      lambda r: calc_per_90(r, "bps"), axis=1
  )
  players["influence_per_90"] = players.apply(
      lambda r: calc_per_90(r, "influence"), axis=1
  )
  players["threat_per_90"] = players.apply(
      lambda r: calc_per_90(r, "threat"), axis=1
  )
  players["creativity_per_90"] = players.apply(
      lambda r: calc_per_90(r, "creativity"), axis=1
  )
  players["xgi_per_90"] = players.apply(
      lambda r: calc_per_90(r, "expected_goal_involvements"), axis=1
  )
  players["def_contrib_per_90"] = players.apply(
      lambda r: calc_per_90(r, "defensive_contributions"), axis=1
  )
  players["shots_per_90"] = players.apply(
      lambda r: calc_per_90(r, "shots"), axis=1
  )
  players["shots_in_box_per_90"] = players.apply(
      lambda r: calc_per_90(r, "shots_in_the_box"), axis=1
  )
  players["key_passes_per_90"] = players.apply(
      lambda r: calc_per_90(r, "key_passes"), axis=1
  )
  players["touches_in_box_per_90"] = players.apply(
      lambda r: calc_per_90(r, "touches_in_penalty_area"), axis=1
  )

  return players, data


with st.spinner("Connecting to live FPL data & fixture feed..."):
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
      "Max Price (£m)", min_value=min_p, max_value=max_p, value=max_p, step=0.1
  )

  st.sidebar.markdown("---")
  st.sidebar.subheader("Fixture & Threshold Filters")

  # Max Next 5 Fixture Difficulty Slider (Lower = Easier fixtures)
  max_fdr = st.sidebar.slider(
      "Max Next 5 Fixture Difficulty (FDR)",
      min_value=1.0,
      max_value=5.0,
      value=5.0,
      step=0.1,
  )
  st.sidebar.markdown(
      "*(Lower FDR means easier upcoming games. 1=Very Easy, 5=Very Hard)*"
  )

  st.sidebar.markdown("---")
  min_minutes = st.sidebar.number_input(
      "Min Minutes Played", min_value=0, value=0, step=90
  )

  # --- TOGGLE FOR TOTALS VS PER 90 ---
  metric_mode = st.sidebar.radio(
      "Filter Threshold Mode",
      options=["Total Accumulation", "Per 90 Rates"],
      help=(
          "Switch between filtering by total recorded stats or normalized"
          " per-90 rates."
      ),
  )

  st.sidebar.markdown("---")
  if metric_mode == "Total Accumulation":
    min_influence = st.sidebar.number_input(
        "Min Influence", min_value=0.0, value=0.0, step=10.0
    )
    min_threat = st.sidebar.number_input(
        "Min Threat", min_value=0.0, value=0.0, step=10.0
    )
    min_creativity = st.sidebar.number_input(
        "Min Creativity", min_value=0.0, value=0.0, step=10.0
    )
    min_xgi = st.sidebar.number_input(
        "Min Expected Goal Involvements (xGI)",
        min_value=0.0,
        value=0.0,
        step=0.05,
    )
    min_shots = st.sidebar.number_input(
        "Min Total Shots", min_value=0, value=0, step=2
    )
    min_shots_box = st.sidebar.number_input(
        "Min Shots in the Box", min_value=0, value=0, step=2
    )
    min_key_passes = st.sidebar.number_input(
        "Min Key Passes", min_value=0, value=0, step=2
    )
    min_touches_box = st.sidebar.number_input(
        "Min Touches in Box", min_value=0, value=0, step=5
    )
    min_form = st.sidebar.number_input(
        "Min Form (Last 30 Days)", min_value=0.0, value=0.0, step=0.5
    )
    min_def_contrib = st.sidebar.number_input(
        "Min Defensive Contributions", min_value=0, value=0, step=5
    )
    min_bonus = st.sidebar.number_input(
        "Min Bonus Points Accumulated", min_value=0, value=0, step=1
    )
    min_bps = st.sidebar.number_input(
        "Min Total BPS (Bonus System)", min_value=0, value=0, step=25
    )
  else:
    min_influence = st.sidebar.number_input(
        "Min Influence Per 90", min_value=0.0, value=0.0, step=5.0
    )
    min_threat = st.sidebar.number_input(
        "Min Threat Per 90", min_value=0.0, value=0.0, step=5.0
    )
    min_creativity = st.sidebar.number_input(
        "Min Creativity Per 90", min_value=0.0, value=0.0, step=5.0
    )
    min_xgi = st.sidebar.number_input(
        "Min xGI Per 90", min_value=0.0, value=0.0, step=0.05
    )
    min_shots = st.sidebar.number_input(
        "Min Shots Per 90", min_value=0.0, value=0.0, step=0.5
    )
    min_shots_box = st.sidebar.number_input(
        "Min Shots in Box Per 90", min_value=0.0, value=0.0, step=0.5
    )
    min_key_passes = st.sidebar.number_input(
        "Min Key Passes Per 90", min_value=0.0, value=0.0, step=0.5
    )
    min_touches_box = st.sidebar.number_input(
        "Min Touches in Box Per 90", min_value=0.0, value=0.0, step=1.0
    )
    min_form = st.sidebar.number_input(
        "Min Form (Last 30 Days)", min_value=0.0, value=0.0, step=0.5
    )
    min_def_contrib = st.sidebar.number_input(
        "Min Def Contrib Per 90", min_value=0.0, value=0.0, step=1.0
    )
    min_bonus = st.sidebar.number_input(
        "Min Bonus Per 90", min_value=0.0, value=0.0, step=0.1
    )
    min_bps = st.sidebar.number_input(
        "Min BPS Per 90", min_value=0.0, value=0.0, step=5.0
    )

  # --- 4. APPLY CONDITIONAL LOGIC & FILTERING ---
  filtered_df = df_players.copy()

  # Apply Position Filter
  if selected_position != "All":
    filtered_df = filtered_df[filtered_df["position"] == selected_position]

  # Apply Price Filter
  filtered_df = filtered_df[filtered_df["now_cost"] <= max_price]

  # Apply Fixture Difficulty Filter (Keep teams with FDR <= chosen max)
  filtered_df = filtered_df[filtered_df["next_5_fdr"] <= max_fdr]

  # Apply Minutes Filter
  if min_minutes > 0:
    filtered_df = filtered_df[filtered_df["minutes"] >= min_minutes]

  # Apply Form Filter universally (since FPL form is independent of mode totals/rates)
  if min_form > 0:
    filtered_df = filtered_df[filtered_df["form"] >= min_form]

  # Apply Threshold Filters dynamically based on selected mode
  if metric_mode == "Total Accumulation":
    if min_influence > 0:
      filtered_df = filtered_df[filtered_df["influence"] >= min_influence]
    if min_threat > 0:
      filtered_df = filtered_df[filtered_df["threat"] >= min_threat]
    if min_creativity > 0:
      filtered_df = filtered_df[filtered_df["creativity"] >= min_creativity]
    if min_xgi > 0:
      filtered_df = filtered_df[
          filtered_df["expected_goal_involvements"] >= min_xgi
      ]
    if min_shots > 0:
      filtered_df = filtered_df[filtered_df["shots"] >= min_shots]
    if min_shots_box > 0:
      filtered_df = filtered_df[
          filtered_df["shots_in_the_box"] >= min_shots_box
      ]
    if min_key_passes > 0:
      filtered_df = filtered_df[filtered_df["key_passes"] >= min_key_passes]
    if min_touches_box > 0:
      filtered_df = filtered_df[
          filtered_df["touches_in_penalty_area"] >= min_touches_box
      ]
    if min_def_contrib > 0:
      filtered_df = filtered_df[
          filtered_df["defensive_contributions"] >= min_def_contrib
      ]
    if min_bonus > 0:
      filtered_df = filtered_df[filtered_df["bonus"] >= min_bonus]
    if min_bps > 0:
      filtered_df = filtered_df[filtered_df["bps"] >= min_bps]
  else:
    if min_influence > 0:
      filtered_df = filtered_df[
          filtered_df["influence_per_90"] >= min_influence
      ]
    if min_threat > 0:
      filtered_df = filtered_df[filtered_df["threat_per_90"] >= min_threat]
    if min_creativity > 0:
      filtered_df = filtered_df[
          filtered_df["creativity_per_90"] >= min_creativity
      ]
    if min_xgi > 0:
      filtered_df = filtered_df[filtered_df["xgi_per_90"] >= min_xgi]
    if min_shots > 0:
      filtered_df = filtered_df[filtered_df["shots_per_90"] >= min_shots]
    if min_shots_box > 0:
      filtered_df = filtered_df[
          filtered_df["shots_in_box_per_90"] >= min_shots_box
      ]
    if min_key_passes > 0:
      filtered_df = filtered_df[
          filtered_df["key_passes_per_90"] >= min_key_passes
      ]
    if min_touches_box > 0:
      filtered_df = filtered_df[
          filtered_df["touches_in_box_per_90"] >= min_touches_box
      ]
    if min_def_contrib > 0:
      filtered_df = filtered_df[
          filtered_df["def_contrib_per_90"] >= min_def_contrib
      ]
    if min_bonus > 0:
      filtered_df = filtered_df[filtered_df["bps_per_90"] >= min_bps]

  # Clean up display names and columns
  filtered_df["Player"] = (
      filtered_df["first_name"] + " " + filtered_df["second_name"]
  )

  display_columns = [
      "Player",
      "team_name",
      "position",
      "now_cost",
      "next_5_fdr",
      "form",
      "total_points",
      "points_per_90",
      "expected_goal_involvements",
      "shots_in_the_box",
      "key_passes",
      "touches_in_penalty_area",
      "defensive_contributions",
      "bonus",
      "minutes",
      "selected_by_percent",
  ]

  # Sort by form and total points descending by default
  filtered_df = filtered_df.sort_values(
      by=["form", "total_points"], ascending=[False, False]
  )

  # --- 5. RENDER RESULTS ON SCREEN ---
  st.subheader(f"Matching Shortlist ({len(filtered_df)} players found)")

  if not filtered_df.empty:
    st.dataframe(
        filtered_df[display_columns].rename(
            columns={
                "team_name": "Team",
                "position": "Pos",
                "now_cost": "Price (£m)",
                "next_5_fdr": "Next 5 FDR",
                "form": "Form",
                "total_points": "Points",
                "points_per_90": "Pts/90",
                "expected_goal_involvements": "xGI",
                "shots_in_the_box": "Shots in Box",
                "key_passes": "Key Passes",
                "touches_in_penalty_area": "Box Touches",
                "defensive_contributions": "Def Contrib",
                "bonus": "Bonus",
                "minutes": "Mins",
                "selected_by_percent": "Ownership %",
            }
        ),
        use_container_width=True,
    )
  else:
    st.warning(
        "No players match this exact combination of filters. Try loosening"
        " your fixture difficulty slider or thresholds."
    )
