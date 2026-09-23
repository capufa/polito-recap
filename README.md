# PoliTo Recap

> **Vibe-coded**: written by prompting an AI coding assistant, and tested on real lectures.

Turn a recorded lecture into a page you can study from.

> A personal student project. Not affiliated with or endorsed by Politecnico di Torino, nor by
> Anthropic, OpenAI or Google, whose programs it can run with your own account.

Give it the recording — the video with the slides on screen (`.mp4`) or just the audio
(`.mp3`) — and the slide PDFs. You get one page per lecture:

- **Lecture**: what the lecturer said about each slide, cleaned up, with timestamps
- **Off the slides**: what was on screen when no slide was (code, a website), read with OCR
- **Exam**: everything about the exam, with the lecturer's exact words
- **Notices**: cancelled lessons, deadlines, labs, office hours

Every timestamp jumps the player to that moment. Lectures are grouped by course, and you
can tick each slide as studied. A page is a single file: it opens offline, on any device.

Transcription, slide matching and OCR run on your computer. To write the notes, the whole
lecture goes to the model you choose — the transcript with its timestamps (students'
questions included), the slide text and the text read from the screen: your Claude, ChatGPT
or Google subscription, or an API key (Anthropic, OpenAI, Gemini, OpenRouter, Mistral,
DeepSeek). With a local model in Ollama or LM Studio nothing leaves your computer. Check
your provider's data policy: some free tiers train on what you send.

## Where it runs

You need [Docker](https://docs.docker.com/get-docker/) with Compose 2.24 or later
(`docker compose version`; Docker Desktop on Windows and macOS), at least 2.5 GB of free
memory, about 5 GB of disk plus your lectures (and 200–400 MB for a subscription's program),
and an account for the model that writes the notes (below).

| Computer | Works? | Why |
|---|---|---|
| Linux on Intel or AMD, 64-bit | yes | it runs every day on a mini PC with an Intel i5 |
| Windows or Intel Mac, with Docker Desktop | should, untested | the same image, in Docker Desktop's Linux virtual machine, which gets half the computer's memory by default (Settings → Resources) |
| Apple Silicon Mac, Raspberry Pi 5, other 64-bit ARM | should, untested | every part is published for 64-bit ARM and each release builds the image for it, but it has never run there |
| Raspberry Pi 4 | should, untested, slow | as above, on a CPU two to three times slower than the Pi 5's |
| 32-bit systems: 32-bit Raspberry Pi OS, Pi 3 and older | no | the speech engine, the OCR engine and the subscriptions' programs exist only for 64-bit |

Tried it on an untested one? Open an issue and say how it went.

**The setup picks the speech model by free memory, not by speed**: even on two slow cores
the default is faster than the lecture, which waits in a queue anyway.

| Speech model | Free memory | 1 hour of lecture: 4 fast cores / 4 slow / 2 slow | Words differing from large-v3 |
|---|---|---|---|
| `large-v3-turbo` (default) | 3.5 GB | 13 / 25 / 38 min | 4% |
| `small` | 2.5 GB | 7 / 10 / 13 min | 12% |

Measured on 10 minutes of a lecture on an Intel i5-12600H; a dense lecture takes up to a
third longer. Then the notes take 5–15 minutes with a cloud model.

**Raspberry Pi**: a Pi 5 with 8 GB and active cooling. Transcription should take about as
long as the lecture (an estimate, not a measurement). Its kernel uses 16 KB memory pages: the
libraries we checked load there, but only a real Pi can confirm it. If the app crashes at
start, switch to the 4 KB kernel: `kernel=kernel8.img` in `/boot/firmware/config.txt`, then
reboot.

## Install

```sh
mkdir polito-recap
cd polito-recap
curl -LO https://raw.githubusercontent.com/capufa/polito-recap/main/docker-compose.yml
docker compose run --rm setup
```

In Windows PowerShell type `curl.exe` instead of `curl`. The setup asks who writes the notes
(next section), the key or the sign-in and the model, tries them with a one-word question, and
writes everything into `.env`, next to `docker-compose.yml`. Keys are typed without showing.
For a subscription it installs the vendor's own program and starts its sign-in: open the link
it shows, sign in, and paste back the code if the browser gives you one. The sign-in stays with
that program, in a volume of Docker's own, never in `.env`. Then:

```sh
docker compose up -d
```

and open <http://localhost:8470>. The first lecture downloads the speech model (1.6 GB). If
something is missing or wrong, the page says what and how to fix it.

Run the setup again to change provider, key or model. On Linux, if Docker needs `sudo`, put
it before every `docker` command: the app still runs as the owner of the folder.

## Who writes the notes

The setup asks. What it writes into `.env`, if you'd rather do it by hand (a subscription's
sign-in only the setup can do):

| You have | `.env` |
|---|---|
| Claude Pro or Max | `REPORT_PROVIDER=claude`; Claude Code, installed and signed in by the setup |
| an Anthropic API key | `REPORT_PROVIDER=claude`, `REPORT_API_KEY=…`; Claude Code, installed by the setup |
| ChatGPT Plus, Pro or Business | `REPORT_PROVIDER=codex`, `REPORT_MODEL=` empty for Codex's default; Codex, installed and signed in by the setup |
| a Google account: free, AI Pro or Ultra | `REPORT_PROVIDER=antigravity`, `REPORT_MODEL=` one the setup lists; Antigravity CLI, installed and signed in by the setup |
| an OpenAI key | `REPORT_PROVIDER=openai`, `REPORT_API_KEY=…`, `REPORT_MODEL=` e.g. `gpt-5` |
| a Gemini key ([free](https://aistudio.google.com/apikey)) | `REPORT_PROVIDER=gemini`, `REPORT_API_KEY=…`, `REPORT_MODEL=` e.g. `gemini-3.8-flash` |
| an OpenRouter key (many models, some free) | `REPORT_PROVIDER=openrouter`, `REPORT_API_KEY=…`, `REPORT_MODEL=` e.g. `google/gemini-3.8-flash` |
| a Mistral or DeepSeek key | `REPORT_PROVIDER=mistral` or `deepseek`, `REPORT_API_KEY=…`, `REPORT_MODEL=…` |
| Ollama or LM Studio on this computer | `REPORT_PROVIDER=ollama` or `lmstudio`, `REPORT_MODEL=…` (no key) |
| any other OpenAI-compatible server | `REPORT_PROVIDER=compatible`, `REPORT_URL=…/v1`, `REPORT_API_KEY`, `REPORT_MODEL` |

**With a subscription** the notes are written by the vendor's own program — Claude Code,
Codex or Antigravity CLI — unmodified and signed in with your account: the setup installs it
and runs its sign-in, and the sign-in stays with the program. It is for your own use: don't let
others process lectures on your subscription. Running the setup again updates the program.

- **Claude**: keep "extra usage" off in your Claude settings. Anthropic may take a request for a
  third-party app's: with extra usage off it fails instead of being charged.
- **ChatGPT**: signing in with a one-time code may first need turning on in ChatGPT's security
  settings.
- **Google**, experimental: the model is one your account offers. In tests with Gemini Flash
  and Pro the notes covered the whole lecture but were thinner than Claude Opus's (5–6 exam
  items against 12–15). Antigravity's terms are unclear about use inside other programs, and on a personal
  account Google may use what it receives to train its models, and have people read it, unless
  "Enable Telemetry" is off in the program's settings: the setup reminds you.

The model reads 40–150k tokens and writes up to 30k: pick one with a long context and a
long output. Small local models write weak notes, and Ollama needs its context raised
(`OLLAMA_CONTEXT_LENGTH=131072` on its side), or it silently cuts the lecture.

On Windows and macOS the container reaches Ollama and LM Studio as they are. On Linux they
listen only on localhost, which the container cannot reach: make Ollama listen on the Docker
bridge, `OLLAMA_HOST=172.17.0.1:11434` (the address `ip -4 addr show docker0` prints; the
`ollama` command then needs the same variable). Don't use `0.0.0.0`: Ollama has no login, and
anyone on the same Wi-Fi could use it. LM Studio's "Serve on Local Network" opens it the same
way: only on networks you trust.

Tested end to end on a real 82-minute lecture: Claude Opus with a Max subscription, and Gemini
3.1 Pro through Antigravity with a Google AI Pro account. Codex is tested up to its sign-in, not
yet with a ChatGPT plan. The API providers speak the same standard API and are tested against a
mock server; if one misbehaves, open an issue.

## Using it

1. **+ New course**: type its name and press **Create**; the course opens.
2. Drop the recording and the PDF slides on the page, pick the lecture's language
   (Italiano or English), then press **▶ Process lecture**.
3. Once the upload is done, each step shows its progress and you can close the browser.
   Lectures wait in a queue.
4. When it's done, the lecture appears in the list: open it and study.

✎ renames a course or changes a lecture's title; 🗑 moves it to the trash for 30 days.
A lecture that stopped on an error (for example the model's usage limit) resumes from where
it was with **Resume**.

## Settings

Everything lives in `.env`, and every line of it says what it does (it starts as a copy of
[.env.example](.env.example)). After a change, `docker compose up -d` applies it. The ones
you are most likely to change:

| Setting | Default | What it does |
|---|---|---|
| `REPORT_PROVIDER`, `REPORT_MODEL` | `claude`, `opus` | who writes the notes (above) |
| `WHISPER_MODEL` | `large-v3-turbo` | the speech model, which the setup picks by free memory (above). `large-v3` is the most accurate, twice as slow and needs 5.5 GB; `medium` is worse than the default on every count; `distil-*` and `*.en` know English only |
| `WHISPER_THREADS`, `OCR_THREADS` | `4` | CPU threads, which the setup keeps within the CPUs there are; on CPUs with performance and efficiency cores, at most the performance cores |
| `OCR_MODEL` | `small` | reads screens without a slide: `tiny` is 2–8 times faster and on 10 test screens read as well, `medium` is 15 times slower (both downloaded on first use) |
| `RECAP_PORT`, `RECAP_BIND` | `8470`, `127.0.0.1` | where the app answers (below) |
| `RECAP_CPUS`, `RECAP_MEMORY` | `4`, `6g` | what the container may use: `RECAP_CPUS` no more than the CPUs Docker has, or it does not start |

The language is not a setting: you pick it for every lecture when you upload it. It tells
the speech model what to listen for, and the notes are written in it. The app itself is in
English.

## From other devices

By default the app only answers on this computer. To use it from your phone or tablet at
home, set `RECAP_BIND=0.0.0.0` and open `http://<this computer's IP>:8470`. There is no
login: whoever reaches it can do everything, so only do this on networks you trust — never
on university Wi-Fi, never on the internet. If you reach it by name (`mypc.local`, a
Tailscale name), add the name to `RECAP_HOSTNAMES`.

## Updating

The home page tells you when a new version is out (the app asks GitHub once a day;
`RECAP_UPDATE_URL=off` turns that off). Then:

```sh
docker compose pull
docker compose up -d
```

To stay on a version, set `RECAP_VERSION=1.0.0`. A lecture being processed during an
update restarts the step it was on.

## Your data

```
data/courses/<course>/<lecture>/lecture.html      the page
data/courses/<course>/<lecture>/<lecture>.mp4     the recording, next to it
data/courses/.trash/<date>/<course>[/<lecture>]   deleted lectures and courses, 30 days
data/models/                                      the speech model, and the OCR model unless it is small
```

A subscription's program and its sign-in live in a volume of Docker's own, not in `data`:
with the app stopped, `docker volume rm polito-recap_accounts` removes them and signs you out.
Claude Code and Codex keep no copy of a lecture there; Antigravity CLI keeps its own record of
every conversation, lectures included, until that volume goes.

To back up, copy `data/courses`. For an automatic hourly copy of the finished lectures to a
NAS or another disk, set `COMPOSE_PROFILES=backup` and `RECAP_BACKUP` to its mount point,
and create a `polito-recap` folder in it, writable by the app's user; while the NAS is not
mounted, the copy waits. This copy is for Linux: Docker Desktop cannot follow a NAS mounted
later.

The trash keeps each item's path under the date it was deleted. To restore a lecture, move
`.trash/<date>/<course>/<lecture>` back into `data/courses/<course>/` (create the course
folder if the course is gone); a whole course, move `.trash/<date>/<course>` back into
`data/courses/`. Then restart.

## How it works

```
recording ──ffmpeg──► 16 kHz audio ──faster-whisper──► words with timestamps
video ──ffmpeg──► 1 frame/s ──► segments where the screen doesn't change ──┐
slides.pdf ──PyMuPDF──► exact text and a render of every page ─────────────┴─► segment ↔ page
                                   segment with no page ──RapidOCR──► screen text
                                                                         ▼
                                            alignment.json ──model──► report.json ──► lecture.html
```

1. **Speech**: faster-whisper on the CPU, with a timestamp for every word.
2. **Screen** (video only): one frame per second; a new segment starts when the slide area
   changes; each segment is matched to the most similar PDF page, or read with OCR.
3. **Alignment**: every word goes to the segment it was said in.
4. **Notes**: the model gets the alignment and a fixed JSON schema, so it writes the content
   but not the layout. Quotes about the exam and notices are checked against the transcript.
5. **Page**: always the same layout, with the recording linked next to it.

Every slow step saves its result when done, so an interrupted lecture resumes where it was.

## Limits

- With audio only there is no screen: no "Off the slides", and the model matches speech to
  slides by topic.
- A slide deck you didn't upload is read with OCR: readable, not exact.
- One lecture at a time.
- No login (see above).

## Development

```sh
git clone https://github.com/capufa/polito-recap
cd polito-recap
docker build -t ghcr.io/capufa/polito-recap:latest .
docker compose run --rm setup
docker compose up -d
```

The image you build takes the place of the published one (`RECAP_VERSION=latest`). The
code map is the docstring of [recap/\_\_init\_\_.py](recap/__init__.py); each module explains
itself at the top. A tag `vX.Y.Z` publishes the image for Intel/AMD and ARM on GHCR and the
release notes ([release.yml](.github/workflows/release.yml)).

## License

[MIT](LICENSE)
