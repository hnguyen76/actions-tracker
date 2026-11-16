# Live big-play alert — design (short)

**Intent.** While the dashboard is open, the owner wants to notice big plays in the games they have a play on
without staring at the score: touchdown, field goal made, field goal missed/blocked, interception, fumble lost.

**Approach (picked by the owner).**
1. On the page only: full-screen fireworks + big text + short chime, vibration on Android. Instant (5–10 s). **Picked.**
2. Telegram from the home phone: buzzes the iPhone in a pocket, but 1–5 min late and more phone work. Not now.
3. Both. Not now.
iPhone Safari cannot vibrate from a web page, so the visual + sound is the alert there.

**Goals.** One alert per new play, only for games on the "Đang đá & chờ kết quả" card (games with a play),
NFL/NCAAF. Shows the event, the team, the score, and the owner's bet with "đang thắng / đang thua"; green tone
when the play helps the bet side, red when it hurts.

**Non-goals.** No alerts for plays that happened before the page was opened (first look only records them).
No Telegram, no push notifications, no alerts while the tab is hidden (live polling already stops then).
Fumbles recovered by the same team are not alerts.

**Anti-goals.** Never alert twice for the same play; never block the page (tap anywhere to dismiss, ~4 s auto).

**Design.**
- Data: `live-scores.js` already fetches the ESPN summary every 10 s for live football. Add `parseBigPlays`:
  the last plays of `drives.previous` (last drive) and `drives.current`, each classified from `type.text`
  (and `scoringPlay` / text as fallback) into `touchdown | field_goal | field_goal_missed | interception |
  fumble_lost`, with play id, benefiting team side (scoring team; for turnovers the team that gained the ball),
  play text. Result travels as `drive.big_plays` on each live score row.
- Page: `scoreboard.js` (or a small new `big-play.js`) keeps a seen-set per game. The first time a game is seen
  its plays are only recorded; later, a new play id triggers the overlay (queue if several).
- Overlay: fixed full-screen layer, canvas fireworks in the benefiting team colour, big label
  (TOUCHDOWN / FIELD GOAL / FIELD GOAL MISSED / INTERCEPTION / FUMBLE), team, score, bet line with
  win/lose tone; Web Audio chime after the first user tap; `navigator.vibrate` where available;
  `prefers-reduced-motion` → banner only, no particles.

**Constraint.** ESPN is blocked from the cloud session, so classification is tested with fixtures built from
known ESPN play type names; the first real check is the next live NFL game.

**Left to the builder.** Exact animation, chime, colours, queueing details.
