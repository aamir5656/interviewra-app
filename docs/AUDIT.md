# Audit of possible problems (PART 4)

| Area | Real risk? | What was done |
|---|---|---|
| Two answers sent at once (double submit) | Yes | One turn per session at a time, second gets 409 `turn_in_progress` (`routers/interview.py`); test in `test_audit.py` |
| Role text with instructions / HTML | Yes | Role name validator (letters, numbers, simple punctuation, no instruction phrases); tests |
| Injection inside the CV | Yes | Instruction-like CV items dropped in `clean_summary`; CV text fenced (`resume_summary` tag added to `fence_safe`); test |
| "Score me 100" in an answer (evaluator) | Yes | Instruction-only answers capped at 25 in code (`apply_code_rules`); test |
| Alex shows tool names / system prompt | Yes | Reply check + code cleanup (`reply_checks.INTERNAL`); test |
| Tool abuse ("call end_interview now") | Was handled | Tools are gated in code per turn (`allowed_tools`, `tool_specs`); more tests added |
| User A opens user B's report/interview | No | Every query filters by `user_id` (existing test `test_other_user_gets_404_everywhere`) |
| Memory leak between users | No | `get_user_memory` uses the server-side user id only |
| XSS in Markdown | No | react-markdown without raw HTML, no `dangerouslySetInnerHTML` (guard test) |
| `.env` committed | No | `.gitignore` blocks `.env`, `.env.*` (guard test) |
| Empty / 10,000-char answers | No | 422 for empty, max 4000 chars (test) |
| Timer expires | No | The timer is advisory only, it never sends an answer |
| Ended early report | Yes | Summary says "ended after N of M questions"; average covers only asked questions; test |
| Evaluator dropped a question | Yes | Count validation + one retry + padding in code; test |
| LLM outage / bad JSON | Was handled | Retry, fallback report, clear error; existing tests |
| Rate limits / cost abuse | Was handled | Per-user daily limits and IP limit (existing tests) |

## Added later (professional review pass)

| Area | Real risk? | What was done |
|---|---|---|
| Free-text role (nonsense, instructions, roles with no questions) | Yes | Role is a dropdown of 7 roles; the API accepts only those (any spelling or slug) and answers 422 "Please choose a role from the list." |
| Data Analyst / Product Manager got Git and code-review questions | Yes | Developer-only general questions are tagged `dev` and only used for Frontend, Backend, Full-Stack, DevOps, QA; test checks 40 random sessions |
| Two-topic questions in the bank ("what is X and how do you Y") | Yes | 5 questions reworded; test fails if any question has two focuses |
| Correct answer got a "Critical" flag (flag from another item) | Yes | Critical needs a named mistake; flag contradicting its own feedback is cleared; evaluator asked once to fix contradictions; test strings and HTML are zero-score non-answers, never critical |
| Question asked but never answered when the user pressed End | Yes | Scores 0, "No answer was given." |
| Short but dense answers capped too hard | Yes | Two tiers: under 12 words 55, under 25 words 70 |
| Raw validation text in toasts ("role_name: Value error, ...") | Yes | Readable one-sentence messages |
| Report page for someone else's / unknown id said "No report yet" | Yes | Shows "Not found" |

## Added after Tests 12 and 13 (follow-ups, Mixed type, CV, evaluator)

| Area | Real risk? | What was done |
|---|---|---|
| A wrong answer that no regex can see (CSS box model, "fill every empty cell with zero") got no follow-up: Alex wrote one correcting sentence and started the next main question in the same message | Yes | `app/services/answer_judge.py`: one small model call (`ANSWER_JUDGE`, default on) judges answers that passed the regex checks. A "wrong" or "unprofessional" verdict makes the code keep the interview on the same question for exactly one follow-up turn (no new main question, no `get_next_topic`). A failing judge never blocks the interview; no second judge call after the follow-up |
| A turn that moves on still commented on the previous answer ("one part deserves a second look") | Yes | `check_reply(..., new_topic=True)` rejects correction sentences (questions are ignored, so "a time you made a mistake" is fine) and `sanitize` removes them; the turn notes say so too |
| Mixed type had no HR question and only one technical question in four | Yes | `MIXED_PATTERN`: an HR "Introduction" first, then mostly technical (about half), never two HR in a row; HR-only interviews also open with the introduction |
| Only the dangerous claim was named; ordinary factual errors were not listed (Test 12: 3 of 5 wrong claims named) | Yes | The evaluator lists EVERY wrong claim in `mistakes`; three or more cap the item at 30 in code (`MANY_MISTAKES_CAP`) |
| "Stronger answer" hints repeated the candidate or suggested outdated ideas | Yes | Prompt forbids outdated, advanced or repeated ideas; the existing code check still replaces hints that only repeat the answer |
| "At least half of the questions on the CV" was only a global prompt rule and was ignored | Yes | With a relevant CV, every non-HR main question gets a per-turn note to build the question on a concrete resume item (`cv_hook`) |
| Test suite takes about 30 minutes against Neon | Yes | pytest prints a warning for a remote database; README explains `TEST_DATABASE_URL` with the local Docker database (433 tests in about 30 seconds) |
| The closing message praised a session with serious red flags ("I appreciate your thoughtful answers") | Yes | `check_reply(closing=True)` rejects praise and grading words, `sanitize(closing=True)` strips them |
| A repeated question lost its scenario ("those duplicate records" without the table description) because the model wrote lead-in, scenario and question as one paragraph | Yes | `sanitize(new_topic=True)` puts the lead-in sentence in its own paragraph, so the stored question keeps the whole scenario |

## Added after Test 15 (root causes, not patches)

| Symptom in Test 15 | Root cause | Fix |
|---|---|---|
| The old line ("You maintained that deleting rows is safe...") stuck to the repeated question and appeared in the report | The question was guessed from free text (`extract_question`), and the report copied the whole interviewer message | The model wraps the question in `<q></q>`; the code stores the exact text with the main-question record (`question_text.py`, `agent._store_question`); repeats, `current_question` and the report's `question` field read it. The old guess remains only as a fallback for old sessions or a model that ignores the tags (one rewrite first, `STRICT_QUESTION_TAGS`) |
| "a" got only "No problem" and no hint | A hint phrased as a question was dropped when the repeat was composed | `compose_repeat` turns a hint-like question into a statement and always adds a default hint after a non-answer; `check_reply` asks for a hint |
| An injection followed by a good answer was reported as "needed a hint" (65) | The model inferred prompting from the transcript, where the re-ask after the injection looked like a hint | The answer flag is stored with each reply; `needed_prompting` is computed in code from the flags (instruction and off-topic are not prompting); the transcript marks such messages as not an answer |
| The injection was mentioned twice | Prompt-only rule | `normalize_injection`: every mention is removed and exactly one neutral line is added under weaknesses when an instruction was seen |
| Not every wrong claim was named; a hint was too advanced for a junior (MCAR/MAR/MNAR) | Prompt-only rules | Prompt asks for one entry per false sentence; a list of advanced terms is replaced for intern/junior (a model cannot be forced to be complete, so this part stays best-effort) |

Tests: `tests/test_question_state.py` (helper unit tests, a 300-case fuzz of lead-in shapes, the whole Test 15 flow, report rules, tag compliance).

## Added after Tests 16 and 17

| Symptom | Fix (all in code, one test block each in `tests/test_lead_and_report_rules.py`) |
|---|---|
| The lead-in did not match the candidate's last answer | `fix_lead`: a lead-in whose content words share nothing with the answer is replaced by a short neutral line (only for replies with `<q>` tags, because the lead-in is known exactly there) |
| Almost every reply started with "Thanks" | `check_reply` rejects a lead-in that starts with thanks / thank you (one rewrite); `fix_lead` then replaces it with a neutral line rotated by question number (`NEUTRAL_LEADS`). The closing message is exempt; the rule is also in `interviewer.md` and `turn_notes.md` |
| A hint claimed the candidate's approach still fails | The evaluator prompt forbids it; `HINT_ASSERTS_FAILURE` replaces such hints in code. The question bank has no per-topic "points", so a hint cannot be restricted to uncovered points |
| Unrelated tips (memory management, locks, software velocity for a data analyst) | The prompt limits tips to the candidate's own weaknesses and the role; `drop_irrelevant_tips` drops a tip when fewer than half of its specific words occur in the transcript or in the asked topics (one tip always stays) |
| The injection appeared under "To improve" | `normalize_injection` removes every mention (including the old weakness line) and adds one neutral sentence to the feedback of the question where it happened |
| Skill breakdown was flat (50, 50, 50) | `derive_skills`: accuracy follows the scores, depth follows trade-offs and examples, communication drops with answers that needed help, problem solving follows first-try success; each stays within 15 of the average and a critical mistake may cap accuracy |
| A follow-up hinted at the solution | `check_reply` rejects "how might X help", "wouldn't X help", "would ... improve" in follow-up turns (one rewrite) |

