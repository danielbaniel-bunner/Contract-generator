import asyncio
import json
import time
from typing import Any, Dict, List, Optional

from fastapi.responses import StreamingResponse  # only for type hints; not used directly
from openai import AsyncOpenAI

from logging_utils import jlog
from models import Job
from config import (
    OPENAI_API_KEY, OPENAI_MODEL,
    OUTLINE_MIN_SECTIONS, SECTION_TARGET_WORDS, MAX_PARALLEL_SECTIONS,
    JOB_TTL_SECONDS, STREAM_CHARS_PER_EVENT, STREAM_DELAY_MS,
    INCLUDE_GLOBAL_CONTEXT_IN_WORKERS, VALIDATION_ENABLED,
    build_policy_params, policy_params_to_line, REVERSE_ENGINEERING_GUIDANCE
)

# OpenAI client
oai = AsyncOpenAI(api_key=OPENAI_API_KEY)

# ------------- Utilities -------------
def sse(event: str, data: str) -> str:
    msg = f"event: {event}\n" + "\n".join(f"data: {line}" for line in data.splitlines()) + "\n\n"
    jlog("sse.build", event=event, data_len=len(data), msg_len=len(msg))
    return msg

def html_escape(t: str) -> str:
    out = (t.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
             .replace('"',"&quot;").replace("'","&#39;"))
    return out

async def delayed_delete(job_id: str, jobs: Dict[str, Job], seconds: int = JOB_TTL_SECONDS):
    jlog("cleanup.schedule", job_id=job_id, ttl_seconds=seconds)
    await asyncio.sleep(seconds)
    removed = jobs.pop(job_id, None) is not None
    jlog("cleanup.removed", job_id=job_id, removed=removed)

async def stream_html(job: Job, html: str):
    jlog("stream_html.start", job_id=job.id, html_len=len(html))
    n = len(html)
    if n == 0:
        jlog("stream_html.empty", job_id=job.id)
        return
    i = 0
    while i < n:
        if job.cancel.is_set():
            jlog("stream_html.cancelled", job_id=job.id, i=i)
            return
        j = min(i + STREAM_CHARS_PER_EVENT, n)
        snippet = html[i:j]
        await job.queue.put(sse("chunk", snippet))
        if STREAM_DELAY_MS > 0:
            await asyncio.sleep(STREAM_DELAY_MS / 1000.0)
        i = j
    jlog("stream_html.finish", job_id=job.id)

# ------------- OpenAI helpers -------------

async def get_outline(prompt: str) -> Dict[str, Any]:
    t0 = time.monotonic()
    jlog("outline.start", model=OPENAI_MODEL, min_sections=OUTLINE_MIN_SECTIONS, prompt_len=len(prompt))

    system = (
        "You are a senior contracts lawyer.\n\n"
        "Task\n"
        "- Read the user's free-text brief.\n"
        "- Infer:\n"
        "  • contract_type (e.g., SaaS ToS, MSA, NDA, DPA, Employment, Consulting, Privacy Policy, SOW, Licensing)\n"
        "  • governing_jurisdiction (normalize to a recognized legal system; if unclear, use 'Applicable Law')\n"
        "  • primary_parties (e.g., Provider vs Customer; Discloser vs Recipient; Licensor vs Licensee)\n"
        "- Produce ONLY JSON:\n"
        "{\n"
        '  "title": str,\n'
        '  "contract_type": str,\n'
        '  "jurisdiction": str,\n'
        '  "parties": [str, str],\n'
        '  "sections": [{"number":"1.","title":str,"bullets":[str,...]}, ...]\n'
        "}\n\n"
        "Global Rules (contract-agnostic)\n"
        f"- Minimum sections: {OUTLINE_MIN_SECTIONS}; number 1., 2., 3.\n"
        "- No bracket placeholders like [insert X]. If the user gave no numbers, propose neutral, widely-accepted defaults, stated plainly.\n"
        "- Keep foundational doctrines embedded within commercial sections; do NOT create stand-alone sections titled Offer/Acceptance, Consideration, Capacity/Legality, Definiteness unless the brief demands it.\n"
        "- Include (rename to fit contract_type if needed): Definitions; Scope/Services or Purpose; Fees/Payment; "
        "Term/Renewal/Termination (centralize any renewal logic); Confidentiality; IP & License/Ownership; "
        "Warranties/Disclaimers; Indemnities; Limitation of Liability; Data Protection/Security (if hosted/personal data is implicated); "
        "Force Majeure; Governing Law & Disputes; Boilerplate (Assignment, Notices, Severability, Amendment, Entire Agreement, Publicity, Survival, No Third-Party Beneficiaries).\n"
        "- Single source of truth: Renewal/termination lives only in the Term/Renewal/Termination section; other sections reference it by title. "
        "Governing Law appears only once (in Governing Law & Disputes).\n"
        "- Tailor section names to the inferred contract_type (e.g., NDA → Purpose, Confidentiality, Exclusions, Term, Remedies)."
    )
    user = f"Brief:\n{prompt}\n\nReturn ONLY the JSON object."

    try:
        res = await oai.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0.2,
            messages=[{"role":"system","content":system},{"role":"user","content":user}],
            response_format={"type":"json_object"},
        )
        data = json.loads(res.choices[0].message.content)
        dur_ms = int((time.monotonic() - t0) * 1000)
        jlog("outline.finish", duration_ms=dur_ms)
    except Exception as e:
        jlog("outline.error", error=str(e))
        raise

    title = data.get("title") or "Contract"
    sections = data.get("sections") or []
    for i, s in enumerate(sections):
        s.setdefault("number", f"{i+1}.")
        s.setdefault("title", f"Section {i+1}")
        s.setdefault("bullets", [])
    if len(sections) < OUTLINE_MIN_SECTIONS:
        extras = [
            "Intellectual Property & License/Ownership","Notices","Assignment","Force Majeure","Audit Rights",
            "Insurance","Subcontractors","Publicity","Export/Trade Compliance","Anti-Corruption",
            "Severability","Amendments","Entire Agreement"
        ]
        i0 = len(sections)
        for j, t in enumerate(extras[: OUTLINE_MIN_SECTIONS - i0]):
            sections.append({"number": f"{i0+j+1}.", "title": t, "bullets": []})

    out = {
        "title": title,
        "contract_type": data.get("contract_type", "Agreement"),
        "jurisdiction": data.get("jurisdiction", "Applicable Law"),
        "parties": data.get("parties", ["Party A", "Party B"]),
        "sections": sections
    }
    jlog("outline.normalize", title=out["title"], contract_type=out["contract_type"],
         jurisdiction=out["jurisdiction"], sections=len(sections))
    return out


async def build_shared_guidance_llm(
    contract_type: str,
    jurisdiction: str,
    parties: List[str],
    user_prompt: str,
) -> str:
    """
    Ask the LLM for a 'Shared Guidance' pack tailored to contract_type
    and jurisdiction. Returns one HTML <section>.
    """
    t0 = time.monotonic()
    jlog("llm.guidance.start", contract_type=contract_type, jurisdiction=jurisdiction)

    system = (
        "You are a senior contracts lawyer.\n\n"
        "Output:\n"
        "- A single 'Shared Guidance' pack as valid HTML <section>.\n"
        "- Structure:\n"
        "  <h2>Shared Guidance</h2>\n"
        "  <h3>Core Checklist</h3> …\n"
        "  <h3>Scope & License</h3> …\n"
        "  <h3>Payment & Renewal</h3> …\n"
        "  <h3>Data & Security</h3> …\n"
        "  <h3>IP & Work Product</h3> …\n"
        "  <h3>Indemnity & Liability</h3> …\n"
        "  <h3>Boilerplate</h3> …\n"
        "  <h3>Jurisdiction Considerations</h3> …\n"
        "  <h3>Assumptions</h3> …\n\n"
        "Rules:\n"
        "- Tailor to the inferred contract_type.\n"
        "- Use the jurisdiction context (e.g., 'Tel Aviv', 'New York', 'EU law') to highlight issues drafters typically face "
        "in that venue, but phrase them cautiously as 'under applicable [jurisdiction] law'.\n"
        "- Avoid citing specific statutes unless they are universally recognized (e.g., 'GDPR' when jurisdiction='EU').\n"
        "- Provide drafting heuristics: what must be explicit, what can be left flexible, what risks to watch for.\n"
        "- Do not copy contract text; provide *guidance*.\n"
        "- No placeholders like [insert X]; provide plain, neutral defaults where the user gave nothing.\n"
    )

    party_a = parties[0] if parties else "Party A"
    party_b = parties[1] if len(parties) > 1 else "Party B"

    user = (
        f"Contract Type: {contract_type}\n"
        f"Jurisdiction: {jurisdiction or 'Applicable Law'}\n"
        f"Primary Parties: {party_a} and {party_b}\n"
        "User brief:\n"
        f"{user_prompt}\n\n"
        "Produce the Shared Guidance section now."
    )

    res = await oai.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=0.25,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
    )
    html = res.choices[0].message.content or ""
    dur_ms = int((time.monotonic() - t0) * 1000)
    jlog("llm.guidance.finish", duration_ms=dur_ms, html_len=len(html))
    return html


async def get_main_first_part(
    title: str,
    contract_type: str,
    jurisdiction: str,
    parties: List[str],
    sections: List[Dict[str, Any]],
) -> Dict[str, str]:
    t0 = time.monotonic()
    jlog("main_first_part.start", title=title, contract_type=contract_type, jurisdiction=jurisdiction)

    party_a = parties[0] if parties else "Party A"
    party_b = parties[1] if len(parties) > 1 else "Party B"

    system = (
        "You are a senior contracts lawyer. Produce ONLY JSON with keys 'html' and 'context'.\n\n"
        "'html'\n"
        "- Two sections only:\n"
        "  (A) <section id=\"front-matter\">:\n"
        "      • <h1> title\n"
        "      • party roles\n"
        "      • jurisdiction label (use inferred jurisdiction or 'Applicable Law')\n"
        "      • a short recital confirming assent (e.g., clickwrap or signature) and consideration without naming statutes\n"
        "      • do NOT define terms here; keep definitions in the next section\n"
        "  (B) <section id=\"global-definitions\">:\n"
        "      • a compact, precise <dl> tuned to the inferred contract_type (e.g., Services, Deliverables, Customer Data, Effective Date, Term, Renewal, Confidential Information, Order Form, Support, SLA, Fees, Taxes)\n"
        "      • avoid placeholders; where the brief lacks numbers, state neutral defaults suited to the contract_type\n\n"
        "'context'\n"
        "- One paragraph (≤1200 chars) listing the key capitalized terms you just defined and summarizing: parties/roles, assent modality, consideration; "
        "and that renewal/termination logic will live only in the Term/Renewal/Termination section.\n"
        "- Do not include statute or case names."
    )

    user = (
        f"Contract Title: {title}\n"
        f"Contract Type: {contract_type}\n"
        f"Jurisdiction: {jurisdiction or 'Applicable Law'}\n"
        f"Parties: {party_a} and {party_b}\n"
        "Anticipated Sections:\n" + "\n".join(f"- {s['number']} {s['title']}" for s in sections)
    )

    try:
        res = await oai.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0.2,
            messages=[{"role":"system","content":system},{"role":"user","content":user}],
            response_format={"type":"json_object"},
        )
        data = json.loads(res.choices[0].message.content)
        html = data.get("html", "")
        context = (data.get("context", "") or "").strip()
        jlog("main_first_part.finish", html_len=len(html), context_len=len(context),
             duration_ms=int((time.monotonic() - t0) * 1000))
    except Exception as e:
        jlog("main_first_part.error", error=str(e))
        raise

    params = build_policy_params(jurisdiction)
    if params:
        params_line = policy_params_to_line(params)
        context = f"{context}\nPARAMS: {params_line}"
    return {"html": html, "context": context}


async def write_section(
    job_id: str,
    title: str,
    contract_type: str,
    jurisdiction: str,
    parties: List[str],
    number: str,
    sec_title: str,
    bullets: List[str],
    shared_guidance_html: str,
    main_first_part_html: str,
    shared_context: str = "",
) -> str:
    t0 = time.monotonic()
    jlog("section.start", job_id=job_id, number=number, title=sec_title, bullets=len(bullets))

    party_a = parties[0] if parties else "Party A"
    party_b = parties[1] if len(parties) > 1 else "Party B"

    system = (
        "Produce ONE contract section as valid HTML (fragment only).\n\n"
        "Drafting Rules (contract-agnostic)\n"
        f"- Begin with <h2>{number} {sec_title}</h2>.\n"
        f"- Aim ~{SECTION_TARGET_WORDS} words; plain, precise English.\n"
        "- Use <p>, <ol>, <ul>, <h3>. Number subclauses in-text.\n"
        "- NO <html>/<body> wrappers; NO links; NO placeholders like [insert X].\n"
        "- If the user did not provide a value and none is present in PARAMS, propose a conservative, industry-normal default that fits the contract_type; make it explicit (e.g., “within thirty (30) days”).\n"
        "- Single source of truth: reference 'Term/Renewal/Termination' for renewal logic; do not redefine. Governing Law appears only in 'Governing Law & Disputes'.\n"
        "- Keep capitalized terms consistent with Opening & Key Definitions; introduce new ones only if defined inline.\n"
        "- Keep Warranties, Indemnities, and Limitation of Liability logically distinct and non-overlapping.\n"
        "- Include Data/Security only if the subject matter implies hosted/personal data.\n"
        "- If ambiguity arises, choose the more conservative interpretation for enforceability.\n\n"
        "You are given authoritative context:\n"
        "- “Shared Guidance” (HTML): follow direction; do not copy verbatim.\n"
        "- “Opening & Key Definitions” (HTML): authoritative term set; do not duplicate.\n"
        "- Optional “Global Contract Context PARAMS”: reuse numbers/flags if present.\n"
        + REVERSE_ENGINEERING_GUIDANCE
    )

    context_blocks = ""
    if shared_guidance_html:
        context_blocks += "\nShared Guidance (HTML; do not copy verbatim):\n" + shared_guidance_html + "\n"
    if main_first_part_html:
        context_blocks += "\nOpening & Key Definitions (HTML; authoritative, do not duplicate):\n" + main_first_part_html + "\n"
    if INCLUDE_GLOBAL_CONTEXT_IN_WORKERS and shared_context:
        context_blocks += "\nGlobal Contract Context (plain text; do not echo):\n" + shared_context + "\n"

    user = (
        f"Contract Title: {title}\n"
        f"Contract Type: {contract_type}\n"
        f"Jurisdiction: {jurisdiction or 'Applicable Law'}\n"
        f"Parties: {party_a} and {party_b}\n"
        f"Section number: {number}\n"
        f"Section title: {sec_title}\n"
        f"Guidance bullets: {json.dumps(bullets, ensure_ascii=False)}\n"
        "Draft to fit the contract type and subject matter; use the context blocks but do not repeat their text."
        + context_blocks
    )

    try:
        res = await oai.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0.35,
            messages=[{"role":"system","content":system},{"role":"user","content":user}],
        )
        content = res.choices[0].message.content or ""
        jlog("section.finish", job_id=job_id, number=number,
             html_len=len(content), duration_ms=int((time.monotonic() - t0) * 1000))
        return content
    except Exception as e:
        jlog("section.error", job_id=job_id, number=number, error=str(e))
        return (
            f"<h2>{html_escape(number)} {html_escape(sec_title)}</h2>"
            f"<p><strong>Section generation error:</strong> {html_escape(str(e))}</p>"
        )


# ------------- Orchestrator -------------

async def run_job(job: Job, jobs_registry: Dict[str, Job]):
    jlog("job.run.start", job_id=job.id, prompt_len=len(job.prompt))
    full_contract_buf: List[str] = []

    try:
        # Intro + Outline
        outline = await get_outline(job.prompt)
        title = outline["title"]; contract_type = outline["contract_type"]
        jurisdiction = outline["jurisdiction"]; parties = outline["parties"]; sections = outline["sections"]
        jlog("job.outline.data", title=title, contract_type=contract_type,
             jurisdiction=jurisdiction, parties=parties, section_count=len(sections))
        items = "".join([f"<li>{html_escape(s['number'])} {html_escape(s['title'])}</li>" for s in sections])
        await job.queue.put(sse("chunk", f"<h2>Outline</h2>"
                                         f"<p><b>Contract Type:</b> {html_escape(contract_type)} | "
                                         f"<b>Jurisdiction:</b> {html_escape(jurisdiction)}</p>"
                                         f"<ol>{items}</ol><hr/>"))

        # Shared Guidance (LLM only)
        shared_guidance_html = await build_shared_guidance_llm(contract_type, jurisdiction, parties, job.prompt)
        jlog("job.shared_guidance.emitted", job_id=job.id, html_len=len(shared_guidance_html))

        # Main First Part (canonical)
        main_first = await get_main_first_part(title, contract_type, jurisdiction, parties, sections)
        main_first_html = main_first["html"]; main_context = main_first["context"]
        await stream_html(job, main_first_html)
        full_contract_buf.append(main_first_html)
        jlog("job.main_first_part.emitted", job_id=job.id, html_len=len(main_first_html), ctx_len=len(main_context))

        # Sections (parallel generate, ordered emit)
        sem = asyncio.Semaphore(MAX_PARALLEL_SECTIONS)
        results: Dict[int, str] = {}

        async def worker(i: int, s: Dict[str, Any]):
            async with sem:
                if job.cancel.is_set():
                    jlog("section.skip.cancelled", job_id=job.id, index=i)
                    return
                try:
                    html = await write_section(
                        job.id, title, contract_type, jurisdiction, parties,
                        s["number"], s["title"], s["bullets"],
                        shared_guidance_html=shared_guidance_html,
                        main_first_part_html=main_first_html,
                        shared_context=main_context,
                    )
                except Exception as e:
                    jlog("section.worker.error", job_id=job.id, index=i, error=str(e))
                    html = (
                        f"<h2>{html_escape(s['number'])} {html_escape(s['title'])}</h2>"
                        f"<p><strong>Section generation error:</strong> {html_escape(str(e))}</p>"
                    )
                results[i] = html
                jlog("section.worker.done", job_id=job.id, index=i, html_len=len(html))

        tasks = [asyncio.create_task(worker(i, s)) for i, s in enumerate(sections)]
        pending = set(tasks)
        next_to_emit = 0
        jlog("sections.spawned", job_id=job.id, count=len(tasks), parallel=MAX_PARALLEL_SECTIONS)

        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            jlog("sections.progress", job_id=job.id, done=len(done), pending=len(pending))

            emitted = 0
            while next_to_emit in results:
                html = results.pop(next_to_emit)
                full_contract_buf.append(html)
                await stream_html(job, html)
                emitted += 1
                next_to_emit += 1
            if emitted:
                jlog("sections.emitted", job_id=job.id, emitted=emitted, upto_index=next_to_emit - 1)
            if job.cancel.is_set():
                for t in pending:
                    t.cancel()
                jlog("job.cancel.flush", job_id=job.id)
                break

        # Flush leftovers if any
        for i in sorted(results.keys()):
            html = results[i]
            full_contract_buf.append(html)
            await stream_html(job, html)
        jlog("sections.flush.done", job_id=job.id, buffered=len(results))

        jlog("job.run.done", job_id=job.id, total_sections=len(sections), total_len=sum(len(x) for x in full_contract_buf))

    except asyncio.CancelledError:
        jlog("job.run.cancelled", job_id=job.id)
        await job.queue.put(sse("error", "Generation cancelled"))
        await job.queue.put(sse("done", ""))
    except Exception as e:
        jlog("job.run.error", job_id=job.id, error=str(e))
        await job.queue.put(sse("error", f"Internal error: {html_escape(str(e))}"))
        await job.queue.put(sse("done", ""))
    finally:
        asyncio.create_task(delayed_delete(job.id, jobs_registry))
