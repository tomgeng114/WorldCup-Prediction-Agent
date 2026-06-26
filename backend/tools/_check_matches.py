import sqlite3
conn = sqlite3.connect('worldcup_ai.db')
c = conn.cursor()

# M68, M69
for mid in [68, 69]:
    c.execute("""SELECT m.id, m.kickoff_time, ht.name, at.name, m.home_score, m.away_score
                 FROM matches m
                 JOIN teams ht ON m.home_team_id = ht.id
                 JOIN teams at ON m.away_team_id = at.id
                 WHERE m.id = ?""", (mid,))
    r = c.fetchone()
    if r:
        print(f'M{r[0]}: {r[2]} vs {r[3]} | score={r[4]}-{r[5]} | {r[1]}')

# Count scores
c.execute("SELECT COUNT(*) FROM matches WHERE home_score IS NOT NULL")
print(f'\nTotal with scores: {c.fetchone()[0]}')

c.execute("SELECT status, COUNT(*) FROM matches GROUP BY status")
for r in c.fetchall():
    print(f'  {r[0]}: {r[1]}')
