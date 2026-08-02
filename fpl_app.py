import json
import os
import pandas as pd
import requests
import streamlit as st

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(
    page_title="FPL Dynamic Signal Scanner", page_icon="⚽", layout="wide"
)

st.title("⚽ FPL Custom Signal & Threshold Scanner")
st.markdown(
    "Filter live Fantasy Premier League data dynamically using official FPL"
    " stats & expected data."
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

  return players, fixtures, teams_df, data


with st.spinner("Connecting to live FPL data & fixture feed..."):
  df_players, fixtures, teams_df, raw_data = load_fpl_data()


# Helper function to fetch rolling last-X-games data if requested
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
          sum_mins = sum(int(g.get("minutes", 0) or 0) for g in recent_games)
          sum_xg = sum(
              float(g.get("expected_goals", 0) or 0) for g in recent_games
          )
          sum_xa = sum(
              float(g.get("expected_assists", 0) or 0) for g in recent_games
          )
          sum_inf = sum(float(g.get("influence", 0) or 0) for g in recent_games)
          sum_creat = sum(
              float(g.get("creativity", 0) or 0) for g in recent_games
          )
          sum_threat = sum(float(g.get("threat", 0) or 0) for g in recent_games)
          sum_pts = sum(int(g.get("total_points", 0) or 0) for g in recent_games)
          sum_bps = sum(int(g.get("bps", 0) or 0) for g in recent_games)
          sum_bonus = sum(int(g.get("bonus", 0) or 0) for g in recent_games)

          sum_def = 0
          for g in recent_games:
            for def_key in [
                "defensive_contributions",
                "clearances_blocks_interceptions",
            ]:
              if def_key in g:
                sum_def += int(g.get(def_key, 0) or 0)
                break

          rolling_records.append({
              "id": pid,
              "minutes": sum_mins,
              "total_points": sum_pts,
              "expected_goals": sum_xg,
              "expected_assists": sum_xa,
              "expected_goal_involvements": sum_xg + sum_xa,
              "influence": sum_inf,
              "creativity": sum_creat,
              "threat": sum_threat,
              "bps": sum_bps,
              "bonus": sum_bonus,
              "defensive_contributions": sum_def,
          })
    except:
      continue

  if rolling_records:
    return pd.DataFrame(rolling_records)
  return pd.DataFrame()


if df_players is not None:
  # --- 3. SIDEBAR CONTROL PANEL ---
  st.sidebar.header("🔍 Filter Parameters")

  PRESET_FILE = "fpl_presets.json"
  if "fpl_presets" not in st.session_state:
    if os.path.exists(PRESET_FILE):
      try:
        with open(PRESET_FILE, "r") as f:
          st.session_state["fpl_presets"] = json.load(f)
      except:
        st.session_state["fpl_presets"] = {}
    else:
      st.session_state["fpl_presets"] = {}

  if "loaded_preset_data" not in st.session_state:
    st.session_state["loaded_preset_data"] = {}

  # Preset Manager UI block
  with st.sidebar.expander("💾 Filter Presets Manager", expanded=False):
    preset_names = list(st.session_state["fpl_presets"].keys())
    selected_preset = st.selectbox(
        "Load Saved Preset", options=["-- Select --"] + preset_names
    )

    if selected_preset != "-- Select --":
      if st.button("Apply Preset"):
        st.session_state["loaded_preset_data"] = st.session_state[
            "fpl_presets"
        ][selected_preset]
        st.success(f"Loaded preset: {selected_preset}")
        st.rerun()

    new_preset_name = st.text_input("New Preset Name", key="input_preset_name")

    if st.button("Save Current Filters as Preset"):
      preset_key = new_preset_name.strip()
      if preset_key:
        current_state = {
            "data_scope": locals().get("data_scope", "Season Totals"),
            "rolling_window_size": locals().get("rolling_window_size", 5),
            "selected_position": locals().get("selected_position", "All"),
            "max_price": locals().get(
                "max_price", float(df_players["now_cost"].max())
            ),
            "fixture_horizon": locals().get("fixture_horizon", 5),
            "max_fdr": locals().get("max_fdr", 5.0),
            "min_minutes": locals().get("min_minutes", 0),
            "metric_mode": locals().get("metric_mode", "Total Accumulation"),
            "min_influence": locals().get("min_influence", 0.0),
            "min_threat": locals().get("min_threat", 0.0),
            "min_creativity": locals().get("min_creativity", 0.0),
            "min_xgi": locals().get("min_xgi", 0.0),
            "min_def_contrib": locals().get("min_def_contrib", 0),
            "min_form": locals().get("min_form", 0.0),
            "min_bonus": locals().get("min_bonus", 0),
            "min_bps": locals().get("min_bps", 0),
        }
        st.session_state["fpl_presets"][preset_key] = current_state
        try:
          with open(PRESET_FILE, "w") as f:
            json.dump(st.session_state["fpl_presets"], f)
        except Exception as e:
          st.warning(f"Could not write preset to disk: {e}")

        st.success(f"Preset '{preset_key}' saved successfully!")
      else:
        st.warning("Please enter a valid name for the preset.")

  p_data = st.session_state.get("loaded_preset_data", {})

  # --- DATA SCOPE & FILTERS WITH PRESET MAPPING ---
  scope_options = ["Season Totals", "Last X Gameweeks"]
  saved_scope = p_data.get("data_scope", "Season Totals")
  default_scope_idx = (
      scope_options.index(saved_scope) if saved_scope in scope_options else 0
  )

  data_scope = st.sidebar.radio(
      "Data Scope", options=scope_options, index=default_scope_idx
  )

  rolling_window_size = 5
  if data_scope == "Last X Gameweeks":
    rolling_window_size = st.sidebar.slider(
        "Gameweek Window Size",
        min_value=1,
        max_value=10,
        value=int(p_data.get("rolling_window_size", 5)),
        step=1,
    )

  positions = ["All"] + list(df_players["position"].unique())
  saved_pos = p_data.get("selected_position", "All")
  default_pos_idx = positions.index(saved_pos) if saved_pos in positions else 0
  selected_position = st.sidebar.selectbox(
      "Position", positions, index=default_pos_idx
  )

  min_p, max_p = (
      float(df_players["now_cost"].min()),
      float(df_players["now_cost"].max()),
  )
  max_price = st.sidebar.slider(
      "Max Price (£m)",
      min_value=min_p,
      max_value=max_p,
      value=float(p_data.get("max_price", max_p)),
      step=0.1,
  )

  st.sidebar.markdown("---")
  st.sidebar.subheader("Fixture & Threshold Filters")

  fixture_horizon = st.sidebar.slider(
      "Fixture Horizon (Next X Games)",
      min_value=1,
      max_value=10,
      value=int(p_data.get("fixture_horizon", 5)),
      step=1,
  )

  team_fdr_map = {}
  for team_id in teams_df["id"]:
    team_fixtures = [
        f
        for f in fixtures
        if (f["team_h"] == team_id or f["team_a"] == team_id)
        and not f["finished"]
    ]
    next_fixtures = team_fixtures[:fixture_horizon]

    if next_fixtures:
      difficulties = []
      for f in next_fixtures:
        if f["team_h"] == team_id:
          difficulties.append(f["team_h_difficulty"])
        else:
          difficulties.append(f["team_a_difficulty"])
      team_fdr_map[team_id] = round(sum(difficulties) / len(difficulties), 2)
    else:
      team_fdr_map[team_id] = 3.0

  df_players["dynamic_fdr"] = df_players["team"].map(team_fdr_map)

  max_fdr = st.sidebar.slider(
      f"Max Next {fixture_horizon} Fixture Difficulty (FDR)",
      min_value=1.0,
      max_value=5.0,
      value=float(p_data.get("max_fdr", 5.0)),
      step=0.1,
  )
  min_minutes = st.sidebar.number_input(
      "Min Minutes Played",
      min_value=0,
      value=int(p_data.get("min_minutes", 0)),
      step=90,
  )

  metric_options = ["Total Accumulation", "Per 90 Rates"]
  saved_metric = p_data.get("metric_mode", "Total Accumulation")
  default_metric_idx = (
      metric_options.index(saved_metric)
      if saved_metric in metric_options
      else 0
  )

  metric_mode = st.sidebar.radio(
      "Filter Threshold Mode", options=metric_options, index=default_metric_idx
  )

  st.sidebar.markdown("---")
  if metric_mode == "Total Accumulation":
    min_influence = st.sidebar.number_input(
        "Min Influence",
        min_value=0.0,
        value=float(p_data.get("min_influence", 0.0)),
        step=10.0,
    )
    min_threat = st.sidebar.number_input(
        "Min Threat",
        min_value=0.0,
        value=float(p_data.get("min_threat", 0.0)),
        step=10.0,
    )
    min_creativity = st.sidebar.number_input(
        "Min Creativity",
        min_value=0.0,
        value=float(p_data.get("min_creativity", 0.0)),
        step=10.0,
    )
    min_xgi = st.sidebar.number_input(
        "Min Expected Goal Involvements (xGI)",
        min_value=0.0,
        value=float(p_data.get("min_xgi", 0.0)),
        step=0.05,
    )
    min_def_contrib = st.sidebar.number_input(
        "Min Defensive Contributions",
        min_value=0,
        value=int(p_data.get("min_def_contrib", 0)),
        step=5,
    )
    min_form = st.sidebar.number_input(
        "Min Form",
        min_value=0.0,
        value=float(p_data.get("min_form", 0.0)),
        step=0.5,
    )
    min_bonus = st.sidebar.number_input(
        "Min Bonus Points", min_value=0, value=int(p_data.get("min_bonus", 0))
    )
    min_bps = st.sidebar.number_input(
        "Min Total BPS", min_value=0, value=int(p_data.get("min_bps", 0))
    )
  else:
    min_influence = st.sidebar.number_input(
        "Min Influence Per 90",
        min_value=0.0,
        value=float(p_data.get("min_influence", 0.0)),
        step=5.0,
    )
    min_threat = st.sidebar.number_input(
        "Min Threat Per 90",
        min_value=0.0,
        value=float(p_data.get("min_threat", 0.0)),
        step=5.0,
    )
    min_creativity = st.sidebar.number_input(
        "Min Creativity Per 90",
        min_value=0.0,
        value=float(p_data.get("min_creativity", 0.0)),
        step=5.0,
    )
    min_xgi = st.sidebar.number_input(
        "Min xGI Per 90",
        min_value=0.0,
        value=float(p_data.get("min_xgi", 0.0)),
        step=0.05,
    )
    min_def_contrib = st.sidebar.number_input(
        "Min Def Contrib Per 90",
        min_value=0.0,
        value=float(p_data.get("min_def_contrib", 0.0)),
        step=1.0,
    )
    min_form = st.sidebar.number_input(
        "Min Form",
        min_value=0.0,
        value=float(p_data.get("min_form", 0.0)),
        step=0.5,
    )
    min_bonus = st.sidebar.number_input(
        "Min Bonus Per 90",
        min_value=0.0,
        value=float(p_data.get("min_bonus", 0.0)),
        step=0.1,
    )
    min_bps = st.sidebar.number_input(
        "Min BPS Per 90",
        min_value=0.0,
        value=float(p_data.get("min_bps", 0.0)),
        step=5.0,
    )

  def_col_candidates = [
      "defensive_contributions",
      "clearances_blocks_interceptions",
  ]
  found_def_col = None
  for col in def_col_candidates:
    if col in df_players.columns:
      found_def_col = col
      break

  if found_def_col:
    df_players["defensive_contributions"] = pd.to_numeric(
        df_players[found_def_col], errors="coerce"
    ).fillna(0)
  else:
    df_players["defensive_contributions"] = 0

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
      "dynamic_fdr",
      "bps",
      "bonus",
      "defensive_contributions",
  ]
  for col in numeric_cols:
    if col in df_players.columns:
      df_players[col] = pd.to_numeric(df_players[col], errors="coerce").fillna(
          0
      )

  if data_scope == "Last X Gameweeks":
    with st.spinner(f"Fetching last {rolling_window_size} gameweeks data..."):
      rolling_df = fetch_rolling_data(
          df_players["id"].tolist(), num_games=rolling_window_size
      )
      if not rolling_df.empty:
        df_players = df_players.merge(
            rolling_df, on="id", how="left", suffixes=("", "_rolling")
        )
        for col in [
            "minutes",
            "total_points",
            "expected_goals",
            "expected_assists",
            "expected_goal_involvements",
            "influence",
            "creativity",
            "threat",
            "bps",
            "bonus",
            "defensive_contributions",
        ]:
          if col + "_rolling" in df_players.columns:
            df_players[col] = df_players[col + "_rolling"].fillna(0)

  def calc_per_90(row, col_name):
    return (
        round((row[col_name] / row["minutes"]) * 90, 2)
        if row["minutes"] > 0
        else 0.0
    )

  df_players["points_per_90"] = df_players.apply(
      lambda r: calc_per_90(r, "total_points"), axis=1
  )
  df_players["bps_per_90"] = df_players.apply(
      lambda r: calc_per_90(r, "bps"), axis=1
  )
  df_players["influence_per_90"] = df_players.apply(
      lambda r: calc_per_90(r, "influence"), axis=1
  )
  df_players["threat_per_90"] = df_players.apply(
      lambda r: calc_per_90(r, "threat"), axis=1
  )
  df_players["creativity_per_90"] = df_players.apply(
      lambda r: calc_per_90(r, "creativity"), axis=1
  )
  df_players["xgi_per_90"] = df_players.apply(
      lambda r: calc_per_90(r, "expected_goal_involvements"), axis=1
  )
  df_players["def_contrib_per_90"] = df_players.apply(
      lambda r: calc_per_90(r, "defensive_contributions"), axis=1
  )

  # --- 4. APPLY FILTERING ---
  filtered_df = df_players.copy()

  if selected_position != "All":
    filtered_df = filtered_df[filtered_df["position"] == selected_position]

  filtered_df = filtered_df[filtered_df["now_cost"] <= max_price]
  filtered_df = filtered_df[filtered_df["dynamic_fdr"] <= max_fdr]

  if min_minutes > 0:
    filtered_df = filtered_df[filtered_df["minutes"] >= min_minutes]
  if min_form > 0:
    filtered_df = filtered_df[filtered_df["form"] >= min_form]

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
    if min_def_contrib > 0:
      filtered_df = filtered_df[
          filtered_df["def_contrib_per_90"] >= min_def_contrib
      ]
    if min_bonus > 0:
      filtered_df = filtered_df[filtered_df["bps_per_90"] >= min_bonus]

  filtered_df["Player"] = (
      filtered_df["first_name"] + " " + filtered_df["second_name"]
  )

  display_columns = [
      "Player",
      "team_name",
      "position",
      "now_cost",
      "dynamic_fdr",
      "form",
      "total_points",
      "points_per_90",
      "expected_goal_involvements",
      "defensive_contributions",
      "threat",
      "creativity",
      "influence",
      "bonus",
      "minutes",
      "selected_by_percent",
  ]

  filtered_df = filtered_df.sort_values(
      by=["form", "total_points"], ascending=[False, False]
  )

  # --- 5. RENDER RESULTS ---
  st.subheader(f"Matching Shortlist ({len(filtered_df)} players found)")

  if not filtered_df.empty:
    st.dataframe(
        filtered_df[display_columns].rename(
            columns={
                "team_name": "Team",
                "position": "Pos",
                "now_cost": "Price (£m)",
                "dynamic_fdr": f"Next {fixture_horizon} FDR",
                "form": "Form",
                "total_points": "Points",
                "points_per_90": "Pts/90",
                "expected_goal_involvements": "xGI",
                "defensive_contributions": "Def Contrib",
                "threat": "Threat",
                "creativity": "Creativity",
                "influence": "Influence",
                "bonus": "Bonus",
                "minutes": "Mins",
                "selected_by_percent": "Ownership %",
            }
        ),
        use_container_width=True,
    )
  else:
    st.warning(
        "No players match this exact combination of filters. Try loosening your"
        " thresholds."
    )
