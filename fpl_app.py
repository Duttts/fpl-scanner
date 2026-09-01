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
    "Filter live Fantasy Premier League data dynamically using official FPL stats & expected data."
)


# --- 2. LOAD LIVE FPL & FIXTURE DATA ---
@st.cache_data(ttl=3600)
def load_fpl_data():
    url_bootstrap = "https://fantasy.premierleague.com/api/bootstrap-static/"
    url_fixtures = "https://fantasy.premierleague.com/api/fixtures/"

    try:
        response_b = requests.get(url_bootstrap, timeout=15)
        response_f = requests.get(url_fixtures, timeout=15)
    except Exception:
        return None, None, None, None

    if response_b.status_code != 200 or response_f.status_code != 200:
        return None, None, None, None

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

if df_players is None:
    st.error("Failed to fetch live data from Fantasy Premier League API. Please try again later.")
    st.stop()


# --- DEFENSIVE METRIC BUILDER ---
def build_defensive_metric(df):
    col = "clearances_blocks_interceptions"
    if col not in df.columns:
        df[col] = 0
    df["defensive_contributions"] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df

df_players = build_defensive_metric(df_players)


# Determine current active gameweek dynamically
current_gw = 1
if raw_data and "events" in raw_data:
    for event in raw_data["events"]:
        if event.get("is_current") or event.get("is_next"):
            current_gw = event.get("id", 1)
            if event.get("is_current"):
                break


@st.cache_data(ttl=3600)
def fetch_user_team(manager_id, gw):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
    }
    url = f"https://fantasy.premierleague.com/api/entry/{manager_id}/event/{gw}/picks/"
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            picks_data = r.json().get("picks", [])
            if picks_data:
                return [p["element"] for p in picks_data]
    except Exception:
        pass
    return []


@st.cache_data(ttl=3600)
def fetch_rolling_data(player_ids, num_gameweeks=5):
    rolling_records = []
    for pid in player_ids:
        try:
            r = requests.get(
                f"https://fantasy.premierleague.com/api/element-summary/{pid}/",
                timeout=10,
            )
            if r.status_code == 200:
                history = r.json().get("history", [])
                if history:
                    gw_groups = {}
                    for match in history:
                        gw = match.get("round")
                        if gw:
                            if gw not in gw_groups:
                                gw_groups[gw] = []
                            gw_groups[gw].append(match)

                    sorted_gws = sorted(gw_groups.keys())
                    recent_gw_keys = sorted_gws[-num_gameweeks:]

                    recent_matches = []
                    for gw in recent_gw_keys:
                        recent_matches.extend(gw_groups[gw])

                    if not recent_matches:
                        continue

                    sum_mins = sum(int(g.get("minutes", 0) or 0) for g in recent_matches)
                    sum_xg = sum(float(g.get("expected_goals", 0) or 0) for g in recent_matches)
                    sum_xa = sum(float(g.get("expected_assists", 0) or 0) for g in recent_matches)
                    sum_inf = sum(float(g.get("influence", 0) or 0) for g in recent_matches)
                    sum_creat = sum(float(g.get("creativity", 0) or 0) for g in recent_matches)
                    sum_threat = sum(float(g.get("threat", 0) or 0) for g in recent_matches)
                    sum_pts = sum(int(g.get("total_points", 0) or 0) for g in recent_matches)
                    sum_bps = sum(int(g.get("bps", 0) or 0) for g in recent_matches)
                    sum_bonus = sum(int(g.get("bonus", 0) or 0) for g in recent_matches)
                    sum_cs = sum(int(g.get("clean_sheets", 0) or 0) for g in recent_matches)

                    sum_def = 0
                    for g in recent_matches:
                        for def_key in ["defensive_contributions", "clearances_blocks_interceptions"]:
                            if def_key in g:
                                sum_def += int(g.get(def_key, 0) or 0)
                                break

                    form_trend_val = 0.0
                    form_status = "Stable ➡️"

                    if len(recent_gw_keys) >= 4:
                        last_two_gws = recent_gw_keys[-2:]
                        baseline_gws = recent_gw_keys[:-2]

                        last_two_matches = [m for gw in last_two_gws for m in gw_groups[gw]]
                        baseline_matches = [m for gw in baseline_gws for m in gw_groups[gw]]

                        def get_composite_score(matches):
                            n = len(matches)
                            if n == 0:
                                return 0.0
                            xgi = sum(float(g.get("expected_goals", 0) or 0) + float(g.get("expected_assists", 0) or 0) for g in matches) / n
                            threat = (sum(float(g.get("threat", 0) or 0) for g in matches) / n) / 100.0
                            influence = (sum(float(g.get("influence", 0) or 0) for g in matches) / n) / 100.0
                            return (xgi * 0.5) + (threat * 0.3) + (influence * 0.2)

                        recent_score = get_composite_score(last_two_matches)
                        baseline_score = get_composite_score(baseline_matches)
                        form_trend_val = round(recent_score - baseline_score, 2)

                        if form_trend_val > 0.10:
                            form_status = "Surging 📈"
                        elif form_trend_val < -0.10:
                            form_status = "Cooling 📉"
                        else:
                            form_status = "Stable ➡️"

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
                        "clean_sheets": sum_cs,
                        "defensive_contributions": sum_def,
                        "form_trend_delta": form_trend_val,
                        "form_status": form_status,
                    })
        except Exception:
            continue

    if rolling_records:
        return pd.DataFrame(rolling_records)
    return pd.DataFrame()


def calculate_recent_opponent_stats(opponent_id, fixtures_list, window=5):
    if not opponent_id or not fixtures_list:
        return 1.0, 0.0, 0.0

    opp_fixtures = [
        f for f in fixtures_list
        if (f["team_h"] == opponent_id or f["team_a"] == opponent_id) and f["finished"]
    ]

    if not opp_fixtures:
        return 1.0, 0.0, 0.0

    opp_fixtures = sorted(opp_fixtures, key=lambda x: x.get("event", 0), reverse=True)
    recent_matches = opp_fixtures[:window]

    if not recent_matches:
        return 1.0, 0.0, 0.0

    total_conceded = 0
    total_scored = 0
    for match in recent_matches:
        if match["team_h"] == opponent_id:
            total_conceded += match["team_a_score"]
            total_scored += match["team_h_score"]
        else:
            total_conceded += match["team_h_score"]
            total_scored += match["team_a_score"]

    conceded_per_match = total_conceded / len(recent_matches)
    scored_per_match = total_scored / len(recent_matches)
    vulnerability_score = conceded_per_match / 1.3

    return round(vulnerability_score, 2), round(scored_per_match, 2), round(conceded_per_match, 2)


def calculate_next_3_opponents_stats(team_id, fixtures_list, teams_df, window=5):
    if not team_id or not fixtures_list:
        return 0.0, 0.0, "None"

    team_fixtures = [
        f for f in fixtures_list
        if (f["team_h"] == team_id or f["team_a"] == team_id) and not f["finished"]
    ]
    team_fixtures = sorted(team_fixtures, key=lambda x: x.get("event", 999))
    next_3_fixtures = team_fixtures[:3]

    if not next_3_fixtures:
        return 0.0, 0.0, "No fixtures"

    opp_details = []
    total_opp_scored = 0
    total_opp_conceded = 0
    count = 0

    team_short_map = teams_df.set_index("id")["short_name"].to_dict()

    for f in next_3_fixtures:
        opp_id = f["team_a"] if f["team_h"] == team_id else f["team_h"]
        opp_name = team_short_map.get(opp_id, "Unknown")
        opp_details.append(opp_name)

        opp_finished = [
            fix for fix in fixtures_list
            if (fix["team_h"] == opp_id or fix["team_a"] == opp_id) and fix["finished"]
        ]
        opp_finished = sorted(opp_finished, key=lambda x: x.get("event", 0), reverse=True)[:window]

        if opp_finished:
            scored_sum = sum(
                (fix["team_h_score"] if fix["team_h"] == opp_id else fix["team_a_score"])
                for fix in opp_finished
            )
            conceded_sum = sum(
                (fix["team_a_score"] if fix["team_h"] == opp_id else fix["team_h_score"])
                for fix in opp_finished
            )
            total_opp_scored += scored_sum / len(opp_finished)
            total_opp_conceded += conceded_sum / len(opp_finished)
            count += 1

    avg_scored = round(total_opp_scored / count, 2) if count > 0 else 0.0
    avg_conceded = round(total_opp_conceded / count, 2) if count > 0 else 0.0
    opps_str = ", ".join(opp_details)

    return avg_scored, avg_conceded, opps_str


# --- FAVORABLE FIXTURE STACK CALCULATOR (UPDATED WITH SHORT CODES) ---
def check_favorable_fixture_stack(team_id, fixtures_list, teams_df, target_team_names=["Ipswich", "IPS", "Hull", "HUL", "Coventry", "COV", "Crystal Palace", "CRY"], horizon=4, threshold=2):
    if not team_id or not fixtures_list:
        return False, 0, ""

    team_fixtures = [
        f for f in fixtures_list
        if (f["team_h"] == team_id or f["team_a"] == team_id) and not f["finished"]
    ]
    team_fixtures = sorted(team_fixtures, key=lambda x: x.get("event", 999))
    next_fixtures = team_fixtures[:horizon]

    if not next_fixtures:
        return False, 0, ""

    team_short_map = teams_df.set_index("id")["short_name"].to_dict()
    
    matched_count = 0
    matched_opponents = []

    for f in next_fixtures:
        opp_id = f["team_a"] if f["team_h"] == team_id else f["team_h"]
        opp_name = team_short_map.get(opp_id, "")
        
        if any(target.lower() in opp_name.lower() for target in target_team_names):
            matched_count += 1
            matched_opponents.append(opp_name)

    is_stacked = matched_count >= threshold
    opps_str = ", ".join(matched_opponents) if matched_opponents else "None"
    
    return is_stacked, matched_count, opps_str


# --- 3. SIDEBAR CONTROL PANEL ---
st.sidebar.header("🔍 Filter Parameters")

scope_options = ["Season Totals", "Last X Gameweeks"]
data_scope = st.sidebar.radio("Data Scope", options=scope_options)

rolling_window_size = 5
if data_scope == "Last X Gameweeks":
    rolling_window_size = st.sidebar.slider(
        "Gameweek Window Size", min_value=1, max_value=10, value=5, step=1
    )
    target_sample_mins = rolling_window_size * 90.0
else:
    target_sample_mins = 450.0

positions = ["All"] + list(df_players["position"].unique())
selected_position = st.sidebar.selectbox("Position", positions)

min_p, max_p = (
    float(df_players["now_cost"].min()),
    float(df_players["now_cost"].max()),
)
max_price = st.sidebar.slider(
    "Max Price (£m)", min_value=min_p, max_value=max_p, value=max_p, step=0.1
)

st.sidebar.markdown("---")
st.sidebar.subheader("Fixture & Threshold Filters")

fixture_horizon = st.sidebar.slider(
    "Fixture Horizon (Next X Games)", min_value=1, max_value=10, value=5, step=1
)

team_fdr_map = {}
next_opponent_map = {}
team_short_name_map = teams_df.set_index("id")["short_name"].to_dict()

for team_id in teams_df["id"]:
    team_fixtures = [
        f for f in fixtures
        if (f["team_h"] == team_id or f["team_a"] == team_id) and not f["finished"]
    ]
    team_fixtures = sorted(team_fixtures, key=lambda x: x.get("event", 999))
    next_fixtures = team_fixtures[:fixture_horizon]

    if next_fixtures:
        difficulties = []
        for f in next_fixtures:
            if f["team_h"] == team_id:
                difficulties.append(f["team_h_difficulty"])
            else:
                difficulties.append(f["team_a_difficulty"])
        team_fdr_map[team_id] = round(sum(difficulties) / len(difficulties), 2)

        first_fixture = next_fixtures[0]
        if first_fixture["team_h"] == team_id:
            next_opponent_map[team_id] = first_fixture["team_a"]
        else:
            next_opponent_map[team_id] = first_fixture["team_h"]
    else:
        team_fdr_map[team_id] = 3.0
        next_opponent_map[team_id] = None

df_players["dynamic_fdr"] = df_players["team"].map(team_fdr_map)
df_players["upcoming_opponent_team_id"] = df_players["team"].map(next_opponent_map)
df_players["upcoming_opponent_name"] = df_players["upcoming_opponent_team_id"].map(team_short_name_map)

opp_stats_list = df_players.apply(
    lambda row: calculate_recent_opponent_stats(
        row.get("upcoming_opponent_team_id"), fixtures, rolling_window_size
    ),
    axis=1,
)
df_players["opponent_vulnerability"] = [x[0] for x in opp_stats_list]
df_players["opp_goals_scored_per_match"] = [x[1] for x in opp_stats_list]
df_players["opp_goals_conceded_per_match"] = [x[2] for x in opp_stats_list]

next_3_stats = df_players.apply(
    lambda row: calculate_next_3_opponents_stats(row.get("team"), fixtures, teams_df),
    axis=1,
)
df_players["next_3_opps"] = [x[2] for x in next_3_stats]
df_players["next_3_opp_goals_scored_avg"] = [x[0] for x in next_3_stats]
df_players["next_3_opp_goals_conceded_avg"] = [x[1] for x in next_3_stats]

# --- INTEGRATE FAVORABLE FIXTURE STACK INTO DATAFRAME ---
target_teams_list = ["Ipswich", "IPS", "Hull", "HUL", "Coventry", "COV", "Crystal Palace", "CRY"]
stack_stats = df_players.apply(
    lambda row: check_favorable_fixture_stack(row.get("team"), fixtures, teams_df, target_team_names=target_teams_list, horizon=4, threshold=2),
    axis=1,
)
df_players["has_fixture_stack"] = [x[0] for x in stack_stats]
df_players["stack_count"] = [x[1] for x in stack_stats]
df_players["stack_opponents"] = [x[2] for x in stack_stats]
df_players["Favorable Run Flag"] = df_players.apply(
    lambda r: f"🟢 {r['stack_count']} Target Games ({r['stack_opponents']})" if r["has_fixture_stack"] else "Standard",
    axis=1
)

# --- SIDEBAR TOGGLE FOR FIXTURE STACK ---
st.sidebar.markdown("---")
st.sidebar.subheader("🎯 Special Fixture Filters")
favorable_stack_only = st.sidebar.checkbox(
    "Target 2+ vs Ipswich/Hull/Coventry/Palace in Next 4", 
    value=False,
    help="Filters for players whose teams face at least 2 of these specified opponents in their next 4 fixtures."
)

max_fdr = st.sidebar.slider(
    f"Max Next {fixture_horizon} Fixture Difficulty (FDR)",
    min_value=1.0, max_value=5.0, value=5.0, step=0.1
)

leaky_defenses_only = st.sidebar.checkbox("🎯 Target Leaky Defenses Only (Vulnerability > 1.2)", value=False)
blunt_attacks_only = st.sidebar.checkbox("🛡️ Target Blunt Opponent Attacks Only (Opp. Goals Scored < 1.0)", value=False)
min_minutes = st.sidebar.number_input("Min Minutes Played", min_value=0, value=0, step=90)

metric_options = ["Total Accumulation", "Per 90 Rates"]
metric_mode = st.sidebar.radio("Filter Threshold Mode", options=metric_options)

st.sidebar.markdown("---")
if metric_mode == "Total Accumulation":
    min_influence = st.sidebar.number_input("Min Influence", min_value=0.0, value=0.0, step=10.0)
    min_threat = st.sidebar.number_input("Min Threat", min_value=0.0, value=0.0, step=10.0)
    min_creativity = st.sidebar.number_input("Min Creativity", min_value=0.0, value=0.0, step=10.0)
    min_xgi = st.sidebar.number_input("Min Expected Goal Involvements (xGI)", min_value=0.0, value=0.0, step=0.05)
    min_def_contrib = st.sidebar.number_input("Min Defensive Contributions", min_value=0, value=0, step=5)
    min_form = st.sidebar.number_input("Min Form", min_value=0.0, value=0.0, step=0.5)
    min_bonus = st.sidebar.number_input("Min Bonus Points", min_value=0, value=0)
    min_bps = st.sidebar.number_input("Min Total BPS", min_value=0, value=0)
else:
    min_influence = st.sidebar.number_input("Min Influence Per 90", min_value=0.0, value=0.0, step=5.0)
    min_threat = st.sidebar.number_input("Min Threat Per 90", min_value=0.0, value=0.0, step=5.0)
    min_creativity = st.sidebar.number_input("Min Creativity Per 90", min_value=0.0, value=0.0, step=5.0)
    min_xgi = st.sidebar.number_input("Min xGI Per 90", min_value=0.0, value=0.0, step=0.05)
    min_def_contrib = st.sidebar.number_input("Min Def Contrib Per 90", min_value=0.0, value=0.0, step=1.0)
    min_form = st.sidebar.number_input("Min Form", min_value=0.0, value=0.0, step=0.5)
    min_bonus = st.sidebar.number_input("Min Bonus Per 90", min_value=0.0, value=0.0, step=0.1)
    min_bps = st.sidebar.number_input("Min BPS Per 90", min_value=0.0, value=0.0, step=5.0)

numeric_cols = [
    "now_cost", "total_points", "influence", "threat", "creativity",
    "selected_by_percent", "form", "expected_goals", "expected_assists",
    "expected_goal_involvements", "minutes", "dynamic_fdr", "bps", "bonus",
    "clean_sheets", "defensive_contributions", "opponent_vulnerability",
    "opp_goals_scored_per_match", "opp_goals_conceded_per_match",
    "next_3_opp_goals_scored_avg", "next_3_opp_goals_conceded_avg"
]
for col in numeric_cols:
    if col in df_players.columns:
        df_players[col] = pd.to_numeric(df_players[col], errors="coerce").fillna(0)

if "form_status" not in df_players.columns:
    df_players["form_status"] = "Stable ➡️"
if "form_trend_delta" not in df_players.columns:
    df_players["form_trend_delta"] = 0.0

if data_scope == "Last X Gameweeks":
    with st.spinner(f"Fetching last {rolling_window_size} completed gameweeks data..."):
        ids_to_fetch = df_players[df_players["minutes"] > 0]["id"].tolist()
        rolling_df = fetch_rolling_data(ids_to_fetch, num_gameweeks=rolling_window_size)
        if not rolling_df.empty:
            df_players = df_players.merge(
                rolling_df, on="id", how="left", suffixes=("", "_rolling")
            )
            for col in [
                "minutes", "total_points", "expected_goals", "expected_assists",
                "expected_goal_involvements", "influence", "creativity", "threat",
                "bps", "bonus", "clean_sheets", "defensive_contributions", "form_trend_delta", "form_status"
            ]:
                if col + "_rolling" in df_players.columns:
                    df_players[col] = df_players[col + "_rolling"].fillna(0)

for c in ["minutes", "total_points", "expected_goal_involvements", "bps", "bonus", "clean_sheets", "influence", "threat", "creativity"]:
    if c in df_players.columns:
        df_players[c] = pd.to_numeric(df_players[c], errors="coerce").fillna(0)

def calc_per_90(row, col_name):
    return round((row[col_name] / row["minutes"]) * 90, 2) if row["minutes"] > 0 else 0.0

df_players["points_per_90"] = df_players.apply(lambda r: calc_per_90(r, "total_points"), axis=1)
df_players["bps_per_90"] = df_players.apply(lambda r: calc_per_90(r, "bps"), axis=1)
df_players["bonus_per_90"] = df_players.apply(lambda r: calc_per_90(r, "bonus"), axis=1)
df_players["influence_per_90"] = df_players.apply(lambda r: calc_per_90(r, "influence"), axis=1)
df_players["threat_per_90"] = df_players.apply(lambda r: calc_per_90(r, "threat"), axis=1)
df_players["creativity_per_90"] = df_players.apply(lambda r: calc_per_90(r, "creativity"), axis=1)
df_players["xgi_per_90"] = df_players.apply(lambda r: calc_per_90(r, "expected_goal_involvements"), axis=1)
df_players["def_contrib_per_90"] = df_players.apply(lambda r: calc_per_90(r, "defensive_contributions"), axis=1)


# --- PREDICTIVE MODEL CALCULATION ---
def calculate_predicted_points(row):
    minutes = float(row.get("minutes", 0) or 0)
    position = str(row.get("position", "") or "")

    if minutes <= 0:
        return 0.0

    sample_confidence = min(minutes / target_sample_mins, 1.0)
    if minutes < (target_sample_mins * 0.4):
        sample_confidence *= 0.85
    elif minutes < (target_sample_mins * 0.6):
        sample_confidence *= 0.92

    xgi_p90 = float(row.get("xgi_per_90", 0) or 0)

    if position in ("Forward", "Midfielder"):
        attacking_points = xgi_p90 * 4.0
    elif position == "Defender":
        attacking_points = xgi_p90 * 3.5
    else:
        attacking_points = xgi_p90 * 3.0

    attacking_points = min(attacking_points, 7.0)
    appearance_points = 1.0 + sample_confidence

    fdr = float(row.get("dynamic_fdr", 3.0) or 3.0)
    fixture_quality = max(0.0, min(1.0, (5.0 - fdr) / 4.0))

    opp_goals_scored = float(row.get("opp_goals_scored_per_match", 1.0) or 1.0) 

    if opp_goals_scored <= 0.8:
        attack_modifier = 1.20 
    elif opp_goals_scored >= 1.6:
        attack_modifier = 0.80 
    else:
        attack_modifier = 1.0

    clean_sheets = float(row.get("clean_sheets", 0) or 0)
    cs_momentum = 1.0 + (clean_sheets * 0.05)
    cs_momentum = max(1.0, min(1.40, cs_momentum))

    adjusted_fixture_quality = max(0.1, min(1.0, fixture_quality * attack_modifier))

    pos_upper = position.upper()
    if pos_upper in ["GK", "DEF", "GOALKEEPER", "DEFENDER"]:
        max_cs_points = 4.0
    elif pos_upper in ["MID", "MIDFIELDER"]:
        max_cs_points = 1.0
    else: 
        max_cs_points = 0.0

    clean_sheet_points = max_cs_points * adjusted_fixture_quality * cs_momentum

    bps_p90 = float(row.get("bps_per_90", 0) or 0)
    bonus_component = min(1.5, max(0.0, bps_p90 / 100.0))

    influence_p90 = float(row.get("influence_per_90", 0) or 0)
    influence_component = min(1.0, influence_p90 / 75.0)

    performance_component = attacking_points + clean_sheet_points + bonus_component + influence_component
    expected_points = appearance_points + performance_component * sample_confidence
    
    return round(max(0.0, min(expected_points, 15.0)), 2)

df_players["predicted_gw_points"] = df_players.apply(calculate_predicted_points, axis=1)

# --- 4. APPLY FILTERING ---
filtered_df = df_players.copy()

if selected_position != "All":
    filtered_df = filtered_df[filtered_df["position"] == selected_position]

filtered_df = filtered_df[filtered_df["now_cost"] <= max_price]
filtered_df = filtered_df[filtered_df["dynamic_fdr"] <= max_fdr]

if favorable_stack_only:
    filtered_df = filtered_df[filtered_df["has_fixture_stack"] == True]

if leaky_defenses_only:
    filtered_df = filtered_df[filtered_df["opponent_vulnerability"] > 1.2]
    
if blunt_attacks_only:
    filtered_df = filtered_df[filtered_df["opp_goals_scored_per_match"] < 1.0]

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
        filtered_df = filtered_df[filtered_df["expected_goal_involvements"] >= min_xgi]
    if min_def_contrib > 0:
        filtered_df = filtered_df[filtered_df["defensive_contributions"] >= min_def_contrib]
    if "bonus" in filtered_df.columns and min_bonus > 0:
        filtered_df = filtered_df[filtered_df["bonus"] >= min_bonus]
    if "bps" in filtered_df.columns and min_bps > 0:
        filtered_df = filtered_df[filtered_df["bps"] >= min_bps]
else:
    if min_influence > 0:
        filtered_df = filtered_df[filtered_df["influence_per_90"] >= min_influence]
    if min_threat > 0:
        filtered_df = filtered_df[filtered_df["threat_per_90"] >= min_threat]
    if min_creativity > 0:
        filtered_df = filtered_df[filtered_df["creativity_per_90"] >= min_creativity]
    if min_xgi > 0:
        filtered_df = filtered_df[filtered_df["xgi_per_90"] >= min_xgi]
    if min_def_contrib > 0:
        filtered_df = filtered_df[filtered_df["def_contrib_per_90"] >= min_def_contrib]
    if min_bonus > 0:
        filtered_df = filtered_df[filtered_df["bonus_per_90"] >= min_bonus]

filtered_df["Player"] = filtered_df["first_name"] + " " + filtered_df["second_name"]

# --- TOP KPI SUMMARY CARDS ---
if not filtered_df.empty:
    st.markdown("---")
    kpi1, kpi2, kpi3 = st.columns(3)

    top_scorer = filtered_df.sort_values(by="predicted_gw_points", ascending=False).iloc[0]
    kpi1.metric(
        "🔥 Top Predicted Scorer",
        f"{top_scorer['Player']} ({top_scorer['team_name']})",
        f"{top_scorer['predicted_gw_points']} pts",
    )

    budget_pool = filtered_df[filtered_df["now_cost"] <= 6.5]
    if not budget_pool.empty:
        best_budget = budget_pool.sort_values(by="predicted_gw_points", ascending=False).iloc[0]
        kpi2.metric(
            "💎 Top Budget Pick (≤ £6.5m)",
            f"{best_budget['Player']} (£{best_budget['now_cost']}m)",
            f"{best_budget['predicted_gw_points']} pts",
        )
    else:
        kpi2.metric("💎 Top Budget Pick", "None in filter", "0 pts")

    if "opponent_vulnerability" in filtered_df.columns:
        softest_def = filtered_df.sort_values(by="opponent_vulnerability", ascending=False).iloc[0]
        opp_name = softest_def["upcoming_opponent_name"] if pd.notna(softest_def["upcoming_opponent_name"]) else "Unknown"
        kpi3.metric(
            "🎯 Best Fixture Target",
            f"{softest_def['Player']} vs {opp_name}",
            f"Def. Vulnerability: {softest_def['opponent_vulnerability']}",
        )
    st.markdown("---")

desired_display_columns = [
    "Player", "team_name", "position", "now_cost", "predicted_gw_points",
    "Favorable Run Flag", "form_status", "form_trend_delta", "opponent_vulnerability",
    "opp_goals_scored_per_match", "opp_goals_conceded_per_match", "dynamic_fdr",
    "form", "total_points", "points_per_90", "expected_goal_involvements",
    "clean_sheets", "defensive_contributions", "threat", "creativity", "influence", "bonus",
    "minutes", "selected_by_percent",
]

display_columns = [col for col in desired_display_columns if col in filtered_df.columns]
filtered_df = filtered_df.sort_values(by=["predicted_gw_points", "form"], ascending=[False, False]).reset_index(drop=True)

# --- 5. RENDER RESULTS ---
st.subheader(f"Matching Shortlist ({len(filtered_df)} players found)")

if not filtered_df.empty:
    renamed_df = filtered_df[display_columns].rename(
        columns={
            "team_name": "Team",
            "position": "Pos",
            "now_cost": "Price (£m)",
            "predicted_gw_points": "Predicted GW Pts",
            "Favorable Run Flag": "Fixture Stack Run",
            "form_status": "Form Trend",
            "form_trend_delta": "Trend Delta (+/-)",
            "opponent_vulnerability": "Opp. Vulnerability",
            "opp_goals_scored_per_match": "Opp. Goals Scored (Last 5)",
            "opp_goals_conceded_per_match": "Opp. Goals Conceded (Last 5)",
            "dynamic_fdr": f"Next {fixture_horizon} FDR",
            "form": "Form",
            "total_points": "Points",
            "points_per_90": "Pts/90",
            "expected_goal_involvements": "xGI",
            "clean_sheets": "Clean Sheets",
            "defensive_contributions": "Def Contrib",
            "threat": "Threat",
            "creativity": "Creativity",
            "influence": "Influence",
            "bonus": "Bonus",
            "minutes": "Mins",
            "selected_by_percent": "Ownership %",
        }
    )

    event = st.dataframe(
        renamed_df,
        use_container_width=True,
        on_select="rerun",
        selection_mode="multi-row",
    )

    selected_indices = event.selection.get("rows", [])
    if selected_indices:
        st.markdown("---")
        st.subheader("⚔️ Head-to-Head Player Comparison")
        comparison_df = renamed_df.iloc[selected_indices]
        st.dataframe(comparison_df, use_container_width=True)

    # --- NEXT 3 OPPONENTS TABLE ---
    st.markdown("---")
    st.subheader("📅 Next 3 Opponents Scoring & Conceding Averages")
    st.markdown("This table breaks down the average goals scored and conceded by each player's **next 3 upcoming opponents** (based on their recent form).")

    next_3_display_cols = [
        "Player", "team_name", "position", "now_cost", 
        "next_3_opps", "next_3_opp_goals_scored_avg", "next_3_opp_goals_conceded_avg", "predicted_gw_points"
    ]
    available_next_3_cols = [col for col in next_3_display_cols if col in filtered_df.columns]

    renamed_next_3_df = filtered_df[available_next_3_cols].rename(
        columns={
            "team_name": "Team",
            "position": "Pos",
            "now_cost": "Price (£m)",
            "next_3_opps": "Next 3 Opponents",
            "next_3_opp_goals_scored_avg": "Next 3 Opp. Avg Goals Scored",
            "next_3_opp_goals_conceded_avg": "Next 3 Opp. Avg Goals Conceded",
            "predicted_gw_points": "Predicted GW Pts"
        }
    )
    st.dataframe(renamed_next_3_df, use_container_width=True)

else:
    st.warning("No players match this exact combination of filters. Try loosening your thresholds.")

# --- YOUR TEAM INTEGRATION & TRANSFER SUGGESTIONS ---
st.sidebar.markdown("---")
st.sidebar.subheader("🎯 Your Team Integration")
manager_id = st.sidebar.text_input("Enter your FPL Manager ID:")

if manager_id and df_players is not None:
    try:
        my_player_ids = fetch_user_team(int(manager_id), current_gw)

        if my_player_ids:
            my_squad_df = df_players[df_players["id"].isin(my_player_ids)]

            st.markdown("---")
            st.subheader("📋 Your Loaded Squad Audit")
            st.dataframe(
                my_squad_df[[
                    "Player", "team_name", "position", "now_cost",
                    "predicted_gw_points", "opponent_vulnerability",
                    "opp_goals_scored_per_match"
                ]],
                use_container_width=True,
            )

            st.subheader("💡 Recommended Transfer Targets")
            weakest_starter = my_squad_df.sort_values(by="predicted_gw_points", ascending=True).iloc[0]
            
            # Additional logic can follow here
    except Exception as e:
        st.sidebar.error("Could not fetch team data. Check your Manager ID.")
