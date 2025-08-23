"""
contract_pipeline_v3.py — Clean pipeline matching your exact 6-step spec (RAG-free)

Pipeline:
1) Infer jurisdiction + contract type from user prompt (GENERAL defaults if unclear)
2) Generate specific drafting guidelines + jurisdiction considerations (PRIVATE context)
3) Create an outline (sections + bullets) consistent with the guidelines
4) Draft first part (front matter + global definitions)
5) Draft the remaining sections in parallel, using (2) + (4) as context
6) Expert QC pass and a second pass to fix — THEN stream the final HTML

Notes
- No clarifying questions. If info is missing, keep language GENERAL (no numeric specifics or statute names unless user supplied)
- Streaming: only the final, post-QC HTML is streamed (per your spec)
- SSE-based streaming utility provided
- Minimal HTML sanitization applied before streaming
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from typing import Any, Dict, List, Tuple
import dotenv
dotenv.load_dotenv()
from logging_utils import jlog
from config import ( OPENAI_API_KEY, OPENAI_MODEL, OUTLINE_MIN_SECTIONS, SECTION_TARGET_WORDS, MAX_PARALLEL_SECTIONS, JOB_TTL_SECONDS, STREAM_CHARS_PER_EVENT, STREAM_DELAY_MS )

from openai import AsyncOpenAI


# ----------------------------- OpenAI Client -----------------------------
oai = AsyncOpenAI(api_key=OPENAI_API_KEY)

# ----------------------------- SSE helpers -----------------------------

def sse(event: str, data: str) -> str:
    msg = (
        f"event: {event}\n"
        + "\n".join(f"data: {line}" for line in data.splitlines())
        + "\n\n"
    )
    return msg

async def stream_html(queue, html: str):
    n = len(html)
    i = 0
    while i < n:
        j = min(i + STREAM_CHARS_PER_EVENT, n)
        snippet = html[i:j]
        await queue.put(sse("chunk", snippet))
        if STREAM_DELAY_MS:
            await asyncio.sleep(STREAM_DELAY_MS / 1000.0)
        i = j

# ----------------------------- HTML utils -----------------------------

def sanitize_html(html: str) -> str:
    # Minimal sanitization: drop script/style + inline handlers
    html = re.sub(r"<\s*(script|style)[^>]*>.*?<\s*/\s*\1\s*>", "", html, flags=re.I | re.S)
    html = re.sub(r" on[a-zA-Z]+=\".*?\"", "", html)
    html = re.sub(r" on[a-zA-Z]+='.*?'", "", html)
    return html

# ----------------------------- OpenAI helpers -----------------------------

async def chat_json(messages: List[Dict[str, str]], *, temperature: float = 0.2, max_tokens: int | None = None, attempts: int = 2) -> Dict[str, Any]:
    last = None
    for k in range(attempts):
        try:
            res = await oai.chat.completions.create(
                model=OPENAI_MODEL,
                temperature=temperature,
                response_format={"type": "json_object"},
                max_tokens=max_tokens,
                messages=messages,
            )
            return json.loads(res.choices[0].message.content)
        except Exception as e:
            last = e
            await asyncio.sleep(0.4 * (k + 1))
    raise last

async def chat_text(messages: List[Dict[str, str]], *, temperature: float = 0.3, max_tokens: int | None = None) -> str:
    res = await oai.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=messages,
    )
    return res.choices[0].message.content or ""

# ----------------------------- Stage 1 — Infer type & jurisdiction -----------------------------

async def stage1_infer(user_prompt: str) -> Dict[str, Any]:
    system = (
        "You are a contracts lawyer. Infer minimal variables from a free-text brief.\n"
        "Do not ask questions. If unspecified, default to GENERAL placeholders.\n\n"
        "Return ONLY JSON keys: {\"title\":str,\"contract_type\":str,\"jurisdiction\":str,\"parties\":[str,str]}.\n"
        "Rules:\n"
        "- If the brief clearly names a contract (e.g., NDA, Terms of Service), preserve it; else use 'Agreement'.\n"
        "- Jurisdiction: use what is explicitly given; else 'Applicable Law'.\n"
        "- Parties: prefer role nouns when obvious (e.g., Provider/Customer), else ['Party A','Party B'].\n"
    )
    user = f"Brief:\n{user_prompt}\n\nReturn ONLY the JSON."
    data = await chat_json([
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], temperature=0.1, max_tokens=400)

    # Normalize
    parts = data.get("parties") or ["Party A", "Party B"]
    if len(parts) < 2:
        parts = (parts + ["Party B"])[:2]
    return {
        "title": data.get("title") or "Agreement",
        "contract_type": data.get("contract_type") or "Agreement",
        "jurisdiction": data.get("jurisdiction") or "Applicable Law",
        "parties": parts,
    }

# ----------------------------- Stage 2 — Guidelines (PRIVATE) -----------------------------

async def stage2_guidelines(contract_type: str, jurisdiction: str) -> Dict[str, Any]:
    """Generate PRIVATE drafting guidelines + jurisdiction considerations as HTML + a short notes string."""
    system = (
        "You are a senior contracts lawyer. Produce PRIVATE drafting guidance as JSON.\n"
        "No questions. Keep guidance general; include jurisdiction considerations without naming statutes unless the brief explicitly included them.\n"
        "Return ONLY JSON: {\"html\":str,\"notes\":str}.\n"
        "'html' must be ONE <section> fragment with <h2>Guidelines</h2> and subheads (Scope, Payment, Data/Security, IP, Confidentiality, Indemnities, Liability, Disputes, Boilerplate).\n"
        "'notes' ≤ 600 chars summarizing key allocations to keep consistent.\n"
    )
    user = (
        f"Contract Type: {contract_type or 'Agreement'}\n"
        f"Jurisdiction: {jurisdiction or 'Applicable Law'}\n"
        "Generate neutral guidance and venue-specific considerations phrased generally (e.g., 'under applicable law in the named venue')."
    )
    data = await chat_json([
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], temperature=0.25, max_tokens=1200)
    return {"html": data.get("html", ""), "notes": data.get("notes", "")}

# ----------------------------- Stage 3 — Outline -----------------------------

async def stage3_outline(contract_type: str, jurisdiction: str, guidelines_html: str, user_prompt: str) -> Dict[str, Any]:
    system = (
        "You are a legal architect. Create an outline that follows provided guidelines.\n"
        "Return ONLY JSON: {\"sections\":[{\"number\":str,\"title\":str,\"target_words\":int,\"bullets\":[str,...]}...]}.\n"
        "Rules: 10–16 sections; preserve neutral naming; no placeholders; no statute names; centralize renewal in 'Term and Termination'.\n"
    )
    user = (
        f"Contract Type: {contract_type or 'Agreement'}\n"
        f"Jurisdiction: {jurisdiction or 'Applicable Law'}\n"
        f"Guidelines (HTML):\n{guidelines_html}\n\n"
        f"User brief (context only):\n{user_prompt}\n"
    )
    data = await chat_json([
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], temperature=0.2, max_tokens=2000)

    sections = data.get("sections") or []
    if len(sections) < OUTLINE_MIN_SECTIONS:
        # pad with common sections keeping general style
        base = [
            {"title": "Definitions", "target_words": 280},
            {"title": "Scope of Agreement", "target_words": 300},
            {"title": "Fees and Payment", "target_words": 260},
            {"title": "Confidentiality", "target_words": 260},
            {"title": "Intellectual Property", "target_words": 260},
            {"title": "Data Protection and Security", "target_words": 280},
            {"title": "Warranties and Disclaimers", "target_words": 240},
            {"title": "Indemnities", "target_words": 240},
            {"title": "Limitation of Liability", "target_words": 240},
            {"title": "Term and Termination", "target_words": 240},
            {"title": "Governing Law and Dispute Resolution", "target_words": 220},
            {"title": "General Provisions", "target_words": 220},
        ]
        existing_titles = {s.get("title", "").strip().lower() for s in sections}
        sections.extend([s for s in base if s["title"].strip().lower() not in existing_titles])
    for i, s in enumerate(sections):
        s.setdefault("number", f"{i+1}.")
        s.setdefault("bullets", [])
    return {"sections": sections}

# ----------------------------- Stage 4 — First Part -----------------------------

async def stage4_first_part(title: str, contract_type: str, jurisdiction: str, parties: List[str], sections: List[Dict[str, Any]]) -> Dict[str, str]:
    system = (
        "You are a senior drafter. Return ONLY JSON {\"html\":str,\"context\":str}.\n"
        "'html' must contain two fragments: <section id='front-matter'> and <section id='global-definitions'>.\n"
        "- Keep wording GENERAL (no numeric specifics unless present in the brief).\n"
        "- No statute names unless present in the brief.\n"
        "'context' is ≤ 1000 chars summary of defined capitalized terms and drafting constraints (renewal centralization, etc.).\n"
    )
    parties = parties or ["Party A", "Party B"]
    user = (
        f"Title: {title or 'Agreement'}\n"
        f"Contract Type: {contract_type or 'Agreement'}\n"
        f"Jurisdiction: {jurisdiction or 'Applicable Law'}\n"
        f"Parties: {parties[0]} and {parties[1]}\n"
        "Anticipated Sections:\n" + "\n".join(f"- {s['number']} {s['title']}" for s in sections)
    )
    data = await chat_json([
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], temperature=0.2, max_tokens=2000)
    return {"html": data.get("html", ""), "context": data.get("context", "")}

# ----------------------------- Stage 5 — Section drafting (parallel) -----------------------------

async def stage5_section_worker(i: int, s: Dict[str, Any], *, title: str, contract_type: str, jurisdiction: str, parties: List[str], guidelines_html: str, first_part_html: str, shared_context: str) -> Tuple[int, str]:
    system = (
        "Draft ONE section as valid HTML fragment.\n"
        "Start with <h2>{number} {title}</h2>. Use <p>, <ol>, <ul>, optional <h3>.\n"
        "No placeholders like [insert]. No statute names unless present in the brief.\n"
        "Keep content GENERAL (no numeric specifics) unless clearly implied by the brief.\n"
        "Centralize renewal rules in 'Term and Termination' only.\n"
    )
    bullets_json = json.dumps(s.get("bullets") or [], ensure_ascii=False)
    user = (
        f"Agreement Title: {title}\n"
        f"Contract Type: {contract_type}\n"
        f"Jurisdiction: {jurisdiction or 'Applicable Law'}\n"
        f"Parties: {(parties or ['Party A','Party B'])[0]} and {(parties or ['Party A','Party B'])[1]}\n"
        f"Section number: {s.get('number')}\n"
        f"Section title: {s.get('title')}\n"
        f"Target words (approx): {s.get('target_words', 260)}\n"
        "Guidelines (HTML; PRIVATE; do not copy):\n" + (guidelines_html or "") + "\n"
        "Opening & Definitions (HTML; authoritative; do not duplicate text):\n" + (first_part_html or "") + "\n"
        "Shared context (plain text; do not echo):\n" + (shared_context or "") + "\n"
        f"Guidance bullets: {bullets_json}\n"
    )
    html = await chat_text([
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], temperature=0.35, max_tokens=2200)
    return i, html

async def stage5_sections_parallel(title: str, contract_type: str, jurisdiction: str, parties: List[str], sections: List[Dict[str, Any]], guidelines_html: str, first_part_html: str, shared_context: str) -> List[str]:
    sem = asyncio.Semaphore(MAX_PARALLEL_SECTIONS)
    results: Dict[int, str] = {}

    async def run_one(i: int, s: Dict[str, Any]):
        async with sem:
            try:
                idx, html = await stage5_section_worker(
                    i, s,
                    title=title, contract_type=contract_type, jurisdiction=jurisdiction,
                    parties=parties, guidelines_html=guidelines_html, first_part_html=first_part_html,
                    shared_context=shared_context,
                )
            except Exception as e:
                html = f"<h2>{s.get('number')} {s.get('title')}</h2><p><strong>Error:</strong> {e}</p>"
                idx = i
            results[idx] = html

    tasks = [asyncio.create_task(run_one(i, s)) for i, s in enumerate(sections)]
    await asyncio.gather(*tasks)
    return [results[i] for i in range(len(sections))]

# ----------------------------- Stage 6 — QC & Fix -----------------------------

async def stage6_qc_and_fix(full_html: str, contract_type: str, jurisdiction: str) -> str:
    system_eval = (
        "You are an expert contracts reviewer. Evaluate the HTML contract for structure, coherence, defined terms consistency, and missing essentials.\n"
        "Return ONLY JSON {\"issues\":[str,...],\"should_fix\":bool}. Do not include the contract text.\n"
    )
    user_eval = (
        f"Contract Type: {contract_type or 'Agreement'}\n"
        f"Jurisdiction: {jurisdiction or 'Applicable Law'}\n"
        "Contract HTML to evaluate follows:\n" + full_html
    )
    review = await chat_json([
        {"role": "system", "content": system_eval},
        {"role": "user", "content": user_eval},
    ], temperature=0.1, max_tokens=1800)

    if not review.get("should_fix", True):
        return full_html

    system_fix = (
        "You are an expert contracts drafter. You will fix the given HTML contract in a single pass.\n"
        "Rules: keep language GENERAL unless the brief included specifics; preserve headings and numbering;\n"
        "ensure renewal is centralized; avoid statute names; ensure defined terms consistency; no placeholders; valid HTML only.\n"
        "Output ONLY the corrected HTML fragment (no JSON, no commentary).\n"
    )
    user_fix = (
        f"Contract Type: {contract_type or 'Agreement'}\n"
        f"Jurisdiction: {jurisdiction or 'Applicable Law'}\n"
        f"Known issues: {json.dumps(review.get('issues', []))}\n"
        "Original HTML follows (fix inline):\n" + full_html
    )
    fixed = await chat_text([
        {"role": "system", "content": system_fix},
        {"role": "user", "content": user_fix},
    ], temperature=0.25, max_tokens=8000)
    return fixed or full_html

# ----------------------------- Orchestrator -----------------------------

class Job:
    """Minimal job structure expected by the orchestrator. Provide .id, .prompt, .queue, .cancel."""
    def __init__(self, job_id: str, prompt: str):
        self.id = job_id
        self.prompt = prompt
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.cancel = asyncio.Event()

async def delayed_delete(job: Job, registry: Dict[str, Job]):
    await asyncio.sleep(JOB_TTL_SECONDS)
    registry.pop(job.id, None)

async def run_job(job: Job, jobs_registry: Dict[str, Job]):
    try:
        await job.queue.put(sse("start", json.dumps({"job_id": job.id})))

        # 1) Infer
        vars1 = await stage1_infer(job.prompt)
        await job.queue.put(sse("variables", json.dumps(vars1)))

        # 2) Guidelines (PRIVATE)
        guide = await stage2_guidelines(vars1["contract_type"], vars1["jurisdiction"])
        await job.queue.put(sse("progress", "guidelines_ready"))

        # 3) Outline
        outline = await stage3_outline(vars1["contract_type"], vars1["jurisdiction"], guide["html"], job.prompt)
        await job.queue.put(sse("outline", json.dumps(outline)))

        # 4) First part
        first = await stage4_first_part(vars1["title"], vars1["contract_type"], vars1["jurisdiction"], vars1["parties"], outline["sections"])
        await job.queue.put(sse("progress", "first_part_ready"))

        # 5) Sections (parallel, but do not stream yet)
        section_html_list = await stage5_sections_parallel(
            vars1["title"], vars1["contract_type"], vars1["jurisdiction"], vars1["parties"],
            outline["sections"], guide["html"], first["html"], first["context"],
        )
        await job.queue.put(sse("progress", "sections_done"))

        # Merge all parts
        full_html = first["html"] + "\n" + "\n".join(section_html_list)

        # 6) QC then Fix
        fixed_html = await stage6_qc_and_fix(full_html, vars1["contract_type"], vars1["jurisdiction"])

        # Stream final HTML only now
        final_html = sanitize_html(fixed_html)
        await stream_html(job.queue, final_html)
        await job.queue.put(sse("done", ""))

    except asyncio.CancelledError:
        await job.queue.put(sse("error", "Generation cancelled"))
        await job.queue.put(sse("done", ""))
    except Exception as e:
        await job.queue.put(sse("error", f"Internal error: {e}"))
        await job.queue.put(sse("done", ""))
    finally:
        asyncio.create_task(delayed_delete(job, jobs_registry))
