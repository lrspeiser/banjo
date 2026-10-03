# World chat — October 2, 2026

Source base: `902742749f706089cc54438298f0c98aace54625` on main. This checkpoint changes host Python, browser JavaScript/CSS and tests; native binaries and material laws are unchanged.

## Implemented audiences

| Recipient | Behavior |
| --- | --- |
| AI Guide (default) | Read-only help from the authenticated player's fresh wallet, inventory, stock, goals and skill requirements/practice, native energy readings, machine summaries and explicitly focused body. The provider call releases world access so other players can continue interacting. |
| AI Actions | Existing bounded world action agent, now with each player's own saved history. Named-world open/rejoin does not return another player's action history or old shared room chat. |
| Players in this world | Explicit authenticated broadcast. No guide question is broadcast. Sender names come from player records, text is rendered without HTML, and worlds use separate databases. |
| Named AI character | Read-only conversation from that character's own inventory, wallet, goals and recorded progress/blocker. Conversation does not control autonomous play. |
| Named machine | Existing bounded machine conversation/command handler using the actual selected program and the visitor's position. |

AI Guide and character conversations use bounded browser-page history; reloading clears it. Action history is in the saved player profile. Human messages are in the world's existing Workshop SQLite database: 200 recent messages retained, 50 returned per poll, receipt headers retained for durable retry deduplication. Polling is every 2.5 seconds while Players is selected and the page is visible. Pending sends survive reload in session storage and expose Retry after an uncertain acknowledgement. Reusing an identifier with another sender or different content is refused. Sending is limited to five messages per player in two seconds and 1,000 characters per message. Direct messages, moderation and cross-world chat are not implemented.

## HTTP boundaries

All endpoints require a joined player, named-world routing and the normal request token.

- `POST /api/world/help`: `{message, screen, history?, focus?}`; `world` is now a supported screen. Server state cannot be supplied by the client; history accepts only bounded user/assistant text. Provider tools are empty.
- `POST /api/world/messages`: `{action: "list", after_id?}` or `{action: "send", message, request_id}`. SQL receipts bind the request to the authenticated sender and content across restart.
- `POST /api/world/character/chat`: `{id, message, history?}`. Only AI characters in this world are valid. The character's account is selected by the server; controller credentials are excluded from provider observations.
- Existing `/api/world/ask` and `/api/world/rover/talk` continue to handle bounded actions.

## Verification

Windows/Python 3.13/Chrome, using the existing `build/agent-object-strike/Release` native fixtures:

- Five `world_chat_tests.py` cases: authentication, world isolation, restart deduplication, message bounds/rate limit, character-owned state/token exclusion, personal action history through actual ask/open/restart, and Chrome guide/player/machine flow. Browser verification includes another authenticated player responding, literal HTML text, audience separation and a simulated lost acknowledgement retried exactly once.
- Three `game_guidance_tests.py` checks: request boundary, provider payload and concurrent peer native access while a model waits.
- Existing 50 `chat_history_tests.py` and 24 `chat_tool_parity_tests.py` checks pass.
- JavaScript syntax and Python compilation pass. Source registration: 297/297.
- Actual gpt-5-mini World guide and AI-character conversations ran on preview 8771 after a saved-world checkpoint/restart. The guide explained shared solar storage versus manual wallet banking using current readings. Character conversation used its own zero wallet and recorded first-goal blocker. That live reply exposed ambiguous second-person labels and visitor-banking advice; a separate character prompt replaced the human-guide instructions. A final live reply used its own wallet and identified the recorded planner/action-selection blocker despite banking being available, without suggesting that visitor banking would advance it.

An intermediate test setup received a transient HTTP 400 creating its second generated world; the complete final chat suite passed on rerun. This checkpoint does not qualify generated-map reliability or autonomous progression. The existing AI trailblazer remains blocked at its first goal despite banking being available to the human; capture its action catalog/model decision before treating that as a real game blocker. R6 remains open.

Commands: set `BANJO_LIVE_ENGINE`, `BANJO_LIBRARY` and `BANJO_BUILD_DIR` to the existing Release fixtures, set `BANJO_BROWSER_TESTS=required`, then run `python -m unittest discover -s tests -p <suite> -v` for the four suites above, `node --check playground/world.js`, `python -m py_compile playground/server.py playground/game_guidance.py playground/player_messages.py`, and `python scripts/check-source-registration.py`.
