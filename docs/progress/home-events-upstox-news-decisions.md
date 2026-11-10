# Upstox news doc: findings needing a user decision

Source: `docs/progress/home-events-upstox-news-review.md` (two of six lenses ran; the four other lenses have not run, so this list is not the final review). Doc: `docs/designs/home-events-upstox-news.md`. Line numbers below are the original doc's lines, before this edit. Items are listed here only; none is decided.

## Findings needing a user decision

### Finding 1 (remaining part): feed tier, event type, token, and LLM ordering

Finding 1 itself is resolved by the 2026-11-10 storage decision and is not listed here as a decision. Three parts remain open.

- Question: which feed tier and event type do Upstox items take (overview 7.1)? The review asks for this and gives no answer.
- Question: may the Upstox build ship before the LLM relevance stage exists (overview 7.7)? The review says it may come before or with the LLM stage and gives no answer. Proposed by orchestrator draft: no; without the stage there is no gate, so nothing should reach `news_events` before it exists.
- Question: should the poller use its own ingest token, or share `home_events_ingest`? The review's recommendation is a distinct poller token, or an explicit decision to share. The doc now proposes `upstox_news_ingest` (distinct). Confirm or reject.
- Doc lines affected: 33 to 34 (token role), 47 and 72 (storage and build item 2). The storage route is now in the "Storage and route" and "Ingest route and token" sections.

### Finding 2: how an article is attributed to a symbol, and what empty data means

- Question: if the live Upstox payload has no instrument key on each item, how is an article linked to a symbol? The review's fallbacks are one request per key (about 751 per day, which the existing limiter can absorb) or symbol extraction in the LLM stage. Also: may a redacted sample be captured before the Upstox confirmation? And does zero items across all keys mean "no news" or "broken"?
- Review's recommendation: no single answer. The review lists the two fallbacks and asks the user to decide. Proposed by orchestrator draft: capture one redacted sample now, kept out of git, because capture does not publish anything; defer the attribution choice until the sample shows whether the key is present.
- Doc lines affected: 24 to 29 (endpoint and request shape), 38 (poll window), 45 (stored fields).

### Finding 3: dedupe key, and the seen-links store

- Question: is the dedupe key `article_link` alone, or `(article_link, instrument key)`? Should a seen-links store be adopted, or overview 8.2 item 3 (30-day hash of rejected rows) for this source? The review notes that a link-only key drops the second symbol when one article tags two instruments.
- Review's recommendation: use the filings convention of a source prefix plus hash (filings spec 4.2). It does not pick between the two key forms. Proposed by orchestrator draft: `(article_link, instrument key)`, so one article tagged to two symbols keeps both; and adopt overview 8.2 item 3 for this source, owned by the news doc.
- Doc lines affected: 40 (dedupe), 45 (stored fields).

### Finding 6: how "OFF" is enforced, and whether specs are written while blocked

- Question: the source is OFF until Upstox confirms, but `collector_settings.mode` only allows `scheduled` or `manual`, and a UI "Run now" can still start a `manual` source. Which guard is used?
- Review's recommendation: no pick. The options are (a) do not register the source in `SOURCES` or `config/collector_services.json` until unblocked, or (b) add a default-disabled parameter that the run checks first, mirroring filings `default_enabled`. The review also asks whether build specs may be written now with the source disabled. Proposed by orchestrator draft: option (a), and yes, write specs while disabled, since that leaves one switch to flip.
- Doc lines affected: 12 and 71 (OFF status and the enabled switch).

### Finding 8: SDK or UpstoxClient

- Question: should the News call use the official SDK (`upstox-python-sdk`, a new dependency in `requirements.txt`, `requirements.lock.txt` and the Dockerfile), or `UpstoxClient._get`?
- Review's recommendation: no pick. It says to decide, and if the SDK is chosen, to add the dependency changes. The review's facts: a plain urllib call gets HTTP 403 from Cloudflare; `UpstoxClient._get` already has the Bearer auth, the three-window limiter and the 429 handling; a News call is one new method plus a `NEWS_BATCH_SIZE = 30` constant. Proposed by orchestrator draft: `UpstoxClient._get`, because it adds no dependency and already has the limiter and headers.
- Doc lines affected: 24 (endpoint wording) and 49 to 54 (rate limit). Note: the line 54 correction ("gap and cap not set" is not accurate, because `UpstoxClient` has a limiter) is applied in the doc, as the task instructed, and the rest of this finding is still open.

### Finding 11: keep or drop the 1-week age limit

- Question: keep the 1-week age limit (overview 8.2 item 8)? The endpoint already returns about 7 days, so it filters almost nothing. If kept, what does it measure: `published_at` or fetch time?
- Review's recommendation: no pick. It asks for the decision, and says that if kept, the doc must state it is a near no-op. Proposed by orchestrator draft: drop it for the first build, since the endpoint window already does the job.
- Doc lines affected: 41 (age limit).

### Finding 13: the universe

- Question: which rows make up the Upstox universe?
- Review's recommendation (quoted): "Define the universe as `symbol_sector` rows `WHERE isin IS NOT NULL`". It also asks for a volume estimate, since the first poll can send up to 7 days of articles for 751 stocks to the local LLM. The shortlist is about 39 names. The browser watchlist is not stored server-side. Proposed by orchestrator draft: the 751 ISIN rows, with the volume and LLM time estimate done before build.
- Doc lines affected: 25 to 26 (universe and batching).

### Finding 16: which document owns the values

- Question: does this stub own the Upstox values (poll, batch, age limit, token role), or does overview 5.4 keep them and this stub only restate them?
- Review's recommendation: no pick. It offers two options: add the line "overview 5.4 governs until the values move here", or make the stub the single owner and have the overview point to it. Proposed by orchestrator draft: keep the overview as owner until the build spec is approved (the status quo under overview section 2). The doc's status line now reads that way.
- Doc lines affected: 3 (status line), 20 to 58 (owned rules).

## Cross-document items for other owners

These are not edited in this task. Each one needs its owner.

- Finding 17, execution ledger: `docs/progress/execution-ledger.md` line 39 cites `home-event-sources.md` 4.5 for Upstox News terms. The content is now at overview 4.1 and 5.4. Owner: the execution-ledger owner.
- Finding 5, overview 5.4 and 7.3: the "loses nothing" wording needs the collector-uptime condition (about 7 days). The collector split spec runs only the latest missed slot (its risk 5). Owner: overview.
- Finding 12, overview 5.4: the instrument-key sentence is on line 83, but the stored-fields list on line 85 omits the key. Owner: overview.
- Finding 8, overview 7.3 table: the Upstox row is at line 175 (the review cites 158). It says gap "Not set" and cap "Upstox class assumed". Owner: overview.
- Finding 14, overview 8.2 item 15: the "terms not read" list does not include the Upstox API terms and developer agreement. Owner: overview.
- Finding 14, ui-redesign-spec section 9 decision 1: a separate Upstox data-sharing licence check. One inquiry to Upstox could cover both. Owner: the project owner, with the ui-redesign spec owner.
- Finding 1, overview 6.3 against filings spec 4.1: the event-row field list (event_id, classified_at, symbols, sectors, stance, model_id, prompt_version, status) does not match the `home_events` columns. Owner: overview and the news doc.
- Finding 1, route ordering: overview 7.7 build order, and whether the Upstox build waits for the LLM stage. Owner: overview.
- Finding 7, collector split spec: M9 does not assign the Upstox schedule to any plan (per the review; not re-checked here). The split spec also needs the `upstox` row in `exchange_cooldown` and the `exchange` field in `config/collector_services.json` for this source. Owner: split spec.
- Finding 10, filings spec 5.5: no purge covers the news tables; the planned purge is inside the `home_filings` run. Owner: filings doc.
- Finding 3 and the dedupe key: overview 8.2 item 3 (rejected rows, 30-day hash). Owner: news doc.
- Finding 19, `secrets-and-roles.md`: its roles (admin and named user) do not describe the service token that the endpoint maps to `collector`. Owner: secrets doc.
- Review file: the summary line says "12 Majors, 6 Nits". The headings show 15 Majors and 3 Nits. Both total 20. Owner: the review's synthesizer, or whoever next updates the review.
- Review file: four lenses (zoom-out, comprehension, implementation-readiness, structural) did not run. The review is not complete until they run. Owner: the project owner.
- Finding 19 note: the review says Fastify also reads an Upstox token from `data/secrets.env`. This task did not read `data/`, so that is unverified. Owner: whoever next reviews `server/src/secrets.ts`.
