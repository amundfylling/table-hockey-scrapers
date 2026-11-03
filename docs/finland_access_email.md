**To:** Suomen Pöytäjääkiekkoliitto (results site tulos.poytajaakiekko.fi)
**Subject:** Read access to tournament results for a non-commercial head-to-head stats site

Hello,

I run https://h2h.puck.no, a free, non-commercial site where table hockey players can look up their head-to-head
record against other players, built from public tournament results (ITHF ranking, Sportscorpion and national sites).

Finnish ranking tournaments are a big gap for us. Your new results site is great, and I can see the event list is
public, but the game results are served through an API that needs your internal key, so I have not tried to read
them automatically.

Would you be willing to give us read access to the results? Any of these would work for us:

- a read-only API key for the tournament results (we fetch at most once a night, max 1 request per second), or
- a periodic export (CSV/JSON) of games: date, tournament, stage, both players (with ITHF id where known) and score.

We credit the source on every page that uses the data, and we are happy to stop or adjust at any time if you
prefer. The scraper code is open: https://github.com/amundfylling/table-hockey-scrapers

Thank you for considering it!

Best regards,
Amund
https://h2h.puck.no
