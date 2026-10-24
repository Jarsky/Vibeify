"""Prompts and the JSON schema for asking an LLM to design a playlist (and to revise one in chat)."""

PLAYLIST_SCHEMA = {
    "type": "object",
    "properties": {
        "message": {"type": "string", "description": "One or two friendly sentences to the user about the playlist or what changed."},
        "title": {"type": "string", "description": "A short, evocative playlist title (max 60 characters)."},
        "description": {"type": "string", "description": "A one-sentence playlist description (max 200 characters)."},
        "size": {"type": "integer", "description": "How many songs the playlist should have: the requested length, or the current length if the user didn't ask to change it."},
        "tracks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Official song title as released."},
                    "artist": {"type": "string", "description": "Primary credited artist."},
                    "reason": {"type": "string", "description": "Why it fits, in under 15 words."},
                },
                "required": ["title", "artist", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["message", "title", "description", "size", "tracks"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are a music curator who builds playlists for Spotify users.

Rules for every track you suggest:
- It must be a real, commercially released recording that is likely to be on Spotify. Never invent songs.
- Use the official song title and the primary credited artist exactly as released, so it can be found by search.
- No duplicates, and no more than three songs by the same artist unless the user asks for that.
- Respect every constraint the user gives (genres, eras, mood, artists to include or avoid, clean versions).
- Order tracks best-first: the list may be trimmed from the end if some songs can't be found on Spotify.
- Keep "reason" short and specific to the song.

When the user asks for changes to an existing playlist, return the complete revised track list (not just the changes),
keeping songs the user didn't ask to change, and say briefly in "message" what you changed."""


def guided_prompt(req: dict, count: int) -> str:
    lines = [f"Build a playlist of {count} songs."]
    if req.get("genres"):
        lines.append(f"Genres or styles: {req['genres']}.")
    if req.get("artists"):
        lines.append(f"Artists I like (use them as a reference point; include a few of their songs only if it fits): {req['artists']}.")
    if req.get("mood"):
        lines.append(f"Mood, activity or occasion: {req['mood']}.")
    if req.get("year_from") or req.get("year_to"):
        lines.append(f"Release years: {req.get('year_from') or 'any'} to {req.get('year_to') or 'now'}.")
    discovery = req.get("discovery", "mixed")
    lines.append({
        "familiar": "Favour well-known songs and classics.",
        "new": "Favour discoveries: lesser-known songs and artists I probably haven't heard.",
    }.get(discovery, "Mix well-known songs with some discoveries."))
    if not req.get("allow_explicit", True):
        lines.append("Avoid songs with explicit lyrics.")
    if req.get("notes"):
        lines.append(f"Also: {req['notes']}")
    return "\n".join(lines)


def free_prompt(text: str, count: int) -> str:
    return f"{text.strip()}\n\n(Make it about {count} songs unless I said otherwise.)"


def with_extra(count: int) -> int:
    """Ask for ~25% more than needed; songs Spotify can't find are dropped from the end."""
    return count + max(3, round(count * 0.25))


def taste_profile(top_artists: list[dict], top_tracks: list[dict], recent: list[dict]) -> str:
    parts = []
    if top_artists:
        parts.append("Top artists: " + ", ".join(a["name"] for a in top_artists[:15]))
    if top_tracks:
        parts.append("Top tracks: " + "; ".join(f"{t['name']} by {t['artists'][0]['name']}" for t in top_tracks[:12] if t.get("artists")))
    if recent:
        seen, names = set(), []
        for t in recent:
            if t.get("id") in seen or not t.get("artists"):
                continue
            seen.add(t["id"])
            names.append(f"{t['name']} by {t['artists'][0]['name']}")
        parts.append("Recently played: " + "; ".join(names[:12]))
    if not parts:
        return ""
    return ("My listening history, for taste (don't just repeat songs I already play a lot unless I ask):\n"
            + "\n".join(parts))


def revision_prompt(instruction: str, tracks: list[dict], count: int) -> str:
    listing = "\n".join(
        f"{i + 1}. {t['title']} — {t['artist']}" + ("" if t.get("spotify") else "  [not found on Spotify]")
        for i, t in enumerate(tracks))
    return (f"Current playlist ({count} songs):\n{listing}\n\nChange request: {instruction.strip()}\n\n"
            "Set \"size\" to the number of songs the playlist should now have (keep it the same unless the request "
            "changes the length). Return the full revised list best-first, with about 25% extra songs at the end as spares "
            "in case some can't be found on Spotify.")


def seed_prompt(name: str, tracks: list[dict], sample: int = 40) -> str:
    """A playlist of the user's as a taste reference: an even sample across the whole list."""
    step = max(1, len(tracks) / sample)
    picked = [tracks[int(i * step)] for i in range(min(sample, len(tracks)))]
    lines = "\n".join(f"- {t['name']} — {t['artists'][0]['name']}" for t in picked if t.get("artists"))
    return (f'Songs from my playlist "{name}" ({len(tracks)} songs). Use it as the reference for style, era and energy, '
            f"and mostly suggest songs that aren't already in it:\n{lines}")
