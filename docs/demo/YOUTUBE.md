# Demo video: YouTube upload kit

| File | Use |
|---|---|
| `Rika_Demo.mp4` | The video (1080p30 H.264, AAC stereo, 4:20, narrated, captions burned in) |
| `thumbnail.jpg` | Custom thumbnail (1280×720) |
| `captions.en.srt` | Optional English subtitle track (lets YouTube auto-translate) |

**Upload:** YouTube Studio → *Create* → *Upload videos* → `Rika_Demo.mp4`. Paste the title and description below, set the thumbnail, choose **Unlisted** (anyone with the link can watch) or **Public**, and publish. Then put the link into the *Submission* table of the root `README.md` and the header table of `docs/TECHNICAL_DESIGN.md`. Custom thumbnails need a phone-verified YouTube account.

---

## Title

Rika: AI Expense & Reimbursement Agent | AI Innovation Lab demo

## Description

Rika is an AI agent that turns a pile of receipts into a submission-ready expense claim. Employees drop photos, screenshots or PDFs of their bills. Rika reads each document with a vision-language model, double-checks the reading with deterministic rules, applies company policy (limits, non-reimbursable items, currency conversion), catches duplicates, writes the claim's remarks, and asks only the questions it can't answer itself. The claim then goes through manager approval to payout.

In this demo:
• 7 receipts from a Bengaluru business trip, read by Google's Gemma 3 (4B) running locally on Ollama. This is a real run, shown as a 7× time-lapse.
• The hotel is capped at the lodging limit, craft beer is deducted from the dinner bill, a duplicate cab receipt is detected, and a phone photo of a café bill is read.
• Two one-click questions instead of a form → 100 % readiness → submit → manager approval → payout, with live notifications.
• The AI engine switches at runtime between Ollama, Claude and an offline rules engine.

Chapters
0:00 Intro & the problem
0:28 How it works
0:52 Sign in & dashboard
1:05 Drop the receipts
1:19 Live AI pipeline (7x time-lapse, local Gemma 3 4B)
1:46 Hotel cap, beer deduction & duplicate detection
2:13 Only the questions that matter
2:31 Chat with the agent
2:43 Submit to finance
2:57 Manager approval
3:20 Payout & audit trail
3:36 Pluggable AI engines
3:49 Under the hood

Source code and technical design document: <add your GitHub repository URL>
Track: AI Innovation Lab · Built by Sunil Gurjar
Stack: Angular 21 · FastAPI · Pydantic v2 · Ollama · Claude · server-sent events · 1,367 unit tests

## Tags

AI agent, expense management, reimbursement, receipt OCR, vision language model, Ollama, Gemma 3, Claude, FastAPI, Angular, hackathon, AI Innovation Lab
