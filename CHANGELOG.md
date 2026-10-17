# What's new

The app shows the entries for versions newer than yours on the About page. Keep each line short and plain.

## 0.4.2
- Fixed: with some voices, takes started with an extra bit of word (like "…cado" before the first sentence), mostly with OmniVoice. The clip picked from a long recording could end in the middle of a word; it now ends at a real pause.
- Voice cards warn when a clip ends in the middle of a word (also for voices you already have), with how to fix it in Edit.

## 0.4.1
- New voice model (Windows): VoxCPM2. Copies a voice in 30 languages (Hindi, Arabic, Thai, Vietnamese, Turkish…) at 48 kHz. Free for commercial use; graphics cards with 8 GB or more.
- New voice model (Windows): CosyVoice 3. Fast; copies a voice in English, Spanish, French, German, Italian, Chinese, Korean and Cantonese. Free for commercial use.
- On graphics cards under 12 GB, the audio.cpp models now step aside while the subtitles are made, so the larger ones have room.

## 0.4.0
- New voice model (Windows): Chatterbox. Copies a voice in 23 languages, including Hindi, Arabic, Swahili and Turkish. Free for commercial use; needs a graphics card.
- New voice model (Windows): Kokoro. Very fast, with its own 15 voices, which are added to your voice library (marked Kokoro). Over 2× faster than real time even without a graphics card. Free for commercial use.
- New voice model (Windows): MOSS-TTS Nano. Tiny; copies a voice in English, Spanish, French, German and Chinese, faster than real time even without a graphics card. Free for commercial use.
- New voice model (Windows): OmniVoice. About 4× faster than real time in under 2 GB of graphics memory, 96 languages. Non-commercial (marked in red).
- Each new model brings its own small engine part, downloaded with it on the Models page.
- 15 more languages to pick for scripts, among them Cantonese, Hausa, Uzbek, Somali and Macedonian (for the models that speak them).
- Fixed: stopping a part at the wrong moment could stop the whole queue until the app was restarted.

## 0.3.4
- Fixed (Linux): Fish Audio S2 Pro couldn't be downloaded on the Models page ("isn't available to download yet").
- Mac: Fish Audio S2 Pro, on the Mac's graphics (Metal), after running `./build-s2.sh` once. Thanks to @Blarks-de.

## 0.3.3
- Graphics cards with less memory than a voice model needs (2-3 GB) work now instead of running out of memory: Qwen3-TTS puts what fits on the card and the rest in normal memory; S2 Pro runs on the processor there.
- Linux: one command installs everything on Debian, Ubuntu, Mint, Fedora, openSUSE and Arch, with the engines for your graphics card (CUDA for NVIDIA, Vulkan for the rest). S2 Pro and Whisper run on the card, as on Windows. Run it again to update.

## 0.3.2
- Fixed: Find a new voice and Hear it speak failed ("500 Internal Server Error") in languages like Hindi or Urdu. They now use a voice model that speaks the language (S2 Pro for Urdu), with ready sample sentences in 42 languages; for others, type a sentence for the voices to say.
- Find a new voice lists only the languages your downloaded voice models speak.

## 0.3.1
- Subtitles and transcripts use Whisper large-v3 turbo by themselves when Whisper runs on your graphics card and you have it: about as quick there as small, and much more accurate outside English. A model picked in Settings still wins.
- Create: each script's language list follows the voice model, so a script in a language only S2 Pro speaks (Hindi, Urdu…) shows it.

## 0.3.0
- A second voice model: Fish Audio S2 Pro (Windows). Very expressive, 80+ languages (Hindi, Urdu, Arabic, Turkish…), and it follows emotion tags like [whisper] or [excited] in the text. About real time on an NVIDIA card with 8 GB. Optional, and for non-commercial use (marked in red). Download it on the Models page.
- Language lists show what the chosen voice model speaks, and a model is told plainly when it doesn't speak a language.
- Words in [square brackets] other than [pause] are tags: never read aloud and never in the subtitles. (Qwen3-TTS skips them.)
- Voices remember what their clip says (Edit dialog), which S2 Pro uses to copy the voice.
- Chinese and Japanese: scripts are split into sentences and parts properly (a long script was spoken as one huge part), and subtitles are timed line by line instead of one block.
- Subtitles split long sentences into even pieces, without a few leftover words on their own.
- AI agents can't reach a non-commercial model through a preset or the default model either, unless you allow it on the Connect page.

## 0.2.6
- Updates moved to the About page (menu at the top right), next to your version. The update dot and messages point there.
- Fixed: a part could refuse to play ("no supported sources") after the batch page refreshed while a batch was running. Players now load again by themselves, and a part's audio only loads when you play it, so long batches open faster.

## 0.2.5
- Whisper runs on your graphics card, like the voice: subtitles and transcripts about 9× faster (a 26-minute script in about 40 seconds instead of 6½ minutes). NVIDIA, AMD and Intel cards; it sets itself up after the update with a small one-time download, and uses the processor if the card can't.
- On the processor, Whisper now runs at low priority with half the threads, so the PC stays usable.
- The top bar shows the subtitle step's progress, and whether it's on the graphics card or the processor.

## 0.2.4
- Tidier top bar: Create, Batches, Voices and Transcribe as tabs; Help (?) and a menu on the right with Settings, Pronunciation, Models, Setup, Connect and About.
- New About page: version, licences of your models, credits, and your PC's details to copy into a problem report.
- Dark mode: pick Light, Dark or Same as Windows in Settings → App.
- New audio players everywhere: a waveform you can click or drag to jump around, and only one plays at a time.
- Tidier voice cards: initials badge, buttons on one line (Make default is now a star), and a note under Add voice saying what's still needed.
- Parts show their state as a coloured strip (green done, amber to check, red failed), and the text lights up while a part plays.
- Create: script boxes grow as you type, and the queue shows how much audio you made today, this week and in all.
- Batch page: details as small labels, and the Whisper score in green, amber or red so scripts to check stand out.
- The top bar shows a filling ring while speaking (hover the line under it for the full text).
- Friendlier empty pages, grey placeholders while pages load, a quicker Settings page, and messages with an icon.
- Help is now built in: step-by-step guides for every part of the app, with search and a Help link on every page. Works offline.
- Works on a fresh Windows install: the app now brings the Microsoft Visual C++ Runtime the engines need, and says clearly when an engine can't start.
- Tidier Settings page: the cards sit in three even columns, Output is split into Speech and Files, and each folder has an Open button.
- Settings now shows the real MP3 quality (192 kbps by default), and offers 192 and 256.

## 0.2.3
- Clearer Updates panel in Settings: what's new, the download size, and what each button does.
- Ready-made English and Spanish pronunciation lists to import (in the dictionaries folder on GitHub).
- A pronunciation word that ends in a full stop (etc., p.m.) no longer swallows the sentence's own full stop.

## 0.2.2
- Windows now shows the right version number (in Installed apps and the program's details) after a Quick update.

## 0.2.1
- Pronunciation: import and export your word list (CSV, JSON or a plain text file).
- Update notices: a dot on Settings, a one-time message, and a Windows notification.

## 0.2.0
- Pronunciation dictionary: tell the voice how to say names, acronyms and abbreviations.
- Numbers, money, percentages, times and years are read as words.
- Speed control (0.85× to 1.2×) without changing the voice's pitch.
- Channel presets: save a voice and its settings, and pick them in one click.
- Transcribe page: turn audio or video into text or subtitles.
- Clean a voice clip taken from a video or song: the music and background are removed.

## 0.1.1
- Every Whisper size for subtitles, and a setting to choose which one is used.

## 0.1.0
- First release.
