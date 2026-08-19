import streamlit as st
import pandas as pd

st.set_page_config(
    page_title="MPT Padel Ranking",
    page_icon="🎾",
    layout="centered"
)

st.title("🎾 MPT Padel Ranking")
st.subheader("ELO rangliste")

try:
    conn = st.connection("supabase", type="sql")

    players = conn.query(
        """
        SELECT
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

    if players.empty:
        st.info("Der er endnu ingen spillere i databasen.")
    else:
        players = players.copy()
        players["Placering"] = range(1, len(players) + 1)
        players["Win %"] = players.apply(
            lambda row: round((row["wins"] / row["matches_played"]) * 100, 1)
            if row["matches_played"] > 0 else 0,
            axis=1
        )

        players = players.rename(columns={
            "name": "Spiller",
            "elo": "ELO",
            "matches_played": "Kampe",
            "wins": "Sejre",
            "losses": "Nederlag"
        })

        st.dataframe(
            players[
                ["Placering", "Spiller", "ELO", "Kampe", "Sejre", "Nederlag", "Win %"]
            ],
            hide_index=True,
            use_container_width=True
        )

except Exception as e:
    st.error("Kunne ikke forbinde til databasen.")
    st.code(str(e))
