"""Streamlit UI for the AI Job Application Agent.  Run with: streamlit run app.py"""

from __future__ import annotations

import logging
from typing import Any

import streamlit as st

from src.agent import Agent, AgentEvent, AgentResult
from src.utils import (
    AppError,
    LLMClient,
    load_config,
    report_to_markdown,
    save_report,
    setup_logging,
)

setup_logging()
logger = logging.getLogger("job_agent.app")

st.set_page_config(page_title="AI Job Application Agent", page_icon="💼", layout="wide")

# Tool name -> checklist label shown while the agent works.
PROGRESS_LABELS = {
    "extract_resume_text": "Resume extracted",
    "extract_job_requirements": "Job requirements analyzed",
    "compare_skills": "Skills compared",
    "calculate_match_score": "Skill gaps identified",
    "generate_application_strategy": "Application strategy generated",
}
EVENT_ICONS = {"plan": "🧭", "tool_start": "→", "tool_done": "✓", "observation": "👁", "warning": "⚠️", "finish": "🏁"}


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
def render_sidebar(has_key: bool, model: str) -> None:
    with st.sidebar:
        st.header("💼 Job Application Agent")
        if has_key:
            st.success("Gemini API key loaded")
            st.caption(f"Model: `{model}`")
        else:
            st.error("Gemini API key missing. Add GEMINI_API_KEY to your .env file and restart.")
        st.markdown(
            "An AI agent that compares your resume with a job description. "
            "It **plans**, **calls tools**, **checks the results**, then writes your strategy."
        )
        st.subheader("Agent workflow")
        st.markdown(
            "1. Read goal and inputs\n"
            "2. Planner (LLM) picks the next tools\n"
            "3. Tools run (Python + LLM)\n"
            "4. Agent checks results, retries if thin\n"
            "5. Planner picks the next step\n"
            "6. Final structured report"
        )
        st.caption("Python computes matches and the score. The LLM handles language tasks. Nothing is invented.")


# --------------------------------------------------------------------------- #
# Results rendering
# --------------------------------------------------------------------------- #
def chips(items: list[str], empty: str) -> None:
    if items:
        st.markdown(" ".join(f"`{item.replace('`', '')}`" for item in items))
    else:
        st.caption(empty)


def render_report(result: AgentResult) -> None:
    report = result.report
    gaps = report["skill_gaps"]

    st.divider()
    st.header("Results")
    for warning in result.warnings:
        st.warning(warning)

    with st.container(border=True):
        left, right = st.columns([1, 2])
        left.metric("Job Match", f"{report['match_score']}%")
        left.caption(report["match_label"])
        right.progress(report["match_score"] / 100)
        labels = {"required": "Required skills", "preferred": "Preferred skills", "keywords": "Keywords"}
        cols = right.columns(max(len(report["score_breakdown"]), 1))
        for col, (name, part) in zip(cols, report["score_breakdown"].items()):
            col.metric(labels[name], f"{part['matched']}/{part['total']}", help=f"Weight in score: {part['weight_pct']}%")

    col_a, col_b = st.columns(2)
    with col_a, st.container(border=True):
        st.subheader("Resume Summary")
        st.write(report["resume_summary"])
    with col_b, st.container(border=True):
        st.subheader("Job Summary" + (f" — {report['role_title']}" if report["role_title"] else ""))
        st.write(report["job_summary"])

    col_c, col_d = st.columns(2)
    with col_c, st.container(border=True):
        st.subheader("Matching Skills")
        chips(report["matching_skills"], "No matching skills found.")
    with col_d, st.container(border=True):
        st.subheader("Skill Gaps")
        st.caption("Not mentioned in the resume. This does not mean you lack them.")
        st.markdown("**Required**")
        chips(gaps["required"], "None. Every required skill is mentioned.")
        st.markdown("**Preferred**")
        chips(gaps["preferred"], "None.")

    with st.container(border=True):
        st.subheader("Missing Keywords")
        chips(report["missing_keywords"], "No important keywords are missing.")
        st.caption("Use these only where they truthfully describe your work.")

    with st.container(border=True):
        st.subheader("Relevant Projects / Experience")
        if report["relevant_experience"]:
            for item in report["relevant_experience"]:
                st.markdown(f"**{item['item']}**: {item['why_relevant']}")
        else:
            st.caption("No clearly relevant projects or experience were identified in the resume.")

    with st.container(border=True):
        st.subheader("Resume Improvement Suggestions")
        for s in report["improvement_suggestions"] or []:
            st.markdown(f"- {s['suggestion']}" + (f"  \n  *Why: {s['reason']}*" if s["reason"] else ""))
        if not report["improvement_suggestions"]:
            st.caption("Suggestions are unavailable because the strategy step did not complete.")

    with st.container(border=True):
        st.subheader("Interview Preparation")
        for t in report["interview_prep"]:
            st.markdown(f"- **{t['topic']}** ({t['focus'] or 'role'}): {t['reason']}")
        if not report["interview_prep"]:
            st.caption("Interview topics are unavailable because that step did not complete.")

    with st.container(border=True):
        st.subheader("Action Plan")
        for step in report["action_plan"]:
            st.markdown(f"**Priority {step['priority']}** — {step['action']}  \n*{step['reason']}*")

    with st.expander("Agent Activity"):
        st.caption(f"{result.iterations} planning iteration(s). High-level actions only.")
        for event in result.events:
            st.text(f"{EVENT_ICONS.get(event.kind, '•')} {event.message}")

    markdown = report_to_markdown(report)
    st.download_button("Download report (.md)", markdown, file_name="job_application_report.md", mime="text/markdown")


# --------------------------------------------------------------------------- #
# Running the agent
# --------------------------------------------------------------------------- #
def run_agent(model: str, api_key: str, pdf_bytes: bytes, job_description: str) -> AgentResult | None:
    """Run the agent with a live checklist. Returns None (after showing an error) on failure."""
    error_message = ""
    result: AgentResult | None = None
    with st.status("Agent is working...", expanded=True) as status:
        checklist = st.empty()
        activity = st.empty()
        done: list[str] = []

        def on_event(event: AgentEvent) -> None:
            if event.kind == "tool_start":
                activity.caption(f"→ {event.message}...")
            elif event.kind == "tool_done" and event.tool in PROGRESS_LABELS:
                done.append(PROGRESS_LABELS[event.tool])
                checklist.markdown("\n\n".join(f"✓ {label}" for label in done))

        try:
            llm = LLMClient(api_key, model, on_wait=lambda msg: activity.caption(f"⏳ {msg}"))
            agent = Agent(llm, on_event=on_event)
            result = agent.run(job_description=job_description, resume_pdf=pdf_bytes)
        except AppError as exc:
            error_message = str(exc)
        except Exception:  # last line of defence: never show a traceback to the user
            logger.exception("Unexpected error while running the agent")
            error_message = "Something unexpected went wrong. Check the terminal for details and try again."

        if error_message:
            status.update(label="Analysis stopped", state="error", expanded=True)
        else:
            activity.empty()
            status.update(label="Analysis complete", state="complete", expanded=False)

    if error_message:
        st.error(error_message)
        return None
    return result


def main() -> None:
    config = load_config()
    render_sidebar(config.has_api_key, config.model)

    st.title("AI Job Application Agent")
    st.write(
        "An AI agent that analyzes your resume against a job description and creates a "
        "personalized application strategy."
    )

    col_resume, col_job = st.columns(2)
    uploaded = col_resume.file_uploader("Resume (PDF)", type=["pdf"])
    job_description = col_job.text_area("Job description", height=220, placeholder="Paste the full job posting here...")

    if st.button("Analyze My Application", type="primary"):
        if not config.has_api_key:
            st.error("Gemini API key not found. Copy .env.example to .env, set GEMINI_API_KEY, and restart the app.")
        elif uploaded is None:
            st.error("Please upload your resume as a PDF.")
        elif not job_description.strip():
            st.error("Please paste a job description.")
        else:
            st.session_state["result"] = run_agent(config.model, config.api_key, uploaded.getvalue(), job_description)

    result: Any = st.session_state.get("result")
    if result is not None:
        render_report(result)
        save_clicked = st.button("Save report to outputs/ folder")
        if save_clicked:
            path = save_report(report_to_markdown(result.report))
            st.success(f"Saved to {path.name} in the outputs folder.")


main()
