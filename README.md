# AI Job Application Agent

An AI agent that analyzes your resume against a job description and creates a personalized application strategy.

Upload a resume PDF, paste a job description, and the agent produces:

- Job-match score (calculated, never random)
- Resume summary and job summary
- Matching skills, skill gaps and missing keywords
- Relevant projects/experience from *your* resume
- Specific resume improvement suggestions
- Interview preparation topics
- A prioritized action plan

## Why This Is an Agent

A simple chatbot is `User -> Prompt -> LLM -> Response`: one call, no control over what happens.

This project is a loop with **state, tools and decisions**:

| Chatbot | This agent |
|---|---|
| One prompt, one answer | Repeated plan -> act -> observe cycles |
| LLM does everything, including math | Python does exact work, the LLM does language work |
| No memory of intermediate results | Shared `context` dictionary holds every tool result |
| Fails silently or hallucinates | Validates outputs, retries thin results, degrades gracefully |
| Unbounded | Hard `MAX_ITERATIONS` limit |

The LLM **chooses which tools to run next**. Python checks that the choice is valid (tool exists, inputs are ready, not already run) and overrides it if not.

## Architecture

```
                         +---------------------------+
   Resume PDF  --------> |        Streamlit UI       |
   Job description ----> |          (app.py)         |
                         +-------------+-------------+
                                       |
                                       v
                         +---------------------------+
                         |   Agent (src/agent.py)    |
                         |  context = shared memory  |
                         |  loop <= MAX_ITERATIONS   |
                         +------+-------------+------+
                                |             |
                   plan / next  |             | run tools, store results
                   step choice  v             v
                    +----------------+  +-----------------------------+
                    | LLM Planner    |  | Tools (src/tools.py)        |
                    | (prompts.py)   |  |  Python: extract_resume_text|
                    +----------------+  |          compare_skills     |
                                        |          calculate_match_... |
                                        |  LLM:    analyze_resume     |
                                        |          extract_*_skills   |
                                        |          generate_*         |
                                        +-----------------------------+
                                                     |
                                                     v
                                        Final structured report -> UI
```

## Agent Workflow

```
Goal
  |
Planning            LLM sees the goal, tool list and state, and picks the next tools
  |
Tool Selection      Python validates: only "ready" tools, no repeats
  |
Tool Execution      Python tools (exact) and LLM tools (language)
  |
Observation         Agent checks the result; a thin extraction is retried once
  |
Next Decision       Loop again until no tools are left or MAX_ITERATIONS is hit
  |
Final Response      Structured report (score, gaps, plan, ...)
```

A typical run takes 4-5 iterations:

1. `extract_resume_text`
2. `analyze_resume`, `extract_resume_skills`, `analyze_job_description`, `extract_job_requirements`
3. `compare_skills`
4. `calculate_match_score`
5. `generate_application_strategy`, `generate_interview_prep`

### How the match score works

```
score = 100 x (0.65 x required coverage + 0.20 x preferred coverage + 0.15 x keyword coverage)
```

Coverage = matched / total. Categories with no items are dropped and the weights rescaled. A skill counts as present if the LLM extracted it from the resume **or** it appears as a whole word in the resume text (aliases like `JS`/`JavaScript` and `Postgres`/`PostgreSQL` are handled).

### Accuracy rules built into the code

- Prompts forbid inventing experience and distinguish "not mentioned in the resume" from "the candidate lacks it".
- Suggested "relevant projects" are checked against the resume text; anything not found is dropped.
- Suggestions say "if you genuinely have used X ...", never "add X".
- Text inside the resume / job description is treated as data, not instructions (basic prompt-injection hygiene).

## Tech Stack

- Python 3.12+
- Streamlit (UI)
- Google Gemini API via the official `google-genai` SDK (JSON output mode)
- pypdf (PDF text extraction)
- python-dotenv (configuration)
- pytest (tests)

No agent frameworks (LangChain, LangGraph, CrewAI, ...). The agent loop itself is a few dozen lines of plain Python in `src/agent.py` (`Agent.run`).

## Project Structure

```
ai-job-application-agent/
├── app.py                 # Streamlit UI
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── src/
│   ├── agent.py           # Agent class: planning loop, tool registry, error handling
│   ├── tools.py           # Tool functions (deterministic + LLM-assisted)
│   ├── resume_parser.py   # PDF -> text, resume text validation
│   ├── prompts.py         # All prompts
│   └── utils.py           # Config, errors, JSON validation, Gemini client, report export
├── outputs/               # Saved reports
└── tests/
    ├── test_tools.py      # Scoring, comparison, validation, JSON handling
    └── test_agent.py      # Agent loop with a fake LLM (no API key needed)
```

## Installation (Windows)

```
git clone <repository-url>
cd ai-job-application-agent

python -m venv venv
venv\Scripts\activate

pip install -r requirements.txt

copy .env.example .env
```

Create a free key at https://aistudio.google.com/apikey, then open `.env` in a text editor and add it:

```
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-3.5-flash-lite
```

`GEMINI_MODEL` is optional (default `gemini-3.5-flash-lite`). Flash-Lite models have the largest free daily quota; full Flash models allow far fewer requests per day on the free tier. One analysis uses roughly 10-13 API calls. Never commit `.env`; it is in `.gitignore`.

## Running

```
streamlit run app.py
```

Run the tests (no API key required):

```
pytest
```

## Example Usage

1. Upload a **text-based** PDF resume (not a scanned image).
2. Paste a complete job posting, including requirements and preferred qualifications.
3. Click **Analyze My Application**.

Good test: a resume listing Python, Flask, SQL and Git against a "Backend Engineer" posting that requires Python, SQL, Docker and REST APIs. Expect Docker to appear under skill gaps as *not mentioned in the resume*, and an action plan that tells you to add it only if you have truly used it.

The **Agent Activity** expander shows the high-level steps the agent took. No hidden reasoning is exposed.

## Error Handling

| Situation | Behaviour |
|---|---|
| Missing API key | Clear message in sidebar and on click |
| Invalid, empty, encrypted or scanned PDF | Friendly error, no traceback |
| Empty or very short job description | Validation error before any API call |
| Per-minute rate limit / 5xx error | Automatic wait-and-retry (up to 3 times), progress shown in the UI |
| Daily free quota used up | Clear message; resets at midnight Pacific time |
| Network error / bad key / unknown model | Short, specific message |
| Malformed LLM JSON | One automatic retry, then handled error |
| Optional tool fails (e.g. interview prep) | Warning shown, rest of the report still delivered |
| Critical tool fails | Agent stops with a clear message |
| Unexpected exception | Logged to the terminal, generic message in the UI |

## How I Would Explain This Project in an Interview

**The 60-90 second version:**

> "I built an AI agent that helps with job applications. You upload a resume and paste a job description, and it tells you how well you match, what is not mentioned in your resume, and what to do about it.
>
> What makes it an agent rather than a chatbot is the loop. The agent keeps a shared context, and at each step an LLM planner looks at what has been done and chooses which tools to run next. The tools are plain Python functions. Some are deterministic, like PDF extraction, the skill comparison and the match score, so those numbers are exact and reproducible. Others use the LLM for language tasks like summarising the resume or writing the action plan.
>
> After each tool the agent checks the result. For example, if skill extraction returns suspiciously few skills, it retries once with a stricter prompt. There is a hard iteration limit to prevent infinite loops, and optional tools can fail without breaking the whole report. I also added guardrails against hallucination: the LLM output is validated, and any 'relevant project' it suggests must actually appear in the resume text. I built it without LangChain so I understand every part of it."

**Common questions**

- **What is an AI agent?** A system where an LLM repeatedly decides what action to take next, runs tools, observes the results and continues until a goal is met, instead of producing one answer.
- **Why did I use tools?** LLMs are good at language but unreliable at exact work. Tools give exact, testable results (set intersection, scoring) and let the agent act on real data like a PDF.
- **Which parts use the LLM?** Planning the next step, summarising the resume and job, extracting skills and requirements, and writing suggestions, interview topics and the action plan.
- **Which parts are deterministic?** PDF extraction, text validation, skill normalisation, matching and missing skills, the match score, JSON validation, and the anti-fabrication check.
- **How does the agent decide what to do?** Python works out which tools are *ready* (their inputs exist and they have not run). The LLM planner picks from those. If it picks something invalid, Python overrides it.
- **How do I prevent infinite loops?** `MAX_ITERATIONS` is a hard cap, tools never run twice, a failed tool is never retried by the loop, and the loop ends when no tool is ready.
- **What happens if a tool fails?** The error is caught. Critical tools (extraction, comparison, scoring) stop the run with a clear message. Optional tools add a warning and the report is built without them; the action plan even has a deterministic fallback.
- **Why not LangChain/LangGraph?** The workflow is small and fixed, so a framework would hide the parts I wanted to learn and show. For larger systems with many tools, persistence or multi-agent flows, a framework would make sense.

## Limitations

- Scanned (image-only) PDFs are not supported; there is no OCR.
- Skill matching is based on names and a small alias table, not deep semantic similarity.
- Scores measure keyword/skill coverage, not overall candidate quality.
- Very long resumes or postings are truncated to keep cost bounded.

## License

MIT. Use it, learn from it, and improve it.

## Privacy note

On Gemini's free tier, Google may use submitted content to improve its products. Your resume contains personal data, so consider removing your phone number and address before uploading, or use a paid key.
