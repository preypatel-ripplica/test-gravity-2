"""Excel-derived script templates: duration, timing map, hook, CTA, checklist."""

from __future__ import annotations

from typing import Any

# Long video templates (from "Long Video Templates" sheet)
LONG_TEMPLATES: dict[str, dict[str, str]] = {
    "Disease explainer": {
        "target_duration": "3:30-4:00",
        "timing_map": (
            "0-10s hook; 10-25s direct answer; 25-45s promise; "
            "45-120s explain; 120-200s symptoms/tests/treatment; "
            "200-235s mistakes; 235-240s CTA"
        ),
        "opening_hook_formula": "Diagnosis/report + panic-or-ignore question",
        "structure": (
            "Hook -> direct answer -> 3 promises -> simple explanation -> "
            "symptoms/reports -> treatment path -> mistakes -> consult"
        ),
        "emotional_angle": "Relief first, seriousness second",
        "retention_line": "At the end, I will tell you the mistake that makes this worse.",
        "mid_video_line": (
            "Before treatment, understand this one thing: symptoms alone are not enough."
        ),
        "ending_cta": "If your report/symptoms match, get evaluated instead of guessing.",
        "example_opener": (
            "Fatty liver in ultrasound? First, don't panic. But don't ignore it either. "
            "In 4 minutes, let's understand what it means and what to do next."
        ),
        "avoid": "Starting with textbook definition",
    },
    "Treatment / medicine explainer": {
        "target_duration": "3:00-4:00",
        "timing_map": (
            "0-10s patient question; 10-25s direct rule; 25-90s why; "
            "90-180s options; 180-220s mistake; 220-240s CTA"
        ),
        "opening_hook_formula": "Can I stop/change/avoid treatment?",
        "structure": (
            "Question -> direct rule -> why treatment works -> options -> "
            "how doctor decides -> mistake -> follow-up"
        ),
        "emotional_angle": "Fear of lifelong treatment",
        "retention_line": (
            "The biggest mistake usually happens after the report becomes better."
        ),
        "mid_video_line": (
            "Do not compare your prescription with someone else's; "
            "the reason behind treatment may be different."
        ),
        "ending_cta": "Review treatment with the doctor before changing anything.",
        "example_opener": (
            "Sugar normal aa gayi? Great. But that does not automatically mean "
            "diabetes is gone. It may mean your current plan is working."
        ),
        "avoid": "Universal medicine advice",
    },
    "Diagnosis / report explanation": {
        "target_duration": "3:00-3:45",
        "timing_map": (
            "0-8s exact value; 8-20s direct meaning; 20-45s promise; "
            "45-140s meaning; 140-200s what it can/cannot mean; 200-225s next step"
        ),
        "opening_hook_formula": "Exact report value + what now?",
        "structure": (
            "Value/term -> simple meaning -> what it does not mean -> "
            "when it matters -> next step"
        ),
        "emotional_angle": "Report anxiety to clarity",
        "retention_line": "One number is useful, but it is not the whole diagnosis.",
        "mid_video_line": (
            "Now comes the important part: what you should not assume from this report."
        ),
        "ending_cta": "Bring full report and symptoms for interpretation.",
        "example_opener": (
            "HbA1c 7.5? This is not a random number. It tells how your sugar "
            "behaved over the last 3 months."
        ),
        "avoid": "Overexplaining all report ranges",
    },
    "Lifestyle / diet / exercise": {
        "target_duration": "3:00-4:00",
        "timing_map": (
            "0-10s wrong habit; 10-25s correction; 25-60s why; "
            "60-180s 3 actions; 180-220s what not to do; 220-240s CTA"
        ),
        "opening_hook_formula": "Common wrong shortcut",
        "structure": (
            "Wrong practice -> why people do it -> 3 useful changes -> "
            "what won't help -> when to consult"
        ),
        "emotional_angle": "Frustration + realistic hope",
        "retention_line": (
            "The third point is where most people fail, even when they know what to do."
        ),
        "mid_video_line": (
            "Lifestyle works only when it is specific and sustainable, not extreme."
        ),
        "ending_cta": "Save the routine; consult if symptoms/reports are worsening.",
        "example_opener": (
            "Fatty liver diet does not mean starving. It means fixing the daily "
            "habits quietly damaging the liver."
        ),
        "avoid": "Generic health tips",
    },
    "Comparison explainer": {
        "target_duration": "3:00-4:00",
        "timing_map": (
            "0-10s confusion; 10-30s stakes; 30-120s difference; "
            "120-190s symptoms/tests; 190-230s when to act"
        ),
        "opening_hook_formula": "Two problems feel similar, but action differs",
        "structure": (
            "Confusion -> difference -> symptom signs -> tests -> "
            "treatment difference -> danger signs"
        ),
        "emotional_angle": "Confusion + urgency",
        "retention_line": "Stay till the end for the signs where waiting is risky.",
        "mid_video_line": (
            "The goal is not self-diagnosis; the goal is knowing when not to ignore it."
        ),
        "ending_cta": "For danger signs, seek urgent care.",
        "example_opener": (
            "Acidity and heart pain can feel similar. The dangerous mistake is "
            "assuming chest pain is always acidity."
        ),
        "avoid": "Making self-diagnosis sound easy",
    },
    "Story-led lesson": {
        "target_duration": "3:00-4:00",
        "timing_map": (
            "0-15s patient scenario; 15-60s what they assumed; "
            "60-150s key detail/report; 150-220s learning; 220-240s CTA"
        ),
        "opening_hook_formula": "Patient assumed X, but the real sign was Y",
        "structure": "Situation -> assumption -> key detail -> what changed -> lesson -> action",
        "emotional_angle": "Curiosity + practical learning",
        "retention_line": (
            "The important detail was not the main symptom; it was the small thing "
            "they ignored."
        ),
        "mid_video_line": (
            "This is why history and follow-up matter more than guessing from one symptom."
        ),
        "ending_cta": "If your symptoms are similar, get evaluated.",
        "example_opener": (
            "A patient thought it was normal back pain from sitting. The real sign was "
            "pain going down the leg with weakness."
        ),
        "avoid": "Making it promotional",
    },
}

# Short video templates (from "Short Video Templates" sheet)
SHORT_TEMPLATES: dict[str, dict[str, str]] = {
    "Myth buster": {
        "target_duration": "25-45 sec",
        "timing_map": "0-5s myth hook; 5-15s half-truth; 15-30s risk; 30-45s better action + CTA",
        "core_formula": "Myth -> half-truth -> risk -> better action",
        "hook_style": "Start with contradiction",
        "ending_cta": "Share with a diabetic patient at home.",
        "avoid": "Flat 'myth vs fact' tone",
        "example_script": (
            "Normal sugar means diabetes is cured? Not always. Often, it means the "
            "treatment is working. The mistake is stopping everything and checking "
            "again only when symptoms return."
        ),
    },
    "FAQ": {
        "target_duration": "20-45 sec",
        "timing_map": "0-5s question; 5-12s answer; 12-30s reason; 30-45s action + CTA",
        "core_formula": "Question -> answer first -> reason -> action",
        "hook_style": "Use exact patient question",
        "ending_cta": "Comment your next question.",
        "avoid": "Long background",
        "example_script": (
            "Fatty liver grade 1: serious or normal? It is usually not a panic "
            "situation, but it is also not a 'leave it' situation. It is your early "
            "warning to fix the cause."
        ),
    },
    "When-to-worry symptom": {
        "target_duration": "30-60 sec",
        "timing_map": (
            "0-8s common symptom; 8-25s warning version; 25-50s 3 warning signs; "
            "50-60s action + CTA"
        ),
        "core_formula": "Common symptom -> warning version -> action",
        "hook_style": "Most X is common, but Y is not",
        "ending_cta": "Save this warning list.",
        "avoid": "Fear in every line",
        "example_script": (
            "Back pain is common. Back pain with leg weakness, urine trouble, or "
            "fever is not routine back pain. That needs evaluation."
        ),
    },
    "Patient mistake": {
        "target_duration": "30-60 sec",
        "timing_map": (
            "0-8s mistake after improvement; 8-20s why it feels logical; "
            "20-40s consequence; 40-60s better action + CTA"
        ),
        "core_formula": "Mistake -> why it feels logical -> consequence -> better action",
        "hook_style": "This mistake happens after improvement",
        "ending_cta": "Save before changing treatment.",
        "avoid": "Scolding patients",
        "example_script": (
            "Sugar normal aa gayi? Great. But this is where many patients stop "
            "medicines, stop tracking, and come back with worse reports. Normal "
            "report means review the plan, not disappear."
        ),
    },
    "Quick report term": {
        "target_duration": "30-45 sec",
        "timing_map": (
            "0-8s value/term; 8-20s meaning; 20-35s what not to assume; "
            "35-45s next step + CTA"
        ),
        "core_formula": "Value -> meaning -> what not to assume -> next step",
        "hook_style": "If your report says...",
        "ending_cta": "Save before your next report review.",
        "avoid": "Explaining full disease",
        "example_script": (
            "HbA1c 7.5 means your average sugar has been high. It does not tell "
            "the full reason. Do not panic, but do not delay fixing it."
        ),
    },
    "Single exercise / home care tip": {
        "target_duration": "30-60 sec",
        "timing_map": (
            "0-8s problem; 8-25s one tip; 25-45s who should avoid; "
            "45-60s next step + CTA"
        ),
        "core_formula": "Problem -> one tip -> who should avoid -> next step",
        "hook_style": "Try this only if...",
        "ending_cta": "Save, but stop if symptoms worsen.",
        "avoid": "Multiple exercises in one short",
        "example_script": (
            "For mild back stiffness, this stretch may help. But if pain shoots "
            "down the leg or there is numbness, don't force exercises blindly."
        ),
    },
    "Doctor reacts": {
        "target_duration": "30-60 sec",
        "timing_map": (
            "0-8s claim; 8-20s true part; 20-40s wrong part; 40-60s safer advice + CTA"
        ),
        "core_formula": "Claim -> true part -> wrong part -> safer advice",
        "hook_style": "This sounds simple, but...",
        "ending_cta": "Follow for practical health clarity.",
        "avoid": "Personal attacks",
        "example_script": (
            "This viral diabetes hack sounds easy. The true part: lifestyle matters. "
            "The wrong part: one hack cannot replace monitoring, medicines, and follow-up."
        ),
    },
    "Story-led lesson (short)": {
        "target_duration": "45-60 sec",
        "timing_map": (
            "0-12s mini-case; 12-28s missed detail; 28-48s learning; 48-60s action + CTA"
        ),
        "core_formula": "Mini-case -> missed detail -> learning -> action",
        "hook_style": "A patient thought X, but...",
        "ending_cta": "Consult if the pattern matches.",
        "avoid": "Making it promotional",
        "example_script": (
            "A patient thought it was just sitting-related back pain. The real sign was "
            "pain going down the leg. Not every back pain is treated the same way."
        ),
    },
    "Seasonal health alert": {
        "target_duration": "30-60 sec",
        "timing_map": (
            "0-8s season hook; 8-20s common confusion; 20-45s signs/test; "
            "45-60s action + CTA"
        ),
        "core_formula": "Season -> confusion -> sign/test -> action",
        "hook_style": "This season, don't ignore...",
        "ending_cta": "Save for the season.",
        "avoid": "Generic seasonal advice",
        "example_script": (
            "In monsoon, every fever is not dengue. But fever with severe weakness, "
            "bleeding, or low platelets needs proper testing."
        ),
    },
}

# Alias map: content_formats names → template keys
_SHORT_ALIASES: dict[str, str] = {
    "story-led lesson": "Story-led lesson (short)",
    "story-led lesson (short)": "Story-led lesson (short)",
    "when-to-worry": "When-to-worry symptom",
    "when-to-worry symptom": "When-to-worry symptom",
    "exercise / home-care tip": "Single exercise / home care tip",
    "single exercise / home care tip": "Single exercise / home care tip",
    "seasonal alert": "Seasonal health alert",
    "seasonal health alert": "Seasonal health alert",
    "report / diagnosis explainer": "Diagnosis / report explanation",
    "diagnosis / report explanation": "Diagnosis / report explanation",
}

HOOK_BANK: list[dict[str, str]] = [
    {
        "element": "Report hook",
        "use_for": "Report explainers",
        "stronger": "HbA1c 7.5? This is not just a number. It tells a 3-month sugar story.",
    },
    {
        "element": "Panic vs ignore",
        "use_for": "Disease explainers",
        "stronger": "Fatty liver in ultrasound? Don't panic. But don't ignore it either.",
    },
    {
        "element": "Improvement trap",
        "use_for": "Treatment/mistake videos",
        "stronger": (
            "Sugar normal aa gayi? Great. But this is exactly where many patients "
            "make the biggest mistake."
        ),
    },
    {
        "element": "Half-truth",
        "use_for": "Myth busters",
        "stronger": "The dangerous part of this myth is that it is half true.",
    },
    {
        "element": "Common vs serious",
        "use_for": "Symptoms/red flags",
        "stronger": (
            "Most back pain is common. Back pain with leg weakness is a different story."
        ),
    },
    {
        "element": "Wrong shortcut",
        "use_for": "Lifestyle/remedy",
        "stronger": (
            "Detox drinks sound healthy. But fatty liver is not washed out by one drink."
        ),
    },
    {
        "element": "Doctor decision",
        "use_for": "Treatment explainers",
        "stronger": (
            "The real question is not which treatment is best. It is which treatment "
            "fits your stage."
        ),
    },
    {
        "element": "Mini-story",
        "use_for": "Story-led lessons",
        "stronger": (
            "A patient thought it was just posture. The real sign was not the back pain, "
            "it was the leg symptom."
        ),
    },
    {
        "element": "Viewer promise",
        "use_for": "Long intros",
        "stronger": (
            "In 4 minutes, you will know what this means, what not to assume, "
            "and what to do next."
        ),
    },
    {
        "element": "Section transition",
        "use_for": "Long retention",
        "stronger": "Now comes the part where most patients go wrong.",
    },
    {
        "element": "CTA",
        "use_for": "All videos",
        "stronger": "Save this before changing your treatment or ignoring the report.",
    },
]

SCRIPT_CHECKLIST: list[dict[str, str]] = [
    {
        "check": "One objective",
        "question": "Is the video answering one main patient doubt?",
        "long": "One clear question; all sections support it.",
        "short": "Only one question or one myth.",
        "priority": "High",
    },
    {
        "check": "First 5-10 seconds",
        "question": "Does it start with patient fear/confusion/value?",
        "long": "Hook before intro; no textbook start.",
        "short": "Direct hook immediately.",
        "priority": "High",
    },
    {
        "check": "Early answer",
        "question": "Does the viewer get a useful answer early?",
        "long": "Give direct answer in first 20-30 seconds.",
        "short": "Answer in first 5 seconds.",
        "priority": "High",
    },
    {
        "check": "4-minute discipline",
        "question": "Can this be completed without rushing?",
        "long": "Max 5-6 sections; cut extra background.",
        "short": "One idea only.",
        "priority": "High",
    },
    {
        "check": "Emotional angle",
        "question": "Is there a real reason to care?",
        "long": "Use panic, confusion, regret, relief, or consequence naturally.",
        "short": "One emotional hook only.",
        "priority": "Medium",
    },
    {
        "check": "Retention",
        "question": "Is there a reason to keep watching?",
        "long": "Add one open loop: mistake/red flag/what not to assume.",
        "short": "Use one reveal or contrast.",
        "priority": "High",
    },
    {
        "check": "Patient language",
        "question": "Would a patient understand this without medical background?",
        "long": "Explain technical words after using them.",
        "short": "Avoid complex words.",
        "priority": "High",
    },
    {
        "check": "Structure",
        "question": "Does the flow feel like a conversation?",
        "long": "Hook -> answer -> explain -> action.",
        "short": "Hook -> answer -> action.",
        "priority": "High",
    },
    {
        "check": "CTA",
        "question": "Is the next step clear and natural?",
        "long": "End with consult/report review/save based on topic.",
        "short": "One CTA only.",
        "priority": "Medium",
    },
    {
        "check": "Freshness",
        "question": "Does this sound different from last videos?",
        "long": "Rotate hook type and transition lines.",
        "short": "Rotate hook pattern.",
        "priority": "Medium",
    },
]


def _resolve_template_key(video_type: str, fmt: str) -> str | None:
    name = (video_type or "").strip()
    if not name:
        return None
    lower = name.lower()
    if fmt == "Short":
        aliased = _SHORT_ALIASES.get(lower)
        if aliased:
            return aliased
        for key in SHORT_TEMPLATES:
            if key.lower() == lower:
                return key
        return None
    # Long
    if lower in _SHORT_ALIASES and _SHORT_ALIASES[lower] in LONG_TEMPLATES:
        return _SHORT_ALIASES[lower]
    for key in LONG_TEMPLATES:
        if key.lower() == lower:
            return key
    # Fuzzy: report naming
    if "report" in lower or "diagnosis" in lower:
        return "Diagnosis / report explanation"
    return None


def template_for(video_type: str, fmt: str) -> dict[str, Any]:
    """Return the Excel template for a video type + Long/Short format."""
    key = _resolve_template_key(video_type, fmt)
    if fmt == "Short":
        base = SHORT_TEMPLATES.get(key or "") or SHORT_TEMPLATES["FAQ"]
        return {"format": "Short", "video_type": key or "FAQ", **base}
    base = LONG_TEMPLATES.get(key or "") or LONG_TEMPLATES["Disease explainer"]
    return {
        "format": "Long",
        "video_type": key or "Disease explainer",
        **base,
    }


def catalog_for_script_prompt() -> dict[str, Any]:
    return {
        "long_templates": LONG_TEMPLATES,
        "short_templates": SHORT_TEMPLATES,
        "hook_bank": HOOK_BANK,
        "checklist": SCRIPT_CHECKLIST,
        "rules": {
            "max_long_duration": "4 minutes",
            "core_approach": "Attention-first but doctor-like",
            "engagement_style": "Emotional, not dramatic",
            "long_structure_principle": (
                "Start with patient fear/confusion/report value, give an early "
                "answer, then explain."
            ),
        },
    }
