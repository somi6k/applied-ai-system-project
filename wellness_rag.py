"""Retrieval-augmented wellness suggestions for PawPal+.

The scheduler in :mod:`pawpal_system` decides *when* tasks happen. This module
decides *what* tasks are worth doing for a particular pet, by grounding a Gemini
model in a local knowledge base instead of letting it improvise pet-care advice.

Pipeline:

1. **Load**   - read ``knowledge/*.md`` and split each file into passages at its
   ``##`` headings, so a retrieved chunk is one self-contained topic.
2. **Embed**  - turn every passage into a vector with the Gemini embedding
   model, cached on disk so a Streamlit rerun does not re-embed the corpus.
3. **Retrieve** - embed a profile of the pet as the query and keep the top-k
   passages by cosine similarity. With no API key this degrades to keyword
   scoring, so the app still works offline.
4. **Generate** - ask Gemini for a routine grounded *only* in those passages,
   returned as JSON so each activity can become a real :class:`~pawpal_system.Task`.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Protocol, Sequence

from pawpal_system import Owner, Pet, Priority, Task

PROJECT_ROOT = Path(__file__).resolve().parent
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"
CACHE_PATH = PROJECT_ROOT / ".wellness_cache.json"

EMBED_MODEL = "gemini-embedding-001"
# Gemini retires older models for new API keys; `client.models.list()` shows
# what your key can actually call if this one starts 404ing.
CHAT_MODEL = "gemini-3.6-flash"
# gemini-embedding-001 defaults to 3072 dims; 768 is plenty for a corpus this
# small and keeps the cache file readable.
EMBED_DIMS = 768
TOP_K = 4

PRIORITY_BY_NAME = {p.name.lower(): p for p in Priority}


class MissingAPIKey(RuntimeError):
    """Raised when a Gemini call is attempted without an API key configured."""


class GenerationError(RuntimeError):
    """Raised when Gemini responds with something we cannot use."""


# --- configuration ---------------------------------------------------------


def _load_dotenv(path: Path = PROJECT_ROOT / ".env") -> None:
    """Copy simple ``KEY=value`` lines from a .env file into ``os.environ``.

    Deliberately tiny (no python-dotenv dependency) and never overrides a
    variable that is already set in the real environment.
    """
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def api_key() -> str | None:
    """The Gemini API key, or None if the user has not configured one."""
    _load_dotenv()
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or None


def _client():
    """A configured ``google.genai`` client.

    Imported lazily so the rest of PawPal+ (and the test suite) runs without the
    SDK installed.
    """
    key = api_key()
    if not key:
        raise MissingAPIKey(
            "No Gemini API key found. Get one at https://aistudio.google.com/apikey "
            "and set GEMINI_API_KEY in your environment or in a .env file."
        )
    try:
        from google import genai
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise MissingAPIKey(
            "The google-genai package is not installed. Run: pip install -r requirements.txt"
        ) from exc
    return genai.Client(api_key=key)


# --- the knowledge base ----------------------------------------------------


@dataclass
class Passage:
    """One retrievable chunk: a single ``##`` section of a knowledge file."""

    source: str  # file name, e.g. "dog-exercise.md"
    doc_title: str  # the file's H1
    title: str  # the section's H2
    text: str
    embedding: list[float] | None = None

    @property
    def label(self) -> str:
        """Human-readable citation, e.g. "Dog exercise and activity - Sniffing"."""
        return f"{self.doc_title} - {self.title}"

    @property
    def content(self) -> str:
        """What actually gets embedded: the headings plus the body.

        Including the titles gives short sections enough signal to match a
        query that only names the topic.
        """
        return f"{self.doc_title}\n{self.title}\n{self.text}"

    def cache_key(self, model: str, dims: int) -> str:
        digest = hashlib.sha256(self.content.encode("utf-8")).hexdigest()[:16]
        return f"{model}:{dims}:{digest}"


_SECTION_RE = re.compile(r"^##\s+(.*)$", re.MULTILINE)


def split_document(text: str, source: str) -> list[Passage]:
    """Split one markdown document into a Passage per ``##`` section.

    Text before the first ``##`` (the H1 and any preamble) is treated as the
    document title and is not itself a passage.
    """
    lines = text.splitlines()
    doc_title = next(
        (line[2:].strip() for line in lines if line.startswith("# ")), source
    )

    passages: list[Passage] = []
    matches = list(_SECTION_RE.finditer(text))
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[match.end() : end].strip()
        if not body:
            continue  # a heading with no content retrieves nothing useful
        passages.append(
            Passage(
                source=source,
                doc_title=doc_title,
                title=match.group(1).strip(),
                text=body,
            )
        )
    return passages


def load_passages(directory: Path | str = KNOWLEDGE_DIR) -> list[Passage]:
    """Load every ``*.md`` file in ``directory`` as passages, sorted by name."""
    directory = Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"Knowledge directory not found: {directory}")

    passages: list[Passage] = []
    for path in sorted(directory.glob("*.md")):
        passages.extend(split_document(path.read_text(encoding="utf-8"), path.name))
    return passages


# --- embeddings ------------------------------------------------------------


class Embedder(Protocol):
    """Anything that can turn texts into vectors (real or, in tests, fake)."""

    def embed(self, texts: Sequence[str], *, task_type: str) -> list[list[float]]: ...


def _batched(items: Sequence[str], size: int) -> Iterator[Sequence[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


@dataclass
class GeminiEmbedder:
    """Embeds text with the Gemini embedding model."""

    model: str = EMBED_MODEL
    dimensions: int = EMBED_DIMS
    batch_size: int = 32
    _cached_client: object | None = field(default=None, repr=False)

    def embed(self, texts: Sequence[str], *, task_type: str) -> list[list[float]]:
        """Vectors for ``texts``, in order.

        ``task_type`` is the asymmetric-retrieval hint: documents are embedded
        as RETRIEVAL_DOCUMENT and the pet profile as RETRIEVAL_QUERY, which puts
        both in a space tuned for matching questions to passages.
        """
        if not texts:
            return []
        # Client first: it turns a missing key or missing SDK into MissingAPIKey.
        if self._cached_client is None:
            self._cached_client = _client()
        from google.genai import types

        vectors: list[list[float]] = []
        for batch in _batched(texts, self.batch_size):
            response = self._cached_client.models.embed_content(
                model=self.model,
                contents=list(batch),
                config=types.EmbedContentConfig(
                    task_type=task_type, output_dimensionality=self.dimensions
                ),
            )
            vectors.extend(list(item.values) for item in response.embeddings)
        return vectors


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity of two vectors; 0.0 if either has no magnitude."""
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


# --- keyword fallback ------------------------------------------------------

_STOPWORDS = frozenset(
    """a an and are as at be by for from has have how in is it its of on or that
    the to was what when where which who will with your my me i needs need pet
    pets""".split()
)
_WORD_RE = re.compile(r"[a-z]{3,}")


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS]


def keyword_similarity(query: str, passage: Passage) -> float:
    """Overlap score used when embeddings are unavailable.

    Counts distinct query terms present in the passage, weights title hits
    double, and normalises by query length so scores stay comparable.
    """
    query_terms = set(_tokens(query))
    if not query_terms:
        return 0.0
    body_terms = set(_tokens(passage.text))
    title_terms = set(_tokens(f"{passage.doc_title} {passage.title}"))
    hits = len(query_terms & body_terms) + 2 * len(query_terms & title_terms)
    return hits / (len(query_terms) * 3)


# --- retrieval -------------------------------------------------------------


@dataclass
class Retrieved:
    """A passage plus the score that got it selected."""

    passage: Passage
    score: float


@dataclass
class KnowledgeBase:
    """The corpus, its vectors, and top-k retrieval over them."""

    passages: list[Passage]
    embedder: Embedder | None = None
    cache_path: Path | None = CACHE_PATH
    model: str = EMBED_MODEL
    dimensions: int = EMBED_DIMS
    # "vector" once embeddings exist, "keyword" while falling back.
    mode: str = "keyword"
    warning: str | None = None

    @classmethod
    def load(
        cls,
        directory: Path | str = KNOWLEDGE_DIR,
        embedder: Embedder | None = None,
        cache_path: Path | None = CACHE_PATH,
        **kwargs,
    ) -> KnowledgeBase:
        """Build a knowledge base from a directory of markdown files.

        Passing ``embedder=None`` means "use Gemini if a key is configured";
        tests pass an explicit fake instead.
        """
        if embedder is None and api_key():
            embedder = GeminiEmbedder()
        return cls(
            passages=load_passages(directory),
            embedder=embedder,
            cache_path=cache_path,
            **kwargs,
        )

    # -- embedding cache ----------------------------------------------------

    def _read_cache(self) -> dict[str, list[float]]:
        if not self.cache_path or not Path(self.cache_path).is_file():
            return {}
        try:
            return json.loads(Path(self.cache_path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}  # a corrupt cache is a slow start, not an error

    def _write_cache(self, cache: dict[str, list[float]]) -> None:
        if not self.cache_path:
            return
        try:
            Path(self.cache_path).write_text(json.dumps(cache), encoding="utf-8")
        except OSError:
            pass  # read-only checkout: embed every run rather than crash

    def ensure_embeddings(self) -> bool:
        """Populate passage embeddings. True if vector search is available.

        Any failure (no key, no network, SDK missing) is recorded in
        ``warning`` and reported as False so callers fall back to keywords.
        """
        if all(p.embedding is not None for p in self.passages) and self.passages:
            self.mode = "vector"
            return True
        if self.embedder is None:
            self.warning = "No Gemini API key - using keyword search."
            self.mode = "keyword"
            return False

        cache = self._read_cache()
        keys = [p.cache_key(self.model, self.dimensions) for p in self.passages]
        missing = [
            (i, p) for i, p in enumerate(self.passages) if keys[i] not in cache
        ]

        if missing:
            try:
                vectors = self.embedder.embed(
                    [p.content for _, p in missing], task_type="RETRIEVAL_DOCUMENT"
                )
            except Exception as exc:  # noqa: BLE001 - degrade, never crash the UI
                self.warning = f"Embedding failed ({exc}) - using keyword search."
                self.mode = "keyword"
                return False
            for (i, _), vector in zip(missing, vectors):
                cache[keys[i]] = vector
            self._write_cache(cache)

        for passage, key in zip(self.passages, keys):
            passage.embedding = cache[key]
        self.mode = "vector"
        self.warning = None
        return True

    # -- search -------------------------------------------------------------

    def retrieve(self, query: str, k: int = TOP_K) -> list[Retrieved]:
        """The ``k`` passages most relevant to ``query``, best first."""
        if not self.passages:
            return []

        if self.ensure_embeddings():
            try:
                query_vector = self.embedder.embed(
                    [query], task_type="RETRIEVAL_QUERY"
                )[0]
                scored = [
                    Retrieved(p, cosine_similarity(query_vector, p.embedding))
                    for p in self.passages
                ]
            except Exception as exc:  # noqa: BLE001
                self.warning = f"Query embedding failed ({exc}) - using keyword search."
                self.mode = "keyword"
                scored = [
                    Retrieved(p, keyword_similarity(query, p)) for p in self.passages
                ]
        else:
            scored = [Retrieved(p, keyword_similarity(query, p)) for p in self.passages]

        scored.sort(key=lambda r: r.score, reverse=True)
        return [r for r in scored[:k] if r.score > 0]


# --- generation ------------------------------------------------------------


@dataclass
class Activity:
    """One suggested care activity, straight from the model's JSON."""

    name: str
    duration_minutes: int
    priority: str = "medium"
    time_of_day: str = ""
    why: str = ""

    def to_task(self) -> Task:
        """Convert into a schedulable PawPal+ Task."""
        return Task(
            name=self.name,
            duration=max(1, int(self.duration_minutes)),
            priority=PRIORITY_BY_NAME.get(self.priority.lower(), Priority.MEDIUM),
        )


@dataclass
class Issue:
    """One guardrail finding against a generated routine."""

    code: str
    detail: str
    severity: str = "error"  # "error" (repaired/dropped) | "warning" (kept)

    def __str__(self) -> str:
        return f"[{self.severity}] {self.code}: {self.detail}"


@dataclass
class Routine:
    """A grounded wellness suggestion plus the passages that produced it."""

    summary: str
    activities: list[Activity] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    sources: list[Retrieved] = field(default_factory=list)
    retrieval_mode: str = "keyword"
    issues: list[Issue] = field(default_factory=list)

    def to_tasks(self) -> list[Task]:
        """Every suggested activity as a Task, ready for ``Pet.add_task``."""
        return [a.to_task() for a in self.activities]

    @property
    def total_minutes(self) -> int:
        return sum(a.duration_minutes for a in self.activities)


# --- guardrail -------------------------------------------------------------

MAX_ACTIVITY_MINUTES = 240
_CITATION_RE = re.compile(r"\[(\d+)\]")
# Phrases that flip a mention of an allergen from "feed this" to "don't".
_AVOIDANCE_RE = re.compile(
    r"avoid|free[- ]from|free[- ]of|[- ]free|without|instead of|rather than|"
    r"exclud|allerg|not contain|no longer|never",
    re.IGNORECASE,
)
_AVOIDANCE_WINDOW = 60  # characters either side of the mention to inspect


def _allergen_hit(activity: Activity, allergens: Sequence[str]) -> str | None:
    """The allergen an activity would expose the pet to, if any.

    A mention in the activity *name* is always a conflict — that is what the
    owner will actually do. A mention in the reason is only a conflict when it
    is not part of an avoidance instruction, so "use chicken-free kibble" and
    "respecting her chicken allergy" are allowed through while "reward with
    chicken strips" is not.
    """
    name = activity.name.lower()
    why = activity.why.lower()
    for allergen in allergens:
        if allergen in name:
            return allergen
        for match in re.finditer(re.escape(allergen), why):
            window = why[
                max(0, match.start() - _AVOIDANCE_WINDOW) : match.end() + _AVOIDANCE_WINDOW
            ]
            if not _AVOIDANCE_RE.search(window):
                return allergen
    return None


def validate_routine(
    routine: Routine, pet: Pet, owner: Owner | None = None, *, repair: bool = True
) -> list[Issue]:
    """Check a generated routine against the constraints the prompt asked for.

    The model is asked to stay grounded, stay inside the time budget, and avoid
    the pet's allergens — but asking is not enforcing. This runs the same
    constraints as code after the fact:

    - **implausible_duration** - a non-positive or absurd duration is clamped.
    - **bad_citation** - a citation numbered past the retrieved passages is a
      fabricated source, so the activity is dropped.
    - **missing_citation** - an activity with no ``[n]`` at all is ungrounded
      (warning: the text may still be fine, but it cannot be traced).
    - **allergen_conflict** - an activity naming a listed allergen is dropped.
    - **duplicate_task** - the activity repeats a task the pet already has.
    - **budget_exceeded** - the lowest-priority activities are dropped until the
      routine fits the owner's available minutes.
    - **no_activities** - nothing usable survived.

    With ``repair=True`` the routine is edited in place so the caller only ever
    sees activities that pass. Returns every issue found, repaired or not.
    """
    issues: list[Issue] = []
    kept: list[Activity] = []
    source_count = len(routine.sources)
    allergens = [a.lower() for a in pet.allergies if a.strip()]
    existing = {t.name.strip().lower() for t in pet.tasks}

    for activity in routine.activities:
        # -- duration sanity
        if not 0 < activity.duration_minutes <= MAX_ACTIVITY_MINUTES:
            issues.append(
                Issue(
                    "implausible_duration",
                    f"'{activity.name}' had {activity.duration_minutes} min",
                )
            )
            if repair:
                activity.duration_minutes = min(
                    max(1, activity.duration_minutes), MAX_ACTIVITY_MINUTES
                )

        # -- grounding: every claim must point at a passage we actually retrieved
        cited = [int(n) for n in _CITATION_RE.findall(activity.why)]
        invalid = [n for n in cited if not 1 <= n <= source_count]
        if invalid:
            issues.append(
                Issue(
                    "bad_citation",
                    f"'{activity.name}' cites {invalid} but only "
                    f"{source_count} passages were retrieved",
                )
            )
            if repair:
                continue  # a fabricated source means the claim is unsupported
        elif not cited and source_count:
            issues.append(
                Issue("missing_citation", f"'{activity.name}' cites no passage", "warning")
            )

        # -- safety: never suggest something the pet reacts to
        hit = _allergen_hit(activity, allergens)
        if hit:
            issues.append(
                Issue("allergen_conflict", f"'{activity.name}' mentions allergen '{hit}'")
            )
            if repair:
                continue

        # -- usefulness: the prompt asked it to complement, not repeat
        if activity.name.strip().lower() in existing:
            issues.append(
                Issue("duplicate_task", f"'{activity.name}' is already a task", "warning")
            )

        kept.append(activity)

    # -- the owner's time budget is a hard limit, not a suggestion
    budget = owner.available_minutes if owner else None
    if budget is not None:
        total = sum(a.duration_minutes for a in kept)
        if total > budget:
            issues.append(
                Issue("budget_exceeded", f"{total} min suggested, {budget} min available")
            )
            if repair:
                # Drop the least important first: low priority, then longest.
                order = sorted(
                    range(len(kept)),
                    key=lambda i: (
                        -int(PRIORITY_BY_NAME.get(kept[i].priority.lower(), Priority.MEDIUM)),
                        kept[i].duration_minutes,
                    ),
                )
                budgeted, used = [], 0
                for i in order:
                    if used + kept[i].duration_minutes <= budget:
                        budgeted.append(i)
                        used += kept[i].duration_minutes
                kept = [kept[i] for i in sorted(budgeted)]

    if repair:
        routine.activities = kept
        routine.issues = issues

    if not kept:
        issues.append(Issue("no_activities", "nothing survived validation"))
        if repair:
            routine.issues = issues

    return issues


ROUTINE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "activities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "duration_minutes": {"type": "integer"},
                    "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                    "time_of_day": {"type": "string"},
                    "why": {"type": "string"},
                },
                "required": ["name", "duration_minutes", "priority", "why"],
            },
        },
        "cautions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "activities"],
}

SYSTEM_INSTRUCTION = """\
You are the wellness planner inside PawPal+, a pet-care scheduling app.

Rules:
- Use ONLY the numbered guidance passages provided. If they do not cover
  something the pet needs, say so in `summary` rather than inventing advice.
- Every activity's `why` must cite the passage number it came from, e.g. "[2]".
- Respect the owner's time budget: total duration must not exceed it. Prefer
  fewer, higher-value activities over padding the schedule.
- Never contradict the pet's listed allergies or medications.
- You are not a veterinarian. Put anything that needs a vet in `cautions`.
- Activity names are short and imperative, like a to-do item ("Sniff walk",
  "Brush teeth"), because they become tasks in a daily planner.\
"""


def build_profile(pet: Pet, owner: Owner | None = None, focus: str = "") -> str:
    """A compact description of the pet used as both query and prompt context."""
    lines = [f"Pet: {pet.name}", f"Breed/species: {pet.breed or 'unknown'}"]
    if pet.allergies:
        lines.append(f"Allergies: {', '.join(pet.allergies)}")
    if pet.medications:
        lines.append(f"Medications: {', '.join(pet.medications)}")
    if pet.preferred_food:
        lines.append(f"Preferred food: {pet.preferred_food}")
    if pet.appointments:
        lines.append(f"Upcoming appointments: {', '.join(pet.appointments)}")
    if pet.tasks:
        current = ", ".join(
            f"{t.name} ({t.duration} min, {t.priority.name.lower()})" for t in pet.tasks
        )
        lines.append(f"Existing care tasks: {current}")
    if owner is not None:
        lines.append(f"Owner time available today: {owner.available_minutes} minutes")
        if owner.preferences:
            prefs = ", ".join(f"{k}={v}" for k, v in owner.preferences.items())
            lines.append(f"Owner preferences: {prefs}")
    if focus:
        lines.append(f"Owner's question: {focus}")
    return "\n".join(lines)


def format_context(results: Iterable[Retrieved]) -> str:
    """Number the retrieved passages so the model can cite them."""
    return "\n\n".join(
        f"[{i}] {r.passage.label}\n{r.passage.text}" for i, r in enumerate(results, 1)
    )


@dataclass
class WellnessAdvisor:
    """Retrieves relevant guidance, then asks Gemini to turn it into a routine."""

    kb: KnowledgeBase
    model: str = CHAT_MODEL
    temperature: float = 0.3
    _cached_client: object | None = field(default=None, repr=False)

    @classmethod
    def load(cls, directory: Path | str = KNOWLEDGE_DIR, **kwargs) -> WellnessAdvisor:
        """Convenience constructor: build the knowledge base and the advisor."""
        return cls(kb=KnowledgeBase.load(directory), **kwargs)

    def retrieve(
        self, pet: Pet, owner: Owner | None = None, focus: str = "", k: int = TOP_K
    ) -> list[Retrieved]:
        """Just the R of RAG - useful on its own when no API key is set."""
        return self.kb.retrieve(build_profile(pet, owner, focus), k=k)

    def suggest(
        self, pet: Pet, owner: Owner | None = None, focus: str = "", k: int = TOP_K
    ) -> Routine:
        """A wellness routine for ``pet``, grounded in the retrieved passages.

        Raises :class:`MissingAPIKey` if generation is not configured; callers
        can still show ``retrieve()`` output in that case.
        """
        results = self.retrieve(pet, owner, focus, k=k)
        if not results:
            raise GenerationError(
                "No relevant guidance found in the knowledge base for this pet."
            )

        budget = owner.available_minutes if owner else 60
        prompt = (
            f"Guidance passages:\n\n{format_context(results)}\n\n"
            f"---\n\nPet profile:\n{build_profile(pet, owner, focus)}\n\n"
            f"Suggest a wellness routine of 3-5 activities totalling no more than "
            f"{budget} minutes, that complements the existing care tasks instead of "
            f"repeating them."
        )

        # Client first: it turns a missing key or missing SDK into MissingAPIKey.
        if self._cached_client is None:
            self._cached_client = _client()
        from google.genai import types

        try:
            response = self._cached_client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=self.temperature,
                    response_mime_type="application/json",
                    response_schema=ROUTINE_SCHEMA,
                ),
            )
        except MissingAPIKey:
            raise
        except Exception as exc:  # noqa: BLE001 - surface one clear error to the UI
            message = str(exc)
            if "RESOURCE_EXHAUSTED" in message or "429" in message:
                # Found while evaluating: the free tier allows only a handful of
                # requests per day, and the raw 429 body is a wall of JSON.
                raise GenerationError(
                    "Gemini quota exhausted — the free tier caps requests per day "
                    "for this model. Retrieval still works; try generating again later."
                ) from exc
            raise GenerationError(f"Gemini request failed: {exc}") from exc

        routine = parse_routine(response.text, results, self.kb.mode)
        # The prompt asks for these constraints; the guardrail enforces them.
        validate_routine(routine, pet, owner)
        return routine


def parse_routine(
    raw: str | None, sources: list[Retrieved], mode: str = "keyword"
) -> Routine:
    """Turn the model's JSON into a Routine, ignoring unexpected extra keys."""
    try:
        data = json.loads(raw or "")
    except json.JSONDecodeError as exc:
        raise GenerationError(
            f"Gemini did not return valid JSON: {(raw or '')[:200]}"
        ) from exc

    activities = []
    for item in data.get("activities", []):
        try:
            activities.append(
                Activity(
                    name=str(item["name"]),
                    duration_minutes=int(item["duration_minutes"]),
                    priority=str(item.get("priority", "medium")),
                    time_of_day=str(item.get("time_of_day", "")),
                    why=str(item.get("why", "")),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue  # skip a malformed entry rather than lose the whole routine

    return Routine(
        summary=str(data.get("summary", "")),
        activities=activities,
        cautions=[str(c) for c in data.get("cautions", [])],
        sources=sources,
        retrieval_mode=mode,
    )
