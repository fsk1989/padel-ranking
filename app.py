import streamlit as st
from sqlalchemy import text

st.set_page_config(
    page_title="Middelfart Padelteam",
    page_icon="🎾",
    layout="centered"
)

# =========================================================
# LOGIN
# =========================================================

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:

    st.title("🎾 Middelfart Padelteam - Rangliste")
    st.write("Log ind for at få adgang til ranglisten.")

    password = st.text_input(
        "Kodeord",
        type="password"
    )

    if st.button(
        "Log ind",
        type="primary",
        use_container_width=True
    ):
        if password == st.secrets["APP_PASSWORD"]:
            st.session_state.logged_in = True
            st.rerun()
        else:
            st.error("Forkert kodeord")

    st.stop()


# =========================================================
# DATABASE
# =========================================================

conn = st.connection("supabase", type="sql")

K_FACTOR = 32
START_ELO = 1500


# =========================================================
# HENT SPILLERE
# =========================================================

def get_players():
    return conn.query(
        """
        SELECT
            player_id,
            name,
            elo,
            matches_played,
            wins,
            losses
        FROM players
        ORDER BY elo DESC, name ASC
        """,
        ttl=0
    )


# =========================================================
# ELO
# =========================================================

def expected_score(rating_a, rating_b):
    return 1 / (
        1 + 10 ** ((rating_b - rating_a) / 400)
    )


# =========================================================
# GENBEREGN HELE RANGLISTEN
# =========================================================

def recalculate_ranking(session):

    # Fjern den eksisterende ELO-historik
    session.execute(
        text("""
            DELETE FROM elo_history
        """)
    )

    # Nulstil alle spillere
    session.execute(
        text("""
            UPDATE players
            SET
                elo = :start_elo,
                matches_played = 0,
                wins = 0,
                losses = 0
        """),
        {
            "start_elo": START_ELO
        }
    )

    # Hent alle spillere
    player_rows = session.execute(
        text("""
            SELECT player_id
            FROM players
        """)
    ).mappings().all()

    ratings = {
        int(row["player_id"]): START_ELO
        for row in player_rows
    }

    # Hent alle kampe i den rækkefølge de blev spillet
    matches = session.execute(
        text("""
            SELECT
                match_id,
                team1_player1,
                team1_player2,
                team2_player1,
                team2_player2,
                winner
            FROM matches
            ORDER BY match_date ASC, match_id ASC
        """)
    ).mappings().all()

    for match in matches:

        match_id = int(match["match_id"])

        t1p1 = int(match["team1_player1"])
        t1p2 = int(match["team1_player2"])
        t2p1 = int(match["team2_player1"])
        t2p2 = int(match["team2_player2"])

        winner = int(match["winner"])

        # Holdenes gennemsnitlige ELO
        team1_rating = (
            ratings[t1p1] +
            ratings[t1p2]
        ) / 2

        team2_rating = (
            ratings[t2p1] +
            ratings[t2p2]
        ) / 2

        # Forventet vinderchance
        expected_team1 = expected_score(
            team1_rating,
            team2_rating
        )

        actual_team1 = (
            1 if winner == 1 else 0
        )

        # ELO-ændring
        team1_change = round(
            K_FACTOR *
            (
                actual_team1 -
                expected_team1
            )
        )

        team2_change = -team1_change

        changes = {
            t1p1: team1_change,
            t1p2: team1_change,
            t2p1: team2_change,
            t2p2: team2_change
        }

        # Opdater alle fire spillere
        for player_id, change in changes.items():

            old_elo = ratings[player_id]
            new_elo = old_elo + change

            is_team1 = (
                player_id in [t1p1, t1p2]
            )

            won = (
                winner == 1 and is_team1
            ) or (
                winner == 2 and not is_team1
            )

            session.execute(
                text("""
                    UPDATE players
                    SET
                        elo = :new_elo,
                        matches_played =
                            matches_played + 1,
                        wins =
                            wins + :win,
                        losses =
                            losses + :loss
                    WHERE player_id = :player_id
                """),
                {
                    "new_elo": new_elo,
                    "win": 1 if won else 0,
                    "loss": 0 if won else 1,
                    "player_id": player_id
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
                    "player_id": player_id,
                    "elo_before": old_elo,
                    "elo_change": change,
                    "elo_after": new_elo
                }
            )

            ratings[player_id] = new_elo


# =========================================================
# REGISTRER KAMP
# =========================================================

def register_match(
    players,
    t1p1,
    t1p2,
    t2p1,
    t2p2,
    winner
):

    selected = [
        t1p1,
        t1p2,
        t2p1,
        t2p2
    ]

    if len(set(selected)) != 4:
        st.error(
            "De fire spillere skal være forskellige."
        )
        return

    selected_players = players[
        players["name"].isin(selected)
    ].copy()

    data = {
        row["name"]: row
        for _, row
        in selected_players.iterrows()
    }

    ids = {
        name: int(
            data[name]["player_id"]
        )
        for name in selected
    }

    with conn.session as session:

        session.execute(
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
            """),
            {
                "t1p1": ids[t1p1],
                "t1p2": ids[t1p2],
                "t2p1": ids[t2p1],
                "t2p2": ids[t2p2],
                "winner": winner
            }
        )

        # Beregn hele ranglisten på ny
        recalculate_ranking(session)

        session.commit()

    st.success(
        "🏆 Kampen er registreret!"
    )

    st.rerun()


# =========================================================
# MENU
# =========================================================

st.sidebar.title(
    "🎾 Middelfart Padelteam"
)

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

    st.title(
        "🎾 Middelfart Padelteam"
    )

    st.subheader(
        "🏆 Rangliste"
    )

    players = get_players()

    if players.empty:

        st.info(
            "Der er endnu ingen spillere."
        )

    else:

        table = players.copy()

        table["Placering"] = range(
            1,
            len(table) + 1
        )

        table["Win %"] = table.apply(
            lambda row: round(
                row["wins"]
                / row["matches_played"]
                * 100,
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

    st.title(
        "➕ Registrer kamp"
    )

    players = get_players()

    player_names = (
        players["name"]
        .tolist()
    )

    if len(player_names) < 4:

        st.warning(
            "Der skal være mindst 4 spillere."
        )

        st.stop()

    st.subheader(
        "Hold 1"
    )

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

    st.subheader(
        "Hold 2"
    )

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

    selected = [
        t1p1,
        t1p2,
        t2p1,
        t2p2
    ]

    if len(set(selected)) != 4:

        st.warning(
            "Vælg fire forskellige spillere."
        )

        st.stop()

    data = {
        row["name"]: row
        for _, row in players[
            players["name"].isin(
                selected
            )
        ].iterrows()
    }

    team1_rating = round(
        (
            int(
                data[t1p1]["elo"]
            )
            +
            int(
                data[t1p2]["elo"]
            )
        ) / 2
    )

    team2_rating = round(
        (
            int(
                data[t2p1]["elo"]
            )
            +
            int(
                data[t2p2]["elo"]
            )
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

        st.markdown(
            "### Hold 1"
        )

        st.write(
            f"**{t1p1}**"
        )

        st.write(
            f"**{t1p2}**"
        )

        st.caption(
            f"Gennemsnitlig ELO: "
            f"{team1_rating}"
        )

        st.metric(
            "Forventet vinderchance",
            f"{chance1 * 100:.0f}%"
        )

    with col2:

        st.markdown(
            "### Hold 2"
        )

        st.write(
            f"**{t2p1}**"
        )

        st.write(
            f"**{t2p2}**"
        )

        st.caption(
            f"Gennemsnitlig ELO: "
            f"{team2_rating}"
        )

        st.metric(
            "Forventet vinderchance",
            f"{chance2 * 100:.0f}%"
        )

    st.divider()

    st.subheader(
        "Hvem vandt?"
    )

    button1, button2 = (
        st.columns(2)
    )

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

    st.title(
        "📋 Kamphistorik"
    )

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
            ON m.team1_player1 =
               p1.player_id

        JOIN players p2
            ON m.team1_player2 =
               p2.player_id

        JOIN players p3
            ON m.team2_player1 =
               p3.player_id

        JOIN players p4
            ON m.team2_player2 =
               p4.player_id

        ORDER BY
            m.match_date DESC,
            m.match_id DESC
        """,
        ttl=0
    )

    if matches.empty:

        st.info(
            "Der er endnu ikke registreret nogen kampe."
        )

    else:

        for _, match in matches.iterrows():

            match_id = int(
                match["match_id"]
            )

            winner = int(
                match["winner"]
            )

            team1 = (
                f"{match['team1_player1']} & "
                f"{match['team1_player2']}"
            )

            team2 = (
                f"{match['team2_player1']} & "
                f"{match['team2_player2']}"
            )

            if winner == 1:
                winner_text = team1
            else:
                winner_text = team2

            st.markdown(
                f"**{team1}**  vs  "
                f"**{team2}**"
            )

            st.write(
                f"🏆 Vinder: "
                f"**{winner_text}**"
            )

            st.caption(
                match[
                    "match_date"
                ].strftime(
                    "%d-%m-%Y %H:%M"
                )
            )

            col1, col2 = (
                st.columns(2)
            )

            # ---------------------------------
            # RET VINDER
            # ---------------------------------

            with col1:

                if winner == 1:
                    new_winner = 2
                    new_winner_text = team2
                else:
                    new_winner = 1
                    new_winner_text = team1

                if st.button(
                    "✏️ Ret vinder",
                    key=f"edit_{match_id}",
                    use_container_width=True
                ):

                    st.session_state[
                        "edit_match"
                    ] = match_id

            # ---------------------------------
            # SLET KAMP
            # ---------------------------------

            with col2:

                if st.button(
                    "🗑️ Slet kamp",
                    key=f"delete_{match_id}",
                    use_container_width=True
                ):

                    st.session_state[
                        "delete_match"
                    ] = match_id

            # ---------------------------------
            # BEKRÆFT RETTELSE
            # ---------------------------------

            if (
                st.session_state.get(
                    "edit_match"
                )
                == match_id
            ):

                st.warning(
                    f"Skift vinder til "
                    f"{new_winner_text}?"
                )

                yes, no = (
                    st.columns(2)
                )

                with yes:

                    if st.button(
                        "Ja, ret vinderen",
                        key=(
                            f"confirm_edit_"
                            f"{match_id}"
                        ),
                        type="primary",
                        use_container_width=True
                    ):

                        with conn.session as session:

                            session.execute(
                                text("""
                                    UPDATE matches
                                    SET winner = :winner
                                    WHERE match_id =
                                          :match_id
                                """),
                                {
                                    "winner":
                                        new_winner,
                                    "match_id":
                                        match_id
                                }
                            )

                            recalculate_ranking(
                                session
                            )

                            session.commit()

                        st.session_state.pop(
                            "edit_match",
                            None
                        )

                        st.success(
                            "Vinderen er rettet."
                        )

                        st.rerun()

                with no:

                    if st.button(
                        "Annuller",
                        key=(
                            f"cancel_edit_"
                            f"{match_id}"
                        ),
                        use_container_width=True
                    ):

                        st.session_state.pop(
                            "edit_match",
                            None
                        )

                        st.rerun()

            # ---------------------------------
            # BEKRÆFT SLETNING
            # ---------------------------------

            if (
                st.session_state.get(
                    "delete_match"
                )
                == match_id
            ):

                st.warning(
                    "Er du sikker på, at "
                    "kampen skal slettes?"
                )

                yes, no = (
                    st.columns(2)
                )

                with yes:

                    if st.button(
                        "Ja, slet kampen",
                        key=(
                            f"confirm_delete_"
                            f"{match_id}"
                        ),
                        type="primary",
                        use_container_width=True
                    ):

                        with conn.session as session:

                            # Fjern ELO-historikken
                            # for kampen først
                            session.execute(
                                text("""
                                    DELETE FROM
                                        elo_history
                                    WHERE match_id =
                                          :match_id
                                """),
                                {
                                    "match_id":
                                        match_id
                                }
                            )

                            # Slet selve kampen
                            session.execute(
                                text("""
                                    DELETE FROM matches
                                    WHERE match_id =
                                          :match_id
                                """),
                                {
                                    "match_id":
                                        match_id
                                }
                            )

                            # Genberegn alt
                            recalculate_ranking(
                                session
                            )

                            session.commit()

                        st.session_state.pop(
                            "delete_match",
                            None
                        )

                        st.success(
                            "Kampen er slettet."
                        )

                        st.rerun()

                with no:

                    if st.button(
                        "Annuller",
                        key=(
                            f"cancel_delete_"
                            f"{match_id}"
                        ),
                        use_container_width=True
                    ):

                        st.session_state.pop(
                            "delete_match",
                            None
                        )

                        st.rerun()

            st.divider()
