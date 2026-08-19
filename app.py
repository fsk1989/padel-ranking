import streamlit as st
from sqlalchemy import text

st.set_page_config(
    page_title="MPT Padel Ranking",
    page_icon="🎾",
    layout="centered"
)

conn = st.connection("supabase", type="sql")

K_FACTOR = 32


def get_players():
    return conn.query(
        """
        SELECT player_id, name, elo, matches_played, wins, losses
        FROM players
        ORDER BY elo DESC, name ASC
        """,
        ttl=0
    )


def expected_score(rating_a, rating_b):
    return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))


def register_match(
    players,
    t1p1,
    t1p2,
    t2p1,
    t2p2,
    winner
):
    selected = [t1p1, t1p2, t2p1, t2p2]

    if len(set(selected)) != 4:
        st.error("De fire spillere skal være forskellige.")
        return

    selected_players = players[
        players["name"].isin(selected)
    ].copy()

    data = {
        row["name"]: row
        for _, row in selected_players.iterrows()
    }

    team1_rating = (
        int(data[t1p1]["elo"]) +
        int(data[t1p2]["elo"])
    ) / 2

    team2_rating = (
        int(data[t2p1]["elo"]) +
        int(data[t2p2]["elo"])
    ) / 2

    expected_team1 = expected_score(
        team1_rating,
        team2_rating
    )

    actual_team1 = 1 if winner == 1 else 0

    team1_change = round(
        K_FACTOR *
        (actual_team1 - expected_team1)
    )

    team2_change = -team1_change

    ids = {
        name: int(data[name]["player_id"])
        for name in selected
    }

    with conn.session as session:

        result = session.execute(
            text("""
                INSERT INTO matches (
                    team1_player1,
                    team1_player2,
                    team2_player1,
                    team2_player2,
                    winner
                )
                VALUES (
                    :t1p1,
                    :t1p2,
                    :t2p1,
                    :t2p2,
                    :winner
                )
                RETURNING match_id
            """),
            {
                "t1p1": ids[t1p1],
                "t1p2": ids[t1p2],
                "t2p1": ids[t2p1],
                "t2p2": ids[t2p2],
                "winner": winner
            }
        )

        match_id = result.scalar_one()

        changes = {
            t1p1: team1_change,
            t1p2: team1_change,
            t2p1: team2_change,
            t2p2: team2_change
        }

        for name, change in changes.items():

            old_elo = int(data[name]["elo"])
            new_elo = old_elo + change

            won = (
                winner == 1 and name in [t1p1, t1p2]
            ) or (
                winner == 2 and name in [t2p1, t2p2]
            )

            session.execute(
                text("""
                    UPDATE players
                    SET
                        elo = :new_elo,
                        matches_played = matches_played + 1,
                        wins = wins + :win,
                        losses = losses + :loss
                    WHERE player_id = :player_id
                """),
                {
                    "new_elo": new_elo,
                    "win": 1 if won else 0,
                    "loss": 0 if won else 1,
                    "player_id": ids[name]
                }
            )

            session.execute(
                text("""
                    INSERT INTO elo_history (
                        match_id,
                        player_id,
                        elo_before,
                        elo_change,
                        elo_after
                    )
                    VALUES (
                        :match_id,
                        :player_id,
                        :elo_before,
                        :elo_change,
                        :elo_after
                    )
                """),
                {
                    "match_id": match_id,
                    "player_id": ids[name],
                    "elo_before": old_elo,
                    "elo_change": change,
                    "elo_after": new_elo
                }
            )

        session.commit()

    if winner == 1:
        winners = f"{t1p1} & {t1p2}"
    else:
        winners = f"{t2p1} & {t2p2}"

    st.success(f"🏆 {winners} vandt!")

    st.write("### ELO-ændringer")

    st.write(
        f"{t1p1}: "
        f"{int(data[t1p1]['elo'])} → "
        f"{int(data[t1p1]['elo']) + team1_change} "
        f"({team1_change:+d})"
    )

    st.write(
        f"{t1p2}: "
        f"{int(data[t1p2]['elo'])} → "
        f"{int(data[t1p2]['elo']) + team1_change} "
        f"({team1_change:+d})"
    )

    st.write(
        f"{t2p1}: "
        f"{int(data[t2p1]['elo'])} → "
        f"{int(data[t2p1]['elo']) + team2_change} "
        f"({team2_change:+d})"
    )

    st.write(
        f"{t2p2}: "
        f"{int(data[t2p2]['elo'])} → "
        f"{int(data[t2p2]['elo']) + team2_change} "
        f"({team2_change:+d})"
    )


# -----------------------------
# MENU
# -----------------------------

st.sidebar.title("🎾 MPT Padel")

page = st.sidebar.radio(
    "Menu",
    [
        "🏆 Rangliste",
        "➕ Registrer kamp",
        "📋 Kamphistorik"
    ]
)


# =========================================================
# RANGLISTE
# =========================================================

if page == "🏆 Rangliste":

    st.title("🎾 MPT Padel Ranking")
    st.subheader("🏆 ELO rangliste")

    players = get_players()

    if players.empty:
        st.info("Der er endnu ingen spillere.")

    else:
        table = players.copy()

        table["Placering"] = range(1, len(table) + 1)

        table["Win %"] = table.apply(
            lambda row: round(
                row["wins"] /
                row["matches_played"] * 100,
                1
            )
            if row["matches_played"] > 0
            else 0,
            axis=1
        )

        table = table.rename(
            columns={
                "name": "Spiller",
                "elo": "ELO",
                "matches_played": "Kampe",
                "wins": "Sejre",
                "losses": "Nederlag"
            }
        )

        st.dataframe(
            table[
                [
                    "Placering",
                    "Spiller",
                    "ELO",
                    "Kampe",
                    "Sejre",
                    "Nederlag",
                    "Win %"
                ]
            ],
            hide_index=True,
            use_container_width=True
        )


# =========================================================
# REGISTRER KAMP
# =========================================================

elif page == "➕ Registrer kamp":

    st.title("➕ Registrer kamp")

    players = get_players()
    player_names = players["name"].tolist()

    if len(player_names) < 4:
        st.warning("Der skal være mindst 4 spillere.")
        st.stop()

    st.subheader("Hold 1")

    t1p1 = st.selectbox(
        "Spiller 1",
        player_names,
        key="t1p1"
    )

    t1p2 = st.selectbox(
        "Spiller 2",
        player_names,
        index=1,
        key="t1p2"
    )

    st.subheader("Hold 2")

    t2p1 = st.selectbox(
        "Spiller 1 ",
        player_names,
        index=2,
        key="t2p1"
    )

    t2p2 = st.selectbox(
        "Spiller 2 ",
        player_names,
        index=3,
        key="t2p2"
    )

    selected = [t1p1, t1p2, t2p1, t2p2]

    if len(set(selected)) != 4:
        st.warning(
            "Vælg fire forskellige spillere."
        )
        st.stop()

    data = {
        row["name"]: row
        for _, row in players[
            players["name"].isin(selected)
        ].iterrows()
    }

    team1_rating = round(
        (
            int(data[t1p1]["elo"]) +
            int(data[t1p2]["elo"])
        ) / 2
    )

    team2_rating = round(
        (
            int(data[t2p1]["elo"]) +
            int(data[t2p2]["elo"])
        ) / 2
    )

    chance1 = expected_score(
        team1_rating,
        team2_rating
    )

    chance2 = 1 - chance1

    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### Hold 1")
        st.write(f"**{t1p1}**")
        st.write(f"**{t1p2}**")
        st.caption(
            f"Gennemsnitlig ELO: {team1_rating}"
        )
        st.metric(
            "Forventet vinderchance",
            f"{chance1 * 100:.0f}%"
        )

    with col2:
        st.markdown("### Hold 2")
        st.write(f"**{t2p1}**")
        st.write(f"**{t2p2}**")
        st.caption(
            f"Gennemsnitlig ELO: {team2_rating}"
        )
        st.metric(
            "Forventet vinderchance",
            f"{chance2 * 100:.0f}%"
        )

    st.divider()

    st.subheader("Hvem vandt?")

    button1, button2 = st.columns(2)

    with button1:
        if st.button(
            "🏆 Hold 1 vandt",
            type="primary",
            use_container_width=True
        ):
            register_match(
                players,
                t1p1,
                t1p2,
                t2p1,
                t2p2,
                1
            )

    with button2:
        if st.button(
            "🏆 Hold 2 vandt",
            use_container_width=True
        ):
            register_match(
                players,
                t1p1,
                t1p2,
                t2p1,
                t2p2,
                2
            )


# =========================================================
# KAMPHISTORIK
# =========================================================

elif page == "📋 Kamphistorik":

    st.title("📋 Kamphistorik")

    matches = conn.query(
        """
        SELECT
            m.match_id,
            m.match_date,

            p1.name AS team1_player1,
            p2.name AS team1_player2,
            p3.name AS team2_player1,
            p4.name AS team2_player2,

            m.winner

        FROM matches m

        JOIN players p1
            ON m.team1_player1 = p1.player_id

        JOIN players p2
            ON m.team1_player2 = p2.player_id

        JOIN players p3
            ON m.team2_player1 = p3.player_id

        JOIN players p4
            ON m.team2_player2 = p4.player_id

        ORDER BY m.match_date DESC
        """,
        ttl=0
    )

    if matches.empty:

        st.info(
            "Der er endnu ikke registreret nogen kampe."
        )

    else:

        for _, match in matches.iterrows():

            team1 = (
                f"{match['team1_player1']} & "
                f"{match['team1_player2']}"
            )

            team2 = (
                f"{match['team2_player1']} & "
                f"{match['team2_player2']}"
            )

            if match["winner"] == 1:
                winner_text = f"🏆 {team1}"
            else:
                winner_text = f"🏆 {team2}"

            st.markdown(
                f"**{team1}**  vs  **{team2}**"
            )

            st.write(
                f"Vinder: **{winner_text}**"
            )

            st.caption(
                match["match_date"].strftime(
                    "%d-%m-%Y %H:%M"
                )
            )

            st.divider()
