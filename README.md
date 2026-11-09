# Entente

A classic Diplomacy table for friends: an atlas-style interactive board, private orders, and host-paced adjudication. Spring 1901, standard Europe only.

Live: https://entente-diplomacy.vercel.app

## Quick start

**Run locally (SQLite, no setup):**

```sh
git clone https://github.com/nathanpljohnson/entente-diplomacy.git
cd entente-diplomacy
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

Open http://127.0.0.1:8000. Games are stored in `data/entente.db`.

**Run locally against the Neon database:**

```sh
npx vercel link            # pick the entente-diplomacy project
npx vercel env pull .env.local
npx vercel env run -- .venv/bin/python app.py
```

This connects to the live Neon database, so don't run destructive tests against it.

**Deploy to Vercel:**

```sh
npx vercel --prod
```

Vercel needs `DATABASE_URL`, which the Neon integration sets for you. The QStash variables are optional and only needed for phase timers. See `.env.example` for the full list. Never commit `.env.local`.

## Play

1. Create an account with a username and a password of at least 12 characters.
2. Create a private game as host only, or choose a power yourself. Share the invitation code from **Powers** privately with your friends.
3. Each friend creates an account, chooses **Join with code**, and claims a different power.
4. Negotiate in person or in your own messaging app. Select units and destinations on the map, or use the complete keyboard-accessible order builder.
5. Add orders to the sheet. **Save draft** persists orders but marks the power not ready. **Submit orders** persists them and marks the power ready. Submissions remain editable until resolution.
6. The host sets a phase clock, or chooses **Adjudicate phase** and confirms. All saved orders resolve together, including drafts; missing orders use the defaults explained in the confirmation and rulebook. The host may resolve before every power has submitted.
7. Retreats and adjustments appear automatically when needed. Resolved orders and results are available in **History**.

Choose **Private sandbox** to control all seven powers yourself. Click any unit and then its destination; power selection and saving happen automatically, and all powers’ arrows remain on the map. Support and convoy use the issuing unit → action → cooperating unit → destination. Resolve when ready.

## Phase clocks, draws, and scenarios

The host can start, restart, pause, resume, or stop the phase clock. Defaults: 20 minutes for 1901 movement, 15 for later movement, 3 for retreats, 5 for adjustments. All durations are editable (1 minute–24 hours). Upstash QStash Free delivers signed deadlines even with all browsers closed. Set `QSTASH_TOKEN`, `QSTASH_CURRENT_SIGNING_KEY`, `QSTASH_NEXT_SIGNING_KEY`, and optionally `QSTASH_URL` through the Vercel integration. `APP_URL` defaults to the production Entente address; change it when self-hosting. A failed next-phase schedule pauses the clock visibly. Stale callbacks are harmless and concurrent resolution uses a revision check.

**Custom draw rule:** a draw offer replaces that power’s order sheet. Unanimous offers from surviving powers end the game; otherwise draw-offering powers issue no orders and normal missing-order defaults apply. Offers reset each phase and may be withdrawn before resolution.

**Try a scenario** opens a private independent copy in a new tab, from the current or selected historical phase. It includes your own current ideas, never other players’ secret orders. Its owner controls every power. Multiple copies can be adjudicated independently without changing the live game.

Winter adjustments automatically open a nonmodal build/removal panel beside the map with per-power allowances, remaining slots, and legal location buttons. Inland centers offer only armies; split-coast fleet builds require an explicit named coast. Captured foreign and occupied centers explain why they are unavailable. Choices submit as ready orders and take effect only after adjudication. The planner can be reopened from the Orders panel. On mobile, the map stays visible above independently scrolling build choices. Thick country outlines follow the union of the currently controlled land provinces, including Fall captures entering Winter. Thin internal province lines and original movement geometry remain unchanged.

Territories use pastel country colors; actual army circles and fleet triangles use stronger fills with a dark edge in the same hue. Home supply centers use double diamonds; other supply centers use hollow diamonds. Territory details name the original home power separately from current ownership. A captured home center retains its original designation, and can only be used for builds by that original power when owned and vacant. The standard opening renders exactly 22 units and 34 supply-center markers.

Retreat phases show a popup only for powers with genuinely displaced units. Each displaced army/fleet gets a named origin, legal destination dropdown and explicit Disband choice. Players without displaced units see a waiting message. Saved retreats resolve together when the host or clock adjudicates.

Army pieces are circles and fleets are triangles. The army’s **Move via convoy** and the fleet’s **Convoy an army** actions are explicit. Ambiguous direct/convoy destinations ask which route to use; convoy-only army destinations ask for confirmation. Convoy sheets show full origin/destination names and explain the matching army/fleet orders.

Movement arrows are white; support/convoy arrows are curved and dotted. The resulting map retains the last phase’s orders, with failures red and marked ×. The result toggle switches between current planning and the last outcome. Valid support stays white even when the supported attack bounces. Historical starting-position maps use the same result colors.

Province geometry is unchanged. Labels and unit anchors are placed separately for legibility. Selecting a territory reveals its full name. Supply-center colors follow Fall ownership; other land follows last occupation, with original national colors until visited.

## Run locally

Requires Python 3.12 or newer (tested with Python 3.13).

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

Open http://127.0.0.1:8000. Local development uses `data/entente.db` unless `DATABASE_URL` is configured. A local database is not uploaded during deployment.

## Free cloud hosting

The project supports Vercel's Flask runtime and a persistent Neon PostgreSQL database. The provisioned Neon integration uses its **Free** plan, auth and realtime disabled, region `iad1`. Vercel Hobby is appropriate for this personal project, within its current usage limits. No paid plan is needed for this configuration.

```sh
npx vercel login
npx vercel link
# Provision Neon Free through Vercel Storage / Marketplace, connecting Production.
# The integration supplies DATABASE_URL. Do not paste credentials into source.
npx vercel --prod
```

The application refuses Vercel startup without `DATABASE_URL`, preventing accidental ephemeral game storage. Database tables are created on startup. Static assets live under `public/static` for Vercel's CDN. PostgreSQL and SQLite use optimistic revision checks to prevent a stale operation from overwriting a concurrent game change or resolving the same phase twice.

For an already linked checkout, use `npx vercel env run -- .venv/bin/python app.py` to run against its configured development database. Development and production are connected to the same initial Neon resource; do not use that database for destructive tests or reset commands. Configure a separate branch/database before developing migrations against live games.

## Rules and map data

The server uses **Diplomacy 1.1.2**, not a handwritten approximation or a language model, for legal orders and adjudication. It covers support, cuts, bounces, head-to-head moves, convoys, dislodgement, retreats, coast-specific fleets, builds, disbands, supply center capture, civil disorder defaults, and solo victory. The engine's rule interpretations apply to edge cases.

`/rules` contains an original practical rulebook. The source distribution of the adjudicator is included under `third-party/`, including its rule definitions, maps, and tests.

The standard map has exactly **75 playable provinces: 56 land and 19 sea**, **34 supply centers**, **22 home centers**, and **12 neutral centers**. Russia starts with 4 units, each other power with 3. Switzerland is depicted but excluded from playable regions. Separate coast records are not counted as extra provinces.

`GET /api/provinces` exposes region abbreviations, terrain, coasts, adjacency, supply centers, homes, and starting units. Engine IDs use uppercase (`PAR`, `LON`, `MOS`, `STP/SC`). The 75 IDs match the published DBN ProvinceEnum after case normalization.

Two authenticated exports are available:

- `/api/games/<id>/export`: native state, phase history, engine orders, and result labels.
- `/api/games/<id>/export/dbn`: DBN 2022-02 game format with the schema's exact sea/land casing (`NAO`, `Par`, `Lon`, `Mos`), country names, structured coast tuples, and order tuples. Available from **Guide**. Historical records contain beginning-of-phase positions and resolved orders. Current private orders are excluded from both exports. Explicit VIA convoy annotations remain in the native export because the DBN format has no dedicated field for them.

The published DBN schema declares Draft 2020-12 but uses older tuple-valued `items` syntax. Export validation was performed using Draft 7 tuple semantics and the original enumeration/field definitions, rather than claiming the unmodified schema passes a 2020-12 metaschema check.

## Verification

```sh
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
node --check public/static/app.js
# Installed upstream adjudicator tests:
.venv/bin/python -m pytest .venv/lib/python*/site-packages/diplomacy/tests/test_datc.py -q
```

The application suite covers geography, authentication, session logout, origin and CSRF protection, private orders, unauthorized actions, exclusive seats, illegal/duplicate/stale orders, exactly-once resolution, phase history, retreat handling, and source archive privacy. The installed engine's 160 DATC tests were also run. Browser verification covers registration, game creation, order entry, submission, host confirmation, adjudication, history, desktop/mobile layouts, and console/network errors.

## Boundaries

- No email, password recovery, in-game messaging, or replacement-player flow yet.
- No alternative maps, per the requested scope.
- Accounts and games persist in the configured database. The map is shared; only a power's current orders are secret. Host administrative database access is necessarily outside the player privacy model.
- Polling refreshes game changes every 15 seconds while the page is active. Unsaved drafts are retained on the same device and scoped to account, game, phase, and power.
- This is a small-group first release, not a large public matchmaking service.

## Sources and credits

- [Diplomacy engine and standard map](https://github.com/diplomacy/diplomacy), AGPL-3.0; pinned source included in `third-party/diplomacy-1.1.2.tar.gz`.
- [Diplomacy Broadcast Network game schema](https://diplobn.com/diplomacy-game-json-schema/) and [published JSON](https://diplobn.com/GameJSON/2022-02/gameschema.json).
- [Backstabbr playing guide](https://www.backstabbr.com/how-to-play), observed sandbox workflow, and independent interface inspiration. No Backstabbr code or assets were copied.
- [Diplomacy Adjudicator Test Cases](https://petermc.net/diplomacy/datc_v3_3.html).
- Community research: [manual turn processing](https://www.reddit.com/r/diplomacy/comments/1i0qpkv/), [sandbox order checking](https://www.reddit.com/r/diplomacy/comments/1ni5zue/), [clear retreat/build maps](https://www.reddit.com/r/diplomacy/comments/1uxfb3f/free_webbased_diplomacy_adjudicator_datccompliant/), and [variant adjudication discussion](https://www.vdiplomacy.com/forum.php?threadID=99139).

The SVG geography is derived from the engine's jDip map; its original credits (J. Fatula III and Zach DelProposto, jDip GPL notice) remain embedded. Entente adapts colors, typography, interactive province targets, and presentation. Frontend controls use native semantic HTML, native dialogs/selects, and original CSS; no additional component library was needed after reviewing the approved catalog.

Entente is licensed under **AGPL-3.0-or-later**; see `LICENSE`. A corresponding source download, including the engine source distribution, is linked at `/source.zip`. Private databases, environment files, credentials, and runtime caches are excluded. Keep that source link working when hosting modified versions. This independent project is not affiliated with Backstabbr or the owners of the Diplomacy trademark.
