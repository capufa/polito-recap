"""
PoliTo Recap (the package is recap) — from a recorded lecture (video with slides, or voice
only) to a page to study.

WHY
    A 1-3 hour lecture is worth what the lecturer says while a given slide is on screen:
    notices, examples, "this will be on the exam". Listening to it again costs as much as
    attending it. Here the voice becomes text with timestamps, every second is attributed
    to the slide that was on screen (or, with voice only, the model matches speech and
    slides by topic), a strong language model writes the content in four fixed sections,
    and the page lays it out. All the heavy work is local (the container) and
    deterministic; the model gets a compact JSON and returns one with an enforced schema.

WHO RUNS THE WORK
    __main__       starts the app
    setup          the guided setup in the terminal: who writes the notes, into .env
    settings       the environment variables (the .env), read and checked in one place
    server         the app: the server that serves the pages and receives courses and lectures
    updates        whether GitHub has a new version, to say so on the home page
    jobs           the job queue (one at a time, each in its own process, which can be
                   stopped), the steps with their weights, renaming courses, lecture
                   titles, deleting either, and the uploads from the browser
    processing     the core: a lecture's steps in a row, skipping those already done,
                   with a Progress that tells how far along it is; runs in the process
                   the queue starts for each lecture
    backup         the backup copy into another folder (a NAS), in a separate container

THE STEPS, in order, one module each
    video          ffmpeg: the duration; 16 kHz mono audio; one frame per second at 480 px;
                   the slide box; the segments in which the screen does not change
    slides         PyMuPDF: exact text of every page of the PDFs, and the page render
    transcription  faster-whisper on CPU (large-v3-turbo, the language chosen at upload), per-word
                   timestamps, initial prompt with the course and the slide titles
    alignment      each segment → the most similar page, the words to the segment in which
                   they were said: alignment.json; with voice only, whole slides and speech
    ocr            the on-screen text of the off-slide segments, from the full frame
    report         alignment.json → report.json, written by a vendor's own program (Claude
                   Code, Codex, Antigravity CLI: report/program.py) or by an OpenAI-compatible
                   API; instructions in report/ (prompt.md, schema.json); Quotes checks the quotes
    page           report + alignment → lecture.html, a single file, always the same;
                   page.indexes: the home and each course's index (page/ also holds
                   style.css and the scripts)
    check          check.html, the frame ↔ slide grid for checking by eye

    storage        what lives where: courses/<course>/<lecture>/, with work/ inside; files
                   written whole and synced to disk (atomic); the trash
    timecode       seconds ↔ "HH:MM:SS", and durations for readers

The measured numbers are in the README.
"""
