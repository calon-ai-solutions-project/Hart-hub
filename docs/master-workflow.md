# Hart Hub: master workflow and architecture

## How to use this document

This is the master plan for how Hart Hub works. Start with section 01 for the big picture, then read the workflow you are working on. Every workflow follows the same pattern: the steps in order, where the data comes from and where it goes, the rules, and the tricky cases.

A shorter two-page overview exists for anyone who just needs the idea ([workflow-overview.md](workflow-overview.md)). AI coding agents should read section 02 (ground rules) and section 03 (architecture) before any task.

### Words we use

| Word | Meaning |
| --- | --- |
| Enquiry | A customer asking about a car. Starts on WhatsApp, a phone call, the out-of-hours number or a campaign reply. |
| Requirement | What the customer wants, captured from the enquiry form: car, budget, deposit, term, mileage, part-exchange and so on. |
| Platform sync | The scheduled run that collects car details from BCA, Motorway, Carwow and Manheim into our own database. |
| Listing | One car from a sourcing platform, with photos, details, price and end time. |
| Option card | One car offered to a customer: images, details, price, Codeweavers finance and the time it is available until. |
| Available until | The time the car stops being available on the platform. After this the deal is gone. |
| Inbox | Each salesperson's list in the portal of conversations and option cards waiting for them. |
| Source of truth | WhatsApp. Every customer conversation starts and lives there; the Hub mirrors it. |
| Consent | A recorded yes from the customer to be contacted on a channel (WhatsApp, email, SMS). |

## 01 The big picture

Hart Hub does three jobs. It keeps a fresh database of cars from the sourcing platforms. It turns every customer enquiry into ready-to-send options with real finance quotes. And it brings customers back through social posts and campaigns. Everything a customer sees is approved by a salesperson first.

**How data moves through the system:** platforms feed the listing database. Every enquiry becomes a requirement, is matched against the database, gets Codeweavers quotes and becomes option cards that a salesperson approves. Everything lands in the CRM, which feeds campaigns.

### All workflows at a glance

| ID | Workflow | Starts when | Ends with | Build step |
| --- | --- | --- | --- | --- |
| F0 | Platform sync and listing database | Each platform's daily slot | Fresh, priced listings with end times | Step 2 |
| W1 | Deal sourcing from WhatsApp | Customer messages a Hart WhatsApp number | Approved option cards sent; customer picks a car | Steps 3 to 5 |
| W2 | Portal chatbot | Salesperson asks what is available | Options sent to a chosen customer | Step 3 |
| W3 | Call-log form | Customer phones James or a salesperson | Options sent by email (or WhatsApp with consent) | Step 4 |
| W4 | Out-of-hours voice AI | Customer rings the out-of-hours number | Options waiting for approval in the morning | Step 7 |
| W5 | AI social posting | Someone picks a live car to post | Posts live on every account with end time | Step 7 |
| W6 | CRM and campaign manager | Click Dealer import or any enquiry | Targeted campaigns; replies become enquiries | Steps 6 to 7 |

## 02 Ground rules that apply everywhere

These rules come from how Hart works and from the signed contract. Every workflow must follow them.

### WhatsApp is the source of truth

- Every enquiry arrives on WhatsApp, including website enquiries. There is no separate website form feeding the Hub.
- James and each salesperson have their **own WhatsApp Business number and login**, and post that number on their own social media. Replies always go from the same number the customer contacted.
- The team keeps using WhatsApp on their phones. Everything sent from a phone still appears in the Hub.

### Approval and what customers see

- Nothing goes to a customer without a salesperson approving it, unless the client later switches on an automation setting.
- Finance figures only ever come from **Codeweavers quotes**. Quotes only: no finance applications from the Hub. AI never calculates finance.
- Every option shows its **available-until** time from the platform. Expired cars are never sent, matched or posted.
- Buy price, prep cost and margin are **staff only** and never appear on anything a customer sees.

### WhatsApp messaging rules

- Within 24 hours of the customer's last message, the Hub can reply freely. Outside that window, only a Meta-approved template can be sent.
- People who have not messaged us on WhatsApp (phone callers, voice AI callers, campaign lists) are contacted by **email by default**, and on WhatsApp only if their consent is recorded. This stops WhatsApp flagging the numbers.

### Platform sync rules (contract Schedule 1)

- Sync runs only for platforms the client has approved in writing.
- It collects the listings surfaced by Hart's own saved searches and alerts on each platform. Set up broad saved searches so the database covers the cars customers ask for.
- Once per day per platform, at that platform's slot. Stops immediately on any CAPTCHA, warning or block, and never tries to get round it. Every listing opened is logged.

### Data and environments

- Campaigns go only to customers whose consent allows it. STOP removes a customer from every channel at once.
- No real customer data in code, test files or screenshots. The staging environment never messages real customers.

## 03 Architecture

| Component | What it does | Talks to |
| --- | --- | --- |
| Web portal | Screens for owner, sales and admin: inbox, option cards, chatbot, call-log form, posting, CRM, campaigns | Hub API |
| Hub API | All requests and webhooks (WhatsApp messages, calls, form submissions) | Database, workers, connectors |
| Workers and scheduler | Platform sync slots, expiry checks, matching, quotes, campaign sending, posting | Database, AI, connectors |
| Sync runner | Runs the daily platform sync in the logged-in browser session | Sourcing platforms, Hub API |
| PostgreSQL + pgvector | All data plus the vector index for fuzzy matching (hosted on Railway) | API, workers |
| AI models | Cheap LLM for intent, matching and drafting; image model for showroom backgrounds; voice model for calls | Workers |
| WhatsApp Cloud API | One connection per Hart number (coexistence, so phones keep working) | Hub API |
| Codeweavers API | Finance quotes for each option | Workers |
| Meta Graph API | Facebook and Instagram posting for every page under the Hart Group business account | Workers |
| TikTok, LinkedIn, YouTube | Posting to each, through its own connection | Workers |
| Email and SMS | Options by email, campaigns | Workers |
| Telephony and voice agent | Out-of-hours number and call capture | Hub API |

### Environments

- **main** branch deploys to **production** on Railway: the live system.
- **develop** branch deploys to **staging**: the test link shared with Hart every Thursday. Staging uses test connectors only.

### Where each workflow lives in the code

| Workflow | Main code areas |
| --- | --- |
| F0 Platform sync | packages/sourcing (platforms, guard), apps/retrieval-runner, apps/worker (sync slots, expiry) |
| W1 Deal sourcing | apps/api (WhatsApp webhooks, form), apps/worker (matching, quotes), packages/ai, packages/connectors (whatsapp, codeweavers), apps/web (inbox, cards) |
| W2 Portal chatbot | apps/web (chatbot), apps/api, packages/ai |
| W3 Call-log form | apps/web (form), apps/api, apps/worker |
| W4 Voice AI | packages/connectors (telephony), apps/api (call webhooks), packages/ai |
| W5 Social posting | apps/worker (posting), packages/connectors (social), packages/ai (images, captions), apps/web |
| W6 CRM and campaigns | packages/db, apps/worker (campaigns, import), packages/connectors (email, sms, whatsapp), apps/web |

## F0 Platform sync and listing database

**In one line:** Every day, at a set time for each platform, the system collects the cars from Hart's platform alerts with all their details, photos, prices and end times, so enquiries can be matched instantly.

### Schedule

| Platform | Daily slot (UK time) | How long cars stay listed |
| --- | --- | --- |
| Motorway | 4.45pm | Daily auction, 4.30pm until 3.30pm next day (about 23 hours) |
| Carwow | 5.15pm | Bidding 5pm until 3.30pm next day; unsold cars stay listed 2 more days |
| BCA (including former Aston Barclay) | 8.00am, to confirm | Buy Now (any time), Bid Now (timed), live sales (set times) |
| Manheim | 8.30am, to confirm | Bid Now (timed), Buy Now (any time), live sales |

BCA and Manheim slots are confirmed once we see when their alerts arrive.

### Steps

1. At the platform's slot, the scheduler checks the platform is approved and the sync runner's session is logged in. If not, that platform goes to the fallback: the team updates listings by hand.
2. Collect today's listing links from Hart's saved-search alerts for that platform.
3. The runner opens each listing one at a time, with a short pause between them.
4. On every page it checks for a CAPTCHA, warning, unusual-activity notice or block. If it finds one, the run stops, Alom is alerted, and the platform switches to the fallback.
5. Capture the details below, including every photo and the listing link.
6. Calculate prep cost, suggested selling price and margin.
7. Save to the listing database and update the vector index (used for fuzzy matching).
8. Log every listing opened: platform, link, time, result.
9. Every 15 minutes, an expiry check marks cars past their end time as ended. Ended cars disappear from matching, option cards and posting.

### What we capture for every car

| Field | Example | Used for |
| --- | --- | --- |
| Platform and listing link | Motorway, link | Tracing back, team check |
| Photos (all) | 20 photos | Option cards, social posts |
| Make, model, trim | Mercedes CLA 200 AMG Line | Matching |
| Year, mileage, fuel, gearbox, colour, body | 2021, 28,000, petrol, auto, black, coupe | Matching, cards |
| Spec and condition notes | Grade, service history | Cards, staff decision |
| Buy price | Buy now, guide price or current bid | Pricing (staff only) |
| Sale type | Auction, Buy Now, Bid Now, live sale | Available-until wording |
| End time | Tomorrow 3.30pm | Available until, expiry |
| Location | Wakefield | Staff decision, collection |

### What we calculate

- **Prep cost:** default £1,100, editable per car.
- **Customer price:** platform (buy) price + the markup setting (`markup_pence`, £1,500). The salesperson can change it. After changing the setting, `python manage.py reprice_listings` re-prices every car not priced by hand.
- **Margin:** selling price minus buy price minus prep cost. Green at £2,000 or more, amber £1,000 to £1,999, red below £1,000. With a £1,500 markup and £1,100 prep the margin is £400, so the bands need Hart to confirm them. Staff only.

### Expiry and "available until" rules

| Situation | What the customer sees | What the system does |
| --- | --- | --- |
| Car has an end time | "This deal ends tomorrow at 3.30pm. After that it's gone." | Exact time from the platform |
| Less than 24 hours left | Same, marked "ending soon" | Flagged in the inbox |
| Buy Now (no end time) | "Available: Immediate." | Re-checked at the next sync |
| End time passed | Not shown | Marked ended; removed from matching, cards and posts |
| Car no longer in the platform's alerts | Not shown | Marked ended at the next sync |
| Car's page has gone from the platform (sold or withdrawn) | Not shown | Deleted at the next sync with its photos and quotes; an event records it (setting `sync_delete_sold_listings`) |

### Rules

- Only approved platforms; only listings from Hart's saved-search alerts; once per day per platform.
- Stop on any challenge. Never bypass a CAPTCHA, security check or block, and never hide that it is automated.
- Platform logins stay in the encrypted vault and the runner's browser; never logged anywhere.

### Tricky cases

- Session logged out: the run stops at the login page; a person logs in again before the next slot.
- Same car appears twice: one record, latest price and end time kept.
- Platform changes its page layout: capture fails safely, Mehdi is alerted, the team uses the fallback.

## W1 Deal sourcing from WhatsApp

**In one line:** A customer messages a Hart WhatsApp number, fills in a short form, and the system matches them to live cars, gets Codeweavers quotes and prepares up to five option cards for the salesperson to approve and send.

| | |
| --- | --- |
| Starts when | A customer messages James's or a salesperson's WhatsApp number |
| Who | Customer, AI, the salesperson who owns that number |
| Uses | F0 listing database, Codeweavers API, WhatsApp API |
| Ends with | Customer picks a car and the deal starts in the CRM |
| Build step | Steps 3 to 5 |

### Steps

1. The customer messages a Hart WhatsApp number (from social media, the website or anywhere else).
2. The message arrives in the Hub through the WhatsApp API, is saved to the customer's record in the CRM, and appears in the inbox of the salesperson who owns that number.
3. AI reads the message. If it is not a car enquiry, the salesperson handles it as a normal chat.
4. If it is a car enquiry, AI sends a friendly message with a link to the enquiry form, in the approved wording, from the same number.
5. The customer fills in the form (fields below). The answers arrive in the portal as the requirement, and the enquiry status becomes "form received".
6. If the form is not filled in after 2 hours, one reminder is sent. The salesperson can also fill it in themselves from the chat.
7. Matching runs against live listings: hard filters first, then vector search for loose wording, then a cheap LLM ranks the best five and writes a one-line reason for each.
8. If nothing matches, the salesperson is told and the requirement stays live, so tomorrow's sync is checked again.
9. For each option, the suggested selling price is used (editable), and the Codeweavers API returns a quote using the customer's deposit, term and annual mileage.
10. The system builds an option card for each car (contents below) and AI drafts the reply message.
11. Everything waits in the salesperson's inbox as "Ready to send".
12. The salesperson chooses which options to send (one to five), edits if needed, and approves.
13. The message goes out from their own WhatsApp number. Inside the 24-hour window it is a normal message; outside it, an approved template.
14. When the customer replies "I want this one", the enquiry becomes a deal in the CRM and the salesperson takes it from there.

If the customer does not reply, the CRM marks them "gone quiet" after 3 days, ready for a campaign filter (W6).

### Enquiry form

| Question | Required | Used for |
| --- | --- | --- |
| Car wanted (make, model, any must-haves) | Yes | Matching |
| Maximum price | Yes, or monthly budget | Matching, quote |
| Monthly budget | Optional | Ranking |
| Deposit | Yes | Codeweavers quote |
| Finance term (months) | Yes | Codeweavers quote |
| Annual mileage | Yes | Codeweavers quote |
| Part-exchange (reg and mileage) | Optional | Staff valuation |
| Fuel, gearbox, colour, age, mileage limits | Optional | Matching |
| When they want to buy | Optional | Priority |
| Name and email | Yes | CRM, email option |
| Consent: options by WhatsApp and/or email | Yes | How we may contact them |

### Matching

- **Hard filters:** live and not expired; make and model if given; price within the maximum; age, mileage, fuel and gearbox if given.
- **Vector search:** handles loose wording, such as "AMG Line" versus "AMG Line Premium". Only within the same make and model, so a CLA never matches an SLK.
- **Cheap LLM:** ranks the top candidates against the whole requirement and writes a short reason, for example "black, automatic, under budget".

### Option card

| Shown to the customer | Staff only |
| --- | --- |
| Photos, title, year, mileage, fuel, gearbox, colour, key spec | Platform and listing link |
| Selling price | Buy price, prep cost, margin |
| Codeweavers monthly payment, deposit, term, APR, total, with FCA wording | Codeweavers quote reference |
| "This deal ends [day] at [time]" or "Available: Immediate." | Match reason and score |

### Data in and out

| Direction | Data | From or to |
| --- | --- | --- |
| In | WhatsApp message | WhatsApp API |
| In | Form answers (requirement) | Enquiry form |
| In | Live listings | F0 listing database |
| In | Finance quotes | Codeweavers API |
| Out | Option cards and sent message | Customer on WhatsApp |
| Out | Enquiry, requirement, options sent, outcome | CRM (W6) |

### Rules

- Approval before sending.
- Finance only from Codeweavers.
- Expired cars never sent.
- Staff-only fields never shown.
- Reply from the same number the customer used.

### Tricky cases

- Customer messages two salespeople: both see a warning; the first salesperson owns the customer unless James reassigns.
- A car expires while waiting in the inbox: the card is greyed out and cannot be sent.
- Codeweavers is down: the card shows "finance quote to follow"; the salesperson can add figures manually.
- Customer wants two different cars: two requirements, matched separately.

### Built so far (October 2026 demo)

The journey runs on a channel-independent engine (`backend/apps/enquiries`): the portal's **WhatsApp
simulator** (fake numbers 07700 900000 to 900999 only) and the **real WhatsApp Cloud API** (item 10).

1. **The first message is classified by AI** (Gemini through the metered client, prompt `intent-v1` with
   a 30-example eval set: `python manage.py eval_intent`). Car enquiry or finance → the chatbot. A plain
   "hi" / "hello" (below `enquiry_min_confidence`, 0.6) → **no instant reply**: the Hub waits
   `enquiry_greeting_wait_seconds` (60). If the customer says more in that time, that message is answered
   straight away. If not, the Hub asks "Are you looking to buy a car? Or is it something else we can help
   with, like a car you've already seen, an MOT or a service?" Yes → the chatbot's questions; no, or
   other business → a person; unclear twice → a person. Other business (MOT, viewing, test drive, complaint) →
   "One of our team will reply shortly" and "Needs a person". Personal → no reply and **nothing stored**.
2. **Conversational chatbot (15 Oct 2026, default `enquiry_collect_by` = `chat`):** a natural WhatsApp
   conversation. One AI call per customer message (prompt `chat-v2`) reads the conversation, returns what
   the customer has asked for (car, monthly budget, deposit, gearbox, part-exchange) and writes the reply.
   It answers side questions, asks for one or two missing things at a time and never re-asks what it knows.
   **Every AI reply is checked by code before it is sent** (`conversation.guard`): no price, monthly
   payment or deposit the customer didn't give, no rate, APR or percentage, no "approved/accepted", no
   stock, forecourt or delivery promises, no links or phone numbers, nothing over 700 characters. A reply
   that fails is replaced by the scripted question and logged (`enquiry.ai_reply_blocked`). Facts the bot
   may give about Hart (hours, address) come only from the owner's `business_facts` setting; anything
   else, it says the team will confirm. When the details are complete (or the customer says that's all
   and we know the car or the budget) code thanks them and quoting starts, as for the form. Asking for a
   person, or `enquiry_ai_max_replies` (20) replies without enough details → "Needs a person".
   Owner switch `enquiry_ai_replies`: off, or AI unavailable → the scripted questions (make & model →
   monthly budget → deposit → gearbox → part-exchange, written by code, AI or rules only read the
   answers). Visible in the portal as "So far in the chat".
3. **After the chat:** while cars are prepared, the bot answers questions without giving a time. After the
   options, it helps the customer choose using only the sent car cards (no prices, no staff fields). A
   number ("2", "number one", "I'll go with the Audi") hands over to the salesperson and the bot goes
   quiet; a question ("which one has fewer miles?") is not taken as a choice. Option messages, quotes and
   every finance figure are still built by code from Codeweavers only.
4. **One-time form link** (only when `enquiry_collect_by` = `form`; `/f/<code>`, `form_link_days` = 7):
   make & model, colour, needed by, gearbox, monthly budget, deposit, part-exchange. One reminder of the
   link.
5. **PCP only (14 Oct 2026):** only cars with a 48-month PCP quote are sent; no Hire Purchase.
   **Quote first, then send:** cars are tried at Codeweavers in ranked order with the form's deposit until
   `enquiry_options` (5) have a quote or `enquiry_max_quotes` (12) have been tried. Cars that cannot be
   quoted are skipped. None quoted → "Needs a person", nothing sent.
6. **Approval:** the options wait for **Approve & send** unless the owner turns on `enquiry_auto_send`.
   Cars that ended meanwhile are dropped; outside the 24-hour window nothing is sent (template needed).
7. **Messages built by code from the customer card and the Codeweavers figures:** an intro, one message per
   car (first photo, details, monthly payment exactly as quoted, deal end, "more photos" link to
   `/c/<code>`), and a closing line with the disclaimer.
   **Needs sign-off:** on 14 Oct 2026 the price line and the FCA representative example were removed from
   the car messages at Mehedi's request. FCA rules (CONC 3.5) normally require a representative example
   beside a monthly payment, so Alom / Hart must approve this before real customers receive these messages.
   The same day the closing message lost its "Finance is subject to status" disclaimer and the first-payment
   bonus line; this is part of the same sign-off.

8. **No quote documents:** quotes come from Codeweavers' API (figures, lender and terms, no PDF). Customers get
   the figures and representative example in the car messages; no PDF is shown to staff or sent to customers.
9. **When a customer chooses a car** the dashboard shows an alert (banner, chime, browser tab title) for
   whoever has the simulator open.
10. **Real WhatsApp (15 Oct 2026), through Kapso (kapso.ai):** Kapso forwards Meta's WhatsApp Cloud API both
    ways unchanged. Kapso's "Meta webhook" calls `/api/whatsapp/webhook`; only calls signed with our secret
    (`X-Webhook-Signature`, hex HMAC-SHA256 of the body) are read, each message is handled once (retries are
    dropped) and in the background. Every Hub message on a WhatsApp enquiry is sent through Kapso from the
    business number the customer messaged; a car goes as its photo with the message as the caption.
    Delivery is recorded on the message (`sent` / `failed` / `skipped`); failures are logged without the
    message text. **Staging never talks to real customers:** unless `WHATSAPP_REAL_CUSTOMERS=true`
    (production only), only `WHATSAPP_TEST_NUMBERS` are read and answered, and nothing about anyone else is
    stored. **STOP** (or unsubscribe / opt out) suppresses the customer on every channel and closes their
    conversations; if they write again the Hub stays quiet and the enquiry waits for a person.
    Variables (Railway / `backend/.env` only): `WHATSAPP_PROVIDER=kapso`, `KAPSO_API_KEY`,
    `KAPSO_WEBHOOK_SECRET` (the same value as the webhook's secret key in Kapso), `WHATSAPP_PHONE_NUMBER_ID`,
    `WHATSAPP_BUSINESS_NUMBER`, `WHATSAPP_TEST_NUMBERS`, `WHATSAPP_REAL_CUSTOMERS`. Straight from Meta
    instead: `WHATSAPP_PROVIDER=meta` with `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_APP_SECRET` and
    `WHATSAPP_VERIFY_TOKEN`. Check with `python manage.py whatsapp_check` (sends nothing).

Not built yet: WhatsApp templates (needed after 24 hours), the 2-hour form reminder, name/email/consent on the form,
several makes or body type in one request, plate blurring in photos.

## W2 Portal chatbot

**In one line:** A salesperson asks the chatbot in plain words what is available, gets quoted option cards back, and sends them to a customer.

| | |
| --- | --- |
| Starts when | A salesperson types a question in the portal chatbot |
| Who | Salesperson, AI |
| Uses | F0 listing database, matching, Codeweavers |
| Build step | Step 3 |

### Steps

1. The salesperson types what the customer wants, for example "black CLA, automatic, under £25k, £3k deposit, 48 months".
2. The cheap LLM turns it into the same requirement fields as the enquiry form.
3. Matching runs exactly as in W1.
4. If deposit, term or mileage is missing, the chatbot asks the salesperson before getting quotes.
5. Codeweavers quotes are added and option cards are shown in the chat.
6. The salesperson picks the customer (from the CRM) and which options to send.
7. If the customer's WhatsApp window is open, or WhatsApp consent is recorded, it sends on WhatsApp; otherwise by email.
8. Everything is saved to the customer's record in the CRM.

### Rules

- Same matching, quotes and card rules as W1.
- Salespeople only see their own customers when choosing who to send to; James sees all.

## W3 Call-log form

**In one line:** When a customer phones James or a salesperson, the salesperson fills in a form with the same questions, and the system prepares quoted options to send, by email unless the customer agreed to WhatsApp.

| | |
| --- | --- |
| Starts when | A customer phones James or a salesperson |
| Who | Salesperson, system |
| Uses | Matching, Codeweavers, email, WhatsApp templates |
| Build step | Step 4 |

### Steps

1. During or after the call, the salesperson opens the call-log form and goes through each question with the customer.
2. The form has the same questions as the enquiry form, plus the customer's name, phone and email, and two consent ticks: "OK to send options by email" and "OK to send options by WhatsApp".
3. Saving creates the enquiry and requirement in the CRM, owned by that salesperson.
4. Matching, Codeweavers quotes and option cards run exactly as in W1.
5. The cards wait in the salesperson's inbox for approval.
6. On approval, options go by email by default. If WhatsApp consent was ticked, a WhatsApp template message is sent instead (or as well).

### Rules

- Email is the default because the customer has not messaged us on WhatsApp.
- WhatsApp only with recorded consent, and only using an approved template for the first message.

## W4 Out-of-hours voice AI

**In one line:** Out of hours, customers ring a number shown on the website. An AI voice agent asks the form questions, records consent, and leaves quoted options ready for the salesperson to approve in the morning.

| | |
| --- | --- |
| Starts when | A customer rings the out-of-hours number |
| Who | Customer, voice AI, salesperson (next morning) |
| Uses | Telephony, matching, Codeweavers, email |
| Build step | Step 7 |

### Steps

1. The website shows: "Out of hours? Call this number." The number only uses the voice AI outside opening hours.
2. The voice AI answers, says the call is recorded, and asks the enquiry form questions in a natural way.
3. It confirms the customer's email address and asks: "Can we send your options by email? And on WhatsApp?" The answers are recorded as consent.
4. The transcript, a short summary and the requirement are saved in the CRM.
5. The enquiry is assigned to James, or to the salesperson on the rota.
6. Matching, Codeweavers quotes and option cards run as in W1, ready in the inbox for the morning.
7. The salesperson approves; options go by email by default, or by WhatsApp template if the customer agreed.

### Call script outline

- Welcome and recording notice.
- What car are you looking for, and any must-haves?
- Maximum price or monthly budget, deposit, term, annual mileage.
- Part-exchange?
- Name, email, best number.
- Consent for email and WhatsApp.
- Close: "One of the team will send you options in the morning."

### Rules

- The voice AI never quotes prices, finance or availability.
- Callers are always told the call is recorded.

## W5 AI social posting

**In one line:** Live cars from the database become posts with a showroom background, captions for each platform and the time the car is available until, published to every Hart and salesperson account in one go.

| | |
| --- | --- |
| Starts when | Someone picks a live car to post, or chooses from the daily drafts |
| Who | James or a salesperson, AI |
| Uses | F0 listings and photos, Meta, TikTok, LinkedIn and YouTube connections |
| Build step | Step 7 |

### Account set-up

- **Facebook and Instagram:** every Facebook Page and Instagram account, including the salespeople's business pages, is added to the **Hart Group Meta business account**, with Hart Group as admin. One Meta connection then posts to all of them.
- **TikTok, LinkedIn and YouTube:** Meta does not cover these, so each account is connected separately (directly or through a posting service).
- Instagram accounts must be business or creator accounts. Facebook posting goes to Pages.

### Steps

1. Pick a live car from the database. Only cars with enough time left are offered (default 12 hours).
2. AI places the car's photo in the Hart showroom background. Only the background changes, never the car.
3. AI writes a caption for each platform, including the price and "Available until tomorrow 4pm" (or "Buy now: can sell at any time").
4. Each account's post includes that account's own WhatsApp number, so enquiries go to the right salesperson.
5. A person checks and approves. Nothing posts without approval.
6. Publish: Facebook and Instagram through the Hart Group Meta connection; TikTok, LinkedIn and YouTube through their own connections.
7. Status and link are saved for each account.
8. When the car ends or sells, its posts are flagged so they can be removed or marked sold.

### Rules

- Background only; the car is never altered.
- Check each sourcing platform allows its photos to be used in public posts.
- Expired cars are never posted.

## W6 CRM and campaign manager

**In one line:** The CRM holds every customer, enquiry and deal, including the Click Dealer history. The campaign manager filters them and sends approved messages that bring customers back.

| | |
| --- | --- |
| Starts when | Click Dealer import, any new enquiry, or the owner creating a campaign |
| Who | James, Ash and Scarlett (admin), salespeople, AI |
| Uses | Email, SMS, WhatsApp templates |
| Build step | Steps 6 to 7 |

### What goes into the CRM

| Source | What we keep |
| --- | --- |
| Click Dealer export (uploaded once, then as needed) | Customer details, car bought, salesperson, sale date, finance start, end and term, warranty, consent |
| WhatsApp enquiries (W1) | Conversation, form answers, options sent, outcome |
| Portal chatbot (W2) | Options sent |
| Call-log form (W3) | Form answers, consent, options sent |
| Voice AI (W4) | Transcript, summary, consent, options sent |
| Deals | Car, price, finance quote, extras, dates |

### Enquiry statuses

New > Form sent > Form received > Options ready > Options sent > Customer chose a car > Won or Lost. "Gone quiet" is set when options were sent and there has been no reply for 3 days.

### Campaign filters

| Filter | Who is included | Message idea | Default channel |
| --- | --- | --- | --- |
| Bought a car | Customers with a completed deal, a set number of days after purchase | Ask for a Google review | Email or SMS |
| Enquired, did not buy | Enquiries with options sent and no deal | "Are you still looking?" | Email; WhatsApp template if consented |
| Gone quiet | No reply for 3 days after options | New options or a nudge | WhatsApp template if consented, else email |
| Finance ending | Finance end date within the next 3 months | Time to change your car | Email or SMS |
| Custom | Any mix: make, model, salesperson, dates, location | Owner's choice | Owner's choice |

### Steps

1. Import the Click Dealer export into the CRM: match by phone and email, assign each customer to their salesperson, keep finance and warranty dates.
2. Every enquiry from W1 to W4 is saved automatically with its status.
3. The owner picks a filter (or builds a custom one) and sees how many customers it includes.
4. The consent filter (on by default) and the STOP list remove anyone who must not be contacted.
5. AI drafts the message in James's voice; the owner edits and approves.
6. Messages go in batches by email, SMS or WhatsApp template (only to customers with WhatsApp consent).
7. Replies are read: STOP removes the customer from every channel at once; "interested" creates a new enquiry for the original salesperson, which continues in W1 with the form link.

### Rules

- Consent required; every message includes an opt-out.
- WhatsApp campaigns use approved templates only, and only to customers who agreed.
- Admin users can view and export but cannot message customers.

## A Supporting features in the contract

These are in the signed scope and sit alongside the workflows above.

- **Owner dashboard:** enquiries, average time to options, options sent, deals this month against the target of 30, performance per salesperson, and anything needing attention.
- **Salesperson inbox and "My day":** new enquiries, forms received, option cards ready to send, customers who chose a car, gone-quiet customers.
- **Admin view (Ash and Scarlett):** deals won, extras sold, after-sales figures and CSV export.

## B Data dictionary

| Object | Key fields | Created in | Used in |
| --- | --- | --- | --- |
| Customer | name, phone, email, owner, consent (WhatsApp, email, SMS), STOP, finance end date, warranty date | W1 to W4, Click Dealer import | All |
| Enquiry | customer, channel, status, owner, created time | W1 to W4, campaign replies | W6, dashboard |
| Requirement | car wanted, max price, monthly, deposit, term, annual mileage, part-ex, fuel, gearbox, colour | Forms, chatbot, voice AI | Matching, quotes |
| Listing | platform, link, photos, make, model, trim, year, mileage, spec, buy price, sale type, end time, status | F0 | Matching, cards, posts |
| Option card | listing, selling price, quote, available-until text, status (ready, sent, expired) | W1 to W4 | Inbox, CRM |
| Quote | lender, monthly, deposit, term, APR, total, quote reference | Codeweavers | Option cards |
| Deal | customer, car, price, finance, extras, dates, won or lost reason | CRM | Campaigns, dashboard, admin |
| Campaign | filter, channel, message, approved by, recipients, replies | W6 | Dashboard |
| Post | car, image, captions, accounts, status per account, end time | W5 | Dashboard |
| Call | caller, time, transcript, summary, consent | W3, W4 | CRM |
| Sync log | platform, link, time, result | F0 | Audit |

## C Settings and defaults to confirm

These are the starting values. Each one is a setting, so it can change without new code.

| Setting | Default | Confirm with |
| --- | --- | --- |
| BCA and Manheim sync slots | 8.00am and 8.30am | Real alert times |
| Form reminder | Once, after 2 hours | James |
| Gone quiet | 3 days with no reply after options | James |
| Ending soon | Less than 24 hours left | James |
| Options per enquiry | Up to 5; salesperson chooses | James |
| Minimum time left to post a car | 12 hours | James |
| Review request | 14 days after purchase | James |
| Finance ending window | Next 3 months | James |
| Prep cost | £1,100 per car | James |
| Target margin | From the onboarding form | James |
