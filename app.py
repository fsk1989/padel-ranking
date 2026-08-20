import streamlit as st
from sqlalchemy import text

st.set_page_config(
    page_title="Middelfart Padelteam",
    page_icon="🎾",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# =========================================================
# MOBIL CSS
# =========================================================

st.markdown(
    """
    <style>
    .block-container {
        max-width: 720px;
        padding-top: 3.5rem;
        padding-left: 0.9rem;
        padding-right: 0.9rem;
        padding-bottom: 2rem;
    }

    h1 {
        font-size: 1.9rem !important;
        margin-bottom: 0.4rem !important;
    }

    h2, h3 {
        margin-top: 0.8rem !important;
    }

    div[data-testid="stButton"] > button {
        min-height: 52px;
        border-radius: 12px;
        font-size: 1rem;
        font-weight: 600;
    }

    div[data-baseweb="select"] > div {
        min-height: 50px;
        border-radius: 10px;
    }

    div[data-testid="stTextInput"] input {
        min-height: 50px;
        font-size: 16px !important;
    }

    .player-card {
        padding: 14px 16px;
        border: 1px solid rgba(128, 128, 128, 0.25);
        border-radius: 14px;
        margin-bottom: 10px;
    }

    .rank-number {
        font-size: 1.25rem;
        font-weight: 700;
        margin-right: 8px;
    }

    .player-name {
        font-size: 1.08rem;
        font-weight: 700;
    }

    .player-stats {
        margin-top: 4px;
        opacity: 0.75;
        font-size: 0.93rem;
    }

    .match-card {
        padding: 14px 16px;
        border: 1px solid rgba(128, 128, 128, 0.25);
        border-radius: 14px;
        margin-bottom: 10px;
    }

    @media (max-width: 600px) {
        .block-container {
            padding-left: 0.75rem;
            padding-right: 0.75rem;
        }

        h1 {
            font-size: 1.6rem !important;
        }
    }
    </style>
    """,
    unsafe_allow_html=True
)

# =========================================================
# LOGIN
# =========================================================

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:

    st.title("🎾 Middelfart Padelteam")
    st.subheader("Rangliste")

    password = st.text_input(
        "Kodeord",
        type="password",
        placeholder="Indtast kodeord"
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
# DATABASE-FUNKTIONER
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


def expected_score(rating_a, rating_b):
    return 1 / (
        1 + 10 ** ((rating_b - rating_a) / 400)
    )


def recalculate_ranking(session):

    session.execute(
        text("DELETE FROM elo_history")
    )

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
            ORDER BY
                match_date ASC,
                match_id ASC
        """)
    ).mappings().all()

    for match in matches:

        match_id = int(match["match_id"])

        t1p1 = int(match["team1_player1"])
        t1p2 = int(match["team1_player2"])
        t2p1 = int(match["team2_player1"])
        t2p2 = int(match["team2_player2"])

        winner = int(match["winner"])

        team1_rating = (
            ratings[t1p1] +
            ratings[t1p2]
        ) / 2

        team2_rating = (
            ratings[t2p1] +
            ratings[t2p2]
        ) / 2

        expected_team1 = expected_score(
            team1_rating,
            team2_rating
        )

        actual_team1 = (
            1 if winner == 1 else 0
        )

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


def create_player(name):

    clean_name = name.strip()

    if clean_name == "":
        return False, "Du skal indtaste et navn."

    with conn.session as session:

        existing_player = session.execute(
            text("""
                SELECT player_id
                FROM players
                WHERE LOWER(TRIM(name)) =
                      LOWER(:name)
                LIMIT 1
            """),
            {
                "name": clean_name
            }
        ).first()

        if existing_player:
            return False, "Spilleren findes allerede."

        session.execute(
            text("""
                INSERT INTO players (
                    name,
                    elo,
                    matches_played,
                    wins,
                    losses
                )
                VALUES (
                    :name,
                    :elo,
                    0,
                    0,
                    0
                )
            """),
            {
                "name": clean_name,
                "elo": START_ELO
            }
        )

        session.commit()

    return True, f"{clean_name} er oprettet."


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

        recalculate_ranking(session)
        session.commit()

    st.session_state["message"] = (
        "🏆 Kampen er registreret!"
    )

    st.rerun()


# =========================================================
# TOP-NAVIGATION
# =========================================================

if "page" not in st.session_state:
    st.session_state.page = "Rangliste"

nav1, nav2 = st.columns(2)

with nav1:
    if st.button(
        "🏆 Rangliste",
        use_container_width=True
    ):
        st.session_state.page = "Rangliste"
        st.rerun()

with nav2:
    if st.button(
        "🎾 Kamp",
        use_container_width=True
    ):
        st.session_state.page = "Kamp"
        st.rerun()

nav3, nav4 = st.columns(2)

with nav3:
    if st.button(
        "📋 Historik",
        use_container_width=True
    ):
        st.session_state.page = "Historik"
        st.rerun()

with nav4:
    if st.button(
        "👤 Spillere",
        use_container_width=True
    ):
        st.session_state.page = "Spillere"
        st.rerun()

st.divider()

page = st.session_state.page


# =========================================================
# EVENTUEL BESKED
# =========================================================

if "message" in st.session_state:

    st.success(
        st.session_state.pop("message")
    )


# =========================================================
# RANGLISTE
# =========================================================

if page == "Rangliste":

    st.title("🎾 Middelfart Padelteam")
    st.subheader("Rangliste")

    players = get_players()

    if players.empty:
        st.info(
            "Der er endnu ingen spillere."
        )

    else:

        for index, row in players.iterrows():

            position = index + 1

            if position == 1:
                medal = "🥇"
            elif position == 2:
                medal = "🥈"
            elif position == 3:
                medal = "🥉"
            else:
                medal = f"{position}."

            matches_played = int(
                row["matches_played"]
            )

            wins = int(
                row["wins"]
            )

            losses = int(
                row["losses"]
            )

            if matches_played > 0:
                win_pct = round(
                    wins /
                    matches_played *
                    100
                )
            else:
                win_pct = 0

            st.markdown(
                f"""
                <div class="player-card">
                    <div>
                        <span class="rank-number">
                            {medal}
                        </span>
                        <span class="player-name">
                            {row["name"]}
                        </span>
                    </div>
                    <div class="player-stats">
                        ELO {int(row["elo"])}
                        · {matches_played} kampe
                        · {wins} sejre
                        · {losses} nederlag
                        · {win_pct}%
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )


# =========================================================
# KAMP
# =========================================================

elif page == "Kamp":

    st.title("🎾 Registrer kamp")

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

    st.subheader("Hold 1")

    t1p1 = st.selectbox(
        "Spiller 1",
        player_names,
        key="mobile_t1p1"
    )

    t1p2 = st.selectbox(
        "Spiller 2",
        player_names,
        index=1,
        key="mobile_t1p2"
    )

    st.markdown("### VS")

    st.subheader("Hold 2")

    t2p1 = st.selectbox(
        "Spiller 1 ",
        player_names,
        index=2,
        key="mobile_t2p1"
    )

    t2p2 = st.selectbox(
        "Spiller 2 ",
        player_names,
        index=3,
        key="mobile_t2p2"
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

    st.divider()

    st.subheader("Hvem vandt?")

    if st.button(
        f"🏆 {t1p1} + {t1p2}",
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

    if st.button(
        f"🏆 {t2p1} + {t2p2}",
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
# HISTORIK
# =========================================================

elif page == "Historik":

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
                f"{match['team1_player1']} + "
                f"{match['team1_player2']}"
            )

            team2 = (
                f"{match['team2_player1']} + "
                f"{match['team2_player2']}"
            )

            if winner == 1:
                winner_text = team1
                new_winner = 2
                new_winner_text = team2
            else:
                winner_text = team2
                new_winner = 1
                new_winner_text = team1

            date_text = (
                match["match_date"]
                .strftime(
                    "%d-%m-%Y %H:%M"
                )
            )

            st.markdown(
                f"""
                <div class="match-card">
                    <strong>{team1}</strong><br>
                    mod<br>
                    <strong>{team2}</strong><br><br>
                    🏆 Vinder:
                    <strong>{winner_text}</strong><br>
                    <span style="opacity:0.7">
                        {date_text}
                    </span>
                </div>
                """,
                unsafe_allow_html=True
            )

            col1, col2 = st.columns(2)

            with col1:

                if st.button(
                    "✏️ Ret",
                    key=f"edit_{match_id}",
                    use_container_width=True
                ):
                    st.session_state[
                        "edit_match"
                    ] = match_id

            with col2:

                if st.button(
                    "🗑️ Slet",
                    key=f"delete_{match_id}",
                    use_container_width=True
                ):
                    st.session_state[
                        "delete_match"
                    ] = match_id

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

                if st.button(
                    "Ja, ret vinderen",
                    key=f"confirm_edit_{match_id}",
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

                    st.session_state[
                        "message"
                    ] = (
                        "✅ Vinderen er rettet."
                    )

                    st.rerun()

                if st.button(
                    "Annuller",
                    key=f"cancel_edit_{match_id}",
                    use_container_width=True
                ):

                    st.session_state.pop(
                        "edit_match",
                        None
                    )

                    st.rerun()

            if (
                st.session_state.get(
                    "delete_match"
                )
                == match_id
            ):

                st.warning(
                    "Er du sikker på, at kampen skal slettes?"
                )

                if st.button(
                    "Ja, slet kampen",
                    key=f"confirm_delete_{match_id}",
                    type="primary",
                    use_container_width=True
                ):

                    with conn.session as session:

                        session.execute(
                            text("""
                                DELETE FROM elo_history
                                WHERE match_id =
                                      :match_id
                            """),
                            {
                                "match_id":
                                    match_id
                            }
                        )

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

                        recalculate_ranking(
                            session
                        )

                        session.commit()

                    st.session_state.pop(
                        "delete_match",
                        None
                    )

                    st.session_state[
                        "message"
                    ] = (
                        "🗑️ Kampen er slettet."
                    )

                    st.rerun()

                if st.button(
                    "Annuller",
                    key=f"cancel_delete_{match_id}",
                    use_container_width=True
                ):

                    st.session_state.pop(
                        "delete_match",
                        None
                    )

                    st.rerun()

            st.divider()


# =========================================================
# SPILLERE
# =========================================================

elif page == "Spillere":

    st.title("👤 Spillere")

    st.subheader(
        "Opret ny spiller"
    )

    new_player_name = st.text_input(
        "Navn",
        placeholder="Fx Mads Jensen"
    )

    if st.button(
        "➕ Opret spiller",
        type="primary",
        use_container_width=True
    ):

        success, message = create_player(
            new_player_name
        )

        if success:

            st.session_state[
                "message"
            ] = f"✅ {message}"

            st.rerun()

        else:

            st.error(
                message
            )

    st.divider()

    st.subheader(
        "Alle spillere"
    )

    players = get_players()

    for _, row in players.iterrows():

        st.markdown(
            f"""
            <div class="player-card">
                <div class="player-name">
                    {row["name"]}
                </div>
                <div class="player-stats">
                    ELO {int(row["elo"])}
                    · {int(row["matches_played"])} kampe
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )
