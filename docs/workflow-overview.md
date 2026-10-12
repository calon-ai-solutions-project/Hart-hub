# How Hart Hub works

*Workflow overview: a two-page guide for anyone joining the project.*

**In one sentence:** Hart Hub keeps a fresh daily database of cars from the trade platforms, turns every customer enquiry into ready-to-send options with real finance quotes, lets a salesperson approve and send them on WhatsApp, and brings customers back through social posts and campaigns.

## 1. Platform sync: the car database

Every day, at a set time for each platform (Motorway 4.45pm, Carwow 5.15pm, BCA and Manheim to confirm), the system collects the cars from Hart's saved-search alerts on BCA, Motorway, Carwow and Manheim: photos, link, details, buy price and the time the car stops being available. It works out prep cost, a suggested selling price and the margin. Cars disappear automatically when their time runs out.

## 2. Deal sourcing from WhatsApp: the main workflow

A customer messages James or a salesperson on their own WhatsApp number. AI spots that it is a car enquiry and sends a short form (car wanted, price, deposit, term, mileage, part-exchange). When it comes back, the system finds matching cars, gets a Codeweavers finance quote for each, and builds up to five option cards with photos, price, finance and "this deal ends at…". The cards wait in the salesperson's inbox; they choose which to send, approve, and it goes from their own number. When the customer picks a car, the deal starts.

## 3. Portal chatbot

A salesperson asks in plain words, for example "black CLA, automatic, under £25k". The chatbot finds the cars, adds quotes and shows the option cards, ready to send to a customer.

## 4. Call-log form

When a customer phones, the salesperson fills in the same form during the call, including whether the customer agrees to email or WhatsApp. Options are prepared the same way and sent by email, or on WhatsApp only if the customer agreed.

## 5. Out-of-hours voice AI

Out of hours, customers ring a number on the website. An AI voice agent asks the form questions and records consent. Options are ready for the salesperson to approve first thing in the morning.

## 6. AI social posting

Live cars become posts: the car placed in the Hart showroom background, a caption for each platform and the time it is available until. Facebook and Instagram post through the Hart Group Meta account (all pages added under it); TikTok, LinkedIn and YouTube connect separately. A person approves every post.

## 7. CRM and campaign manager

Every customer, enquiry and deal is kept, including the Click Dealer history with finance and warranty dates. Filters find who to contact: bought a car (ask for a review), enquired but didn't buy, gone quiet, or finance ending soon. Messages are approved before sending, and replies become new enquiries.

## Rules that never change

- **WhatsApp is the source of truth.** All enquiries arrive there, and replies go from the same number the customer used.
- **A person approves** everything a customer receives or sees posted.
- **Finance comes only from Codeweavers quotes.** No finance applications from the Hub.
- **Every option shows when it ends.** Expired cars are never sent or posted.
- **Buy price and margin are staff only.**
- **People who didn't message us get email**, unless they agreed to WhatsApp. STOP removes anyone from every channel.
- **The platform sync follows the contract:** approved platforms only, alert listings only, once a day, and it stops at any CAPTCHA or warning.

*For full detail, read [master-workflow.md](master-workflow.md).*
